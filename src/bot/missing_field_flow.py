"""Sequential missing-field collection for the invoice flow.

State machine layered on top of `Session(mode="fill_missing")`. When the
authoritative missing-fields list (computed by `_augment_missing_fields` in
handlers.py against the resolved contact's defaults) is non-empty, this module
takes over: it sends a rich human-readable OVERVIEW message that maps each
missing field to its location on the invoice + an example, then collects ONE
field per message until the list is exhausted.

Key design point: per-answer assignment is DIRECT and LOCAL — no LLM call per
reply. The user's reply is the raw value for the current field, validated
locally (for `rate`: positive Decimal; for `client_id`: existence in contacts).
Extra information the user types alongside the value is ignored — they can use
[Edit] on the confirmation card to refine further (which routes back through
the correction-mode LLM call).

Like contact_flow.py, this module never touches `_sessions` directly. The
caller (handlers.py) owns the session map. `_reset_timeout` and `_sessions`
are lazy-imported inside functions to avoid a circular import at module load.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

import structlog

from bot.formatting import format_confirmation
from bot.keyboards import confirm_keyboard
from db.contacts import get_contact
from models.schemas import LLMOutput
from models.session import Session
from services.invoice_service import merge_and_compute

log = structlog.get_logger()


@dataclass(frozen=True)
class _MissingFieldStep:
    field: str
    question: str
    location_note: str
    example: str
    validate: Optional[Callable[[str], object]] = None


def _validate_rate(text: str) -> Decimal:
    try:
        rate = Decimal(text)
    except (InvalidOperation, ValueError) as e:
        raise ValueError("Rate must be a number, e.g. `500` or `750.50`.") from e
    if rate <= 0:
        raise ValueError("Rate must be positive.")
    return rate


_FIELD_STEPS: dict[str, _MissingFieldStep] = {
    "description": _MissingFieldStep(
        field="description",
        question=(
            "What's the header line for this invoice? (appears above the "
            "invoice table — e.g. `Invoice for Aesthetic Radio, Art.berdeen "
            "booking`)"
        ),
        location_note="header line above the invoice table",
        example="`Invoice for Aesthetic Radio, Art.berdeen booking`",
    ),
    "service_description": _MissingFieldStep(
        field="service_description",
        question=(
            "What service was provided? (appears in the 'Service' column of "
            "the line-item table — e.g. `DJ set at Aesthetic Radio HK`)"
        ),
        location_note="'Service' column in the line-item table",
        example="`DJ set at Aesthetic Radio HK`",
    ),
    "rate": _MissingFieldStep(
        field="rate",
        question=(
            "What's the rate in HKD? (hourly rate or flat-fee amount, e.g. "
            "`500`)"
        ),
        location_note="'Rate' column in the line-item table",
        example="`500`",
        validate=_validate_rate,
    ),
    "client_id": _MissingFieldStep(
        field="client_id",
        question=(
            "Which client is this invoice for? Send the client ID (e.g. "
            "`aesthetic_radio`). Use /contacts to see the list."
        ),
        location_note="recipient block at the top of the invoice",
        example="`aesthetic_radio`",
    ),
}


def build_overview_text(fields: list[str]) -> str:
    """Build the rich overview message that precedes the first question.

    For each field we know about, emits a bullet describing where it appears on
    the invoice and an example. Unknown fields get a bare bullet — defensive in
    case `_augment_missing_fields` ever adds a new field name before this
    module catches up.
    """
    lines: list[str] = [
        "I need a few more details before I can generate your invoice.",
        "",
        "Here's what's missing:",
        "",
    ]
    for field in fields:
        step = _FIELD_STEPS.get(field)
        if step is None:
            lines.append(f"• {field}")
            lines.append("")
            continue
        lines.append(f"• {field} — {step.location_note}")
        lines.append(f"  Example: {step.example}")
        lines.append("")

    lines.append("Let's go one at a time.")
    lines.append("")
    first_field = fields[0]
    first_step = _FIELD_STEPS.get(first_field)
    if first_step is None:
        lines.append(f"Please provide {first_field}.")
    else:
        lines.append(first_step.question)
    return "\n".join(lines)


async def _start_missing_field_flow(
    message,
    context,
    session: Session,
    chat_id: int,
    fields: list[str],
) -> None:
    """Begin the sequential missing-field collection flow.

    Caller (handlers.py) has already set `session.parsed_data` with the partial
    LLM output; we stash the working state in `session.contact_draft` and send
    the overview message containing the first question.
    """
    from bot.handlers import _reset_timeout

    session.mode = "fill_missing"
    session.contact_draft = {
        "_fields": list(fields),
        "_client_id": (session.parsed_data or {}).get("client_id"),
    }
    session.last_active = datetime.now(timezone.utc)

    await message.reply_text(build_overview_text(fields))
    _reset_timeout(chat_id, context)
    log.info("fill_missing.started", chat_id=chat_id, fields=fields)


async def handle_missing_field_message(
    update,
    context,
    session: Session,
    chat_id: int,
) -> None:
    """Process one user message during the fill_missing flow.

    The current field is the first entry in `_fields`. The user's text is the
    raw value: validated locally, patched into `session.parsed_data`, and the
    field is popped. When `_fields` is empty we validate the assembled
    `LLMOutput`, run `merge_and_compute`, and show the confirmation card.
    """
    from bot.handlers import _reset_timeout, _sessions

    draft = session.contact_draft or {}
    fields_remaining: list[str] = list(draft.get("_fields", []))

    if not fields_remaining:
        # Defensive: confirmation card has buttons, not text. If the user
        # somehow lands here we just remind them to tap a button.
        await update.message.reply_text("Tap Confirm or Cancel to finish.")
        return

    current_field = fields_remaining[0]
    step = _FIELD_STEPS.get(current_field)
    text = (update.message.text or "").strip()

    if not text:
        await update.message.reply_text("Please send a value.")
        return

    if step is not None and step.validate is not None:
        try:
            value: object = step.validate(text)
        except ValueError as e:
            await update.message.reply_text(f"{e} Try again.")
            return
    else:
        value = text

    # Patch the value into parsed_data at the correct nesting level.
    parsed = session.parsed_data or {}
    if current_field == "client_id":
        # client_id needs DB existence check — bail before mutating parsed_data
        # so a typo doesn't poison the session.
        contact = await get_contact(str(value))
        if contact is None:
            await update.message.reply_text(
                f"Contact {value!r} not found. Send a known client ID "
                f"(use /contacts to list)."
            )
            return
        parsed["client_id"] = str(value)
        draft["_client_id"] = str(value)
    elif current_field == "description":
        parsed["description"] = value
    elif current_field in ("service_description", "rate"):
        line_items = parsed.setdefault("line_items", [{}])
        if not line_items:
            line_items.append({})
        item = line_items[0]
        if current_field == "rate":
            item["rate"] = str(value)  # Decimal → JSON-safe string
        else:
            item["service_description"] = value
    else:
        # Unknown field — write to top-level as a best-effort fallback.
        parsed[current_field] = value

    session.parsed_data = parsed

    fields_remaining.pop(0)
    draft["_fields"] = fields_remaining
    session.contact_draft = draft
    session.last_active = datetime.now(timezone.utc)

    if fields_remaining:
        next_field = fields_remaining[0]
        next_step = _FIELD_STEPS.get(next_field)
        next_question = (
            next_step.question if next_step else f"Please provide {next_field}."
        )
        await update.message.reply_text(next_question)
        _reset_timeout(chat_id, context)
        return

    # Last field done — validate the full LLMOutput, merge with the contact,
    # and show the confirmation card. Every required field has been validated
    # individually, so get_contact must succeed here.
    result = LLMOutput.model_validate(session.parsed_data)
    contact = await get_contact(result.client_id)

    try:
        data = merge_and_compute(result, contact)
    except ValueError as e:
        await update.message.reply_text(str(e))
        _sessions.pop(chat_id, None)
        return

    session.computed_data = data
    session.mode = "invoice"
    session.contact_draft = None

    has_email = bool(data.get("email"))
    msg = await update.message.reply_text(
        format_confirmation(data), reply_markup=confirm_keyboard(has_email)
    )
    session.message_id = msg.message_id
    _reset_timeout(chat_id, context)
    log.info(
        "fill_missing.completed", chat_id=chat_id, client_id=result.client_id
    )
