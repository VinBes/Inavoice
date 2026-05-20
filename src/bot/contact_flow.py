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
from bot.keyboards import (
    contact_confirm_keyboard,
    contact_delete_confirm_keyboard,
    contact_field_picker_keyboard,
)
from db.contacts import delete_contact, get_contact, upsert_contact
from db.invoices import count_invoices_for_contact
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
    _Step(
        "aliases",
        "Any alternate names or spoken variants for this client? "
        "Comma-separated, e.g. `AER, Aesthetic Radio, aesthetic`. "
        "Type `skip` if none.",
        required=False,
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


# ---------------------------------------------------------------------------
# /contacts edit <client_id> flow
# ---------------------------------------------------------------------------

# `client_id` is the primary key and intentionally NOT editable here — to rename
# a contact, the user must delete + re-add. All other Contact fields are
# editable.
_EDITABLE_FIELDS: tuple[str, ...] = (
    "display_name",
    "address",
    "contact_person",
    "email",
    "default_description",
    "default_service_description",
    "default_rate",
    "aliases",
)


def _step_by_field(field: str) -> _Step:
    """Look up the existing _Step for `field` so we reuse its validators."""
    for step in _STEPS:
        if step.field == field:
            return step
    raise KeyError(f"Unknown editable field: {field!r}")


def _format_current_value(field: str, value: object) -> str:
    """Render the current value of a field for the 'Current X: ...' prompt."""
    if field == "aliases":
        if not value:
            return "(not set)"
        if isinstance(value, list):
            return ", ".join(value)
        return str(value)
    if value in (None, ""):
        return "(not set)"
    if field == "default_rate":
        # Decimal — render without trailing zeros / scientific notation.
        try:
            return format(Decimal(str(value)).normalize(), "f")
        except (InvalidOperation, ValueError):
            return str(value)
    return str(value)


async def _start_contact_edit(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    client_id: str,
) -> None:
    """Begin a guided /contacts edit session for `chat_id` and `client_id`."""
    from bot.handlers import _reset_timeout, _sessions

    existing = _sessions.get(chat_id)
    if existing is not None and existing.state == GENERATING:
        await update.message.reply_text(
            "An invoice is being generated. Please wait for it to finish."
        )
        return

    contact = await get_contact(client_id)
    if contact is None:
        await update.message.reply_text(
            f"No contact named {client_id}. Use /contacts to see the list."
        )
        return

    if existing is not None and existing.state == PENDING:
        log.info("contact_edit.replaced_pending_session", chat_id=chat_id)
        await update.message.reply_text(
            "Your pending invoice draft has been cancelled. Starting contact edit…"
        )

    session = Session(mode="edit_contact")
    session.contact_draft = {"client_id": client_id}
    _sessions[chat_id] = session

    await update.message.reply_text(
        format_contact_summary(contact.model_dump())
        + "\n\nWhich field would you like to edit?",
        reply_markup=contact_field_picker_keyboard(),
    )
    _reset_timeout(chat_id, context)
    log.info("contact_edit.started", chat_id=chat_id, client_id=client_id)


async def _show_field_picker_via_query(
    query,
    contact: Contact,
) -> None:
    """Send the summary + picker keyboard as a fresh message after a field
    edit. We post a new message rather than `edit_message_text` because the
    previous bot message was a free-form prompt, not a keyboard message."""
    await query.message.reply_text(
        format_contact_summary(contact.model_dump())
        + "\n\nWhich field would you like to edit next?",
        reply_markup=contact_field_picker_keyboard(),
    )


async def _execute_contact_edit_field_pick(
    query,
    session: Session,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    field: str,
) -> None:
    """User tapped a field button. Stash the field and prompt for new value."""
    from bot.handlers import _reset_timeout

    if field not in _EDITABLE_FIELDS:
        await query.message.reply_text(
            f"Field {field!r} is not editable. Pick another."
        )
        return

    client_id = (session.contact_draft or {}).get("client_id")
    if client_id is None:
        await query.message.reply_text(
            "Edit session is missing a client ID. Please run /contacts edit again."
        )
        return

    contact = await get_contact(client_id)
    if contact is None:
        await query.message.reply_text(
            f"Contact {client_id} no longer exists. Edit cancelled."
        )
        from bot.handlers import _sessions
        _sessions.pop(chat_id, None)
        return

    step = _step_by_field(field)
    draft = session.contact_draft or {}
    draft["_editing_field"] = field
    session.contact_draft = draft
    session.last_active = datetime.now(timezone.utc)

    current = _format_current_value(field, getattr(contact, field))
    label = field.replace("_", " ").capitalize()
    if step.required:
        prompt = (
            f"Current {label}: {current}\n\n"
            f"Send the new value."
        )
    else:
        prompt = (
            f"Current {label}: {current}\n\n"
            f"Send the new value (or type 'skip' to clear)."
        )
    await query.message.reply_text(prompt)
    _reset_timeout(chat_id, context)


async def handle_contact_edit_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    session: Session,
    chat_id: int,
) -> None:
    """Process one user message during the /contacts edit flow.

    Reads `_editing_field` from the draft. If absent, the user sent text
    before tapping a button — instruct them to use the picker.
    """
    from bot.handlers import _reset_timeout, _sessions

    draft = session.contact_draft or {}
    field = draft.get("_editing_field")
    client_id = draft.get("client_id")

    if field is None:
        await update.message.reply_text(
            "Tap one of the field buttons to choose what to edit, "
            "or tap Done to finish."
        )
        return

    if client_id is None:
        await update.message.reply_text(
            "Edit session is missing a client ID. Please run /contacts edit again."
        )
        _sessions.pop(chat_id, None)
        return

    step = _step_by_field(field)
    text = (update.message.text or "").strip()

    # Optional fields: 'skip' clears the value.
    if not step.required and text.lower() == _SKIP_TOKEN:
        new_value: object = None
    elif step.required and not text:
        await update.message.reply_text(
            "This field is required. Please send a value."
        )
        return
    else:
        new_value = text
        if step.validate is not None:
            try:
                new_value = step.validate(text)
            except ValidationError as e:
                errors = e.errors()
                msg = errors[0]["msg"] if errors else "Invalid value."
                if msg.startswith("Value error, "):
                    msg = msg[len("Value error, "):]
                await update.message.reply_text(f"{msg} Try again.")
                return
            except ValueError as e:
                await update.message.reply_text(f"{e} Try again.")
                return

    contact = await get_contact(client_id)
    if contact is None:
        await update.message.reply_text(
            f"Contact {client_id} no longer exists. Edit cancelled."
        )
        _sessions.pop(chat_id, None)
        return

    payload = contact.model_dump()
    payload[field] = new_value
    try:
        updated = Contact.model_validate(payload)
    except ValidationError as e:
        errors = e.errors()
        msg = errors[0]["msg"] if errors else "Invalid value."
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, "):]
        await update.message.reply_text(f"{msg} Try again.")
        return

    try:
        await upsert_contact(updated)
    except Exception:
        log.exception("contact_edit.upsert_failed", client_id=client_id, field=field)
        await update.message.reply_text(
            "Failed to save the change. Try again in a minute."
        )
        return

    # Clear _editing_field so any stray text after the re-shown picker is
    # routed back to the "tap a button" instruction.
    draft.pop("_editing_field", None)
    session.contact_draft = draft
    session.last_active = datetime.now(timezone.utc)

    log.info(
        "contact_edit.field_updated",
        chat_id=chat_id,
        client_id=client_id,
        field=field,
    )

    await update.message.reply_text(
        format_contact_summary(updated.model_dump())
        + "\n\nWhich field would you like to edit next?",
        reply_markup=contact_field_picker_keyboard(),
    )
    _reset_timeout(chat_id, context)


