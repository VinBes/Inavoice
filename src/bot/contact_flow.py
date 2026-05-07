"""Guided /contacts add conversational flow.

State machine layered on top of `Session(mode="add_contact")`. One field is
collected per message; `skip` is accepted for optional fields. After the last
step, a summary is shown with Confirm/Cancel buttons; Confirm validates the
draft against `Contact` and calls `upsert_contact`.

The flow never touches `_sessions` directly — the caller (handlers.py) owns
the session map and passes the relevant Session in.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

import structlog
from pydantic import ValidationError
from telegram import Update
from telegram.ext import ContextTypes

from bot.formatting import format_contact_summary
from bot.keyboards import contact_confirm_keyboard
from db.contacts import upsert_contact
from models.schemas import Contact
from models.session import GENERATING, PENDING, Session

log = structlog.get_logger()

_SKIP_TOKEN = "skip"


@dataclass(frozen=True)
class _Step:
    field: str
    prompt: str
    required: bool
    validate: Optional[Callable[[str], object]] = None  # returns coerced value, raises ValueError


def _validate_client_id(text: str) -> str:
    # Defer to the Contact model's validator so the rule lives in one place.
    Contact(client_id=text, display_name="x", address="x")
    return text


def _validate_email(text: str) -> str:
    Contact(client_id="x", display_name="x", address="x", email=text)
    return text


def _validate_rate(text: str) -> Decimal:
    try:
        rate = Decimal(text)
    except (InvalidOperation, ValueError) as e:
        raise ValueError("Rate must be a number, e.g. `500` or `750.50`.") from e
    if rate <= 0:
        raise ValueError("Rate must be positive.")
    return rate


_STEPS: tuple[_Step, ...] = (
    _Step(
        "client_id",
        "What's the client ID? Lowercase letters, digits, and underscores only "
        "(e.g. `aesthetic_radio`).",
        required=True,
        validate=_validate_client_id,
    ),
    _Step(
        "display_name",
        "What's the display name as it should appear on the invoice "
        "(e.g. `Aesthetic Radio HK`)?",
        required=True,
    ),
    _Step(
        "address",
        "Billing address? Multi-line is fine — send it as one message.",
        required=True,
    ),
    _Step(
        "contact_person",
        "Contact person at the client? Type `skip` if there isn't a specific name.",
        required=False,
    ),
    _Step(
        "email",
        "Client email address for invoices? Type `skip` if you'll only deliver via Telegram.",
        required=False,
        validate=_validate_email,
    ),
    _Step(
        "default_description",
        "Default invoice description (header line on the invoice)? Type `skip` to set per-invoice.",
        required=False,
    ),
    _Step(
        "default_service_description",
        "Default service description (the line item)? Type `skip` to set per-invoice.",
        required=False,
    ),
    _Step(
        "default_rate",
        "Default rate in HKD? Type `skip` if you'll always specify per invoice.",
        required=False,
        validate=_validate_rate,
    ),
)


def _summary_text(draft: dict) -> str:
    return format_contact_summary(draft)


async def _start_contact_add(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
) -> None:
    """Begin a guided /contacts add session for `chat_id`.

    Imports `_sessions` and `_reset_timeout` lazily from handlers to avoid a
    circular import at module load time.
    """
    from bot.handlers import _reset_timeout, _sessions

    existing = _sessions.get(chat_id)
    if existing is not None and existing.state == GENERATING:
        await update.message.reply_text(
            "An invoice is being generated. Please wait for it to finish."
        )
        return

    if existing is not None and existing.state == PENDING:
        log.info("contact_add.replaced_pending_session", chat_id=chat_id)
        await update.message.reply_text(
            "Your pending invoice draft has been cancelled. Starting contact setup…"
        )

    session = Session(mode="add_contact")
    session.contact_draft = {"_step": 0}
    _sessions[chat_id] = session

    await update.message.reply_text(
        "Let's add a new contact. You can type `skip` for optional fields.\n\n"
        + _STEPS[0].prompt
    )
    _reset_timeout(chat_id, context)
    log.info("contact_add.started", chat_id=chat_id)


async def handle_contact_add_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: Session,
    chat_id: int,
) -> None:
    """Process one user message during the /contacts add flow.

    Mutates `session.contact_draft` in place. Caller (handlers.py) owns the
    session map.
    """
    from bot.handlers import _reset_timeout

    draft = session.contact_draft or {}
    step_idx = draft.get("_step", 0)

    if step_idx >= len(_STEPS):
        # Defensive: user typed text after the summary was shown; ignore (callback decides).
        await update.message.reply_text(
            "Tap Confirm or Cancel to finish. No further input is needed."
        )
        return

    step = _STEPS[step_idx]
    text = (update.message.text or "").strip()

    # Optional-field skip path
    if not step.required and text.lower() == _SKIP_TOKEN:
        draft[step.field] = None
        draft["_step"] = step_idx + 1
        session.contact_draft = draft
        session.last_active = datetime.now(timezone.utc)
        await _advance_or_finish(update, context, session, chat_id)
        _reset_timeout(chat_id, context)
        return

    # Required-field empty input → re-prompt without advancing.
    if step.required and not text:
        await update.message.reply_text(
            "This field is required. Please send a value."
        )
        return

    value: object = text
    if step.validate is not None:
        try:
            value = step.validate(text)
        except ValidationError as e:
            # Surface the first validator message; full ValidationError is verbose.
            errors = e.errors()
            msg = errors[0]["msg"] if errors else "Invalid value."
            # Strip the "Value error, " prefix Pydantic adds to ValueError messages.
            if msg.startswith("Value error, "):
                msg = msg[len("Value error, "):]
            await update.message.reply_text(f"{msg} Try again.")
            return
        except ValueError as e:
            await update.message.reply_text(f"{e} Try again.")
            return

    draft[step.field] = value
    draft["_step"] = step_idx + 1
    session.contact_draft = draft
    session.last_active = datetime.now(timezone.utc)
    await _advance_or_finish(update, context, session, chat_id)
    _reset_timeout(chat_id, context)


async def _advance_or_finish(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: Session,
    chat_id: int,
) -> None:
    draft = session.contact_draft or {}
    step_idx = draft.get("_step", 0)
    if step_idx < len(_STEPS):
        await update.message.reply_text(_STEPS[step_idx].prompt)
        return

    # All steps collected; show summary + confirm/cancel.
    summary_draft = {k: v for k, v in draft.items() if not k.startswith("_")}
    await update.message.reply_text(
        _summary_text(summary_draft) + "\n\nSave this contact?",
        reply_markup=contact_confirm_keyboard(),
    )


async def _execute_contact_confirm(
    query,
    session: Session,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Validate the draft and persist via upsert_contact."""
    from bot.handlers import _sessions

    # Cancel the pending timeout job; otherwise we'd see a spurious 'session expired'
    # message ~30 minutes after success.
    for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
        job.schedule_removal()

    draft = {k: v for k, v in (session.contact_draft or {}).items() if not k.startswith("_")}
    try:
        contact = Contact.model_validate(draft)
    except ValidationError as e:
        log.error(
            "contact_add.validation_failed",
            client_id=draft.get("client_id"),
            error=str(e),
        )
        await query.edit_message_text(
            "Contact data failed validation. Please start over with /contacts add."
        )
        _sessions.pop(chat_id, None)
        return

    try:
        await upsert_contact(contact)
    except Exception:
        log.exception("contact_add.upsert_failed", client_id=contact.client_id)
        await query.edit_message_text(
            "Failed to save contact. Try again in a minute."
        )
        _sessions.pop(chat_id, None)
        return

    _sessions.pop(chat_id, None)
    log.info("contact_add.saved", client_id=contact.client_id)
    await query.edit_message_text(
        f"Contact {contact.client_id} saved. You can now invoice them by name."
    )