async def _execute_contact_edit_done(
    query,
    session: Session,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Done button: clear timeout, drop session, acknowledge."""
    from bot.handlers import _sessions

    for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
        job.schedule_removal()

    _sessions.pop(chat_id, None)
    log.info("contact_edit.done", chat_id=chat_id)
    await query.edit_message_text("Contact updates saved.")


# ---------------------------------------------------------------------------
# /contacts delete <client_id> flow
# ---------------------------------------------------------------------------
#
# Callback-driven, no SessionMode of its own. Pre-checks the FK count to give a
# friendly refusal when invoices reference the contact, then re-checks at
# confirm time (TOCTOU defense). The session only carries `delete_target` so
# stale callbacks (different client_id) can be detected and ignored.


async def _start_contact_delete(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    client_id: str,
) -> None:
    """Begin a /contacts delete confirm flow for `chat_id` and `client_id`."""
    from bot.handlers import _reset_timeout, _sessions

    existing = _sessions.get(chat_id)
    if existing is not None and existing.state == GENERATING:
        await update.message.reply_text(
            "An invoice is being generated. Please wait for it to finish."
        )
        return

    contact = await get_contact(client_id)
    if contact is None:
        await update.message.reply_text(
            f"No contact named {client_id}. Use /contacts to see the list."
        )
        return

    invoice_count = await count_invoices_for_contact(client_id)
    if invoice_count > 0:
        log.info(
            "contact_delete.refused_invoices_exist",
            chat_id=chat_id,
            client_id=client_id,
            count=invoice_count,
        )
        await update.message.reply_text(
            f"Cannot delete {client_id}: {invoice_count} invoice(s) reference "
            "this contact. Delete those first or keep the contact."
        )
        return

    if existing is not None and existing.state == PENDING:
        log.info("contact_delete.replaced_pending_session", chat_id=chat_id)
        await update.message.reply_text(
            "Your pending invoice draft has been cancelled. Starting contact deletion…"
        )

    if existing is not None and existing.mode == "add_contact":
        log.info("contact_delete.replaced_add_contact_session", chat_id=chat_id)
        await update.message.reply_text(
            "Your in-progress contact setup has been cancelled. Starting contact deletion…"
        )

    session = Session()
    session.delete_target = client_id
    _sessions[chat_id] = session

    await update.message.reply_text(
        format_contact_summary(contact.model_dump())
        + f"\n\nDelete this contact?",
        reply_markup=contact_delete_confirm_keyboard(client_id),
    )
    _reset_timeout(chat_id, context)
    log.info("contact_delete.started", chat_id=chat_id, client_id=client_id)


async def _execute_contact_delete_confirm(
    query,
    session: Session,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
    client_id: str,
) -> None:
    """Confirm tap: verify target, re-check invoice count, then delete."""
    from bot.handlers import _sessions

    # Stale callback (button from a previous prompt for a different client_id).
    if session.delete_target != client_id:
        log.info(
            "contact_delete.stale_callback_ignored",
            chat_id=chat_id,
            target=session.delete_target,
            callback_client_id=client_id,
        )
        return

    # Cancel the pending timeout job so a successful delete doesn't trip a
    # spurious 'session expired' message later.
    for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
        job.schedule_removal()

    # TOCTOU re-check: an invoice may have been inserted between the command
    # and the confirm tap. The DB FK would also catch this, but the friendly
    # error is nicer than a generic delete failure.
    invoice_count = await count_invoices_for_contact(client_id)
    if invoice_count > 0:
        log.info(
            "contact_delete.refused_invoices_exist",
            chat_id=chat_id,
            client_id=client_id,
            count=invoice_count,
        )
        await query.edit_message_text(
            f"Cannot delete {client_id}: {invoice_count} invoice(s) reference "
            "this contact. Delete those first or keep the contact."
        )
        _sessions.pop(chat_id, None)
        return

    try:
        await delete_contact(client_id)
    except Exception:
        log.exception("contact_delete.failed", chat_id=chat_id, client_id=client_id)
        await query.edit_message_text(
            "Failed to delete contact. It may still have invoices linked. "
            "Try again or check the database."
        )
        _sessions.pop(chat_id, None)
        return

    _sessions.pop(chat_id, None)
    log.info("contact_delete.completed", chat_id=chat_id, client_id=client_id)
    await query.edit_message_text(f"Contact {client_id} deleted.")


async def _execute_contact_delete_cancel(
    query,
    session: Session,
    chat_id: int,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """Cancel tap: clear timeout, drop session, acknowledge."""
    from bot.handlers import _sessions

    for job in context.job_queue.get_jobs_by_name(f"timeout_{chat_id}"):
        job.schedule_removal()

    _sessions.pop(chat_id, None)
    log.info("contact_delete.cancelled", chat_id=chat_id, source="button")
    await query.edit_message_text("Deletion cancelled.")
