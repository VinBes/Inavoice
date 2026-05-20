"""Tests for the sequential missing-field collection flow."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import config
from bot.handlers import _sessions, handle_message
from bot.missing_field_flow import (
    build_overview_text,
    handle_missing_field_message,
)
from models.schemas import Contact
from models.session import Session

_CHAT_ID = int(config.ALLOWED_CHAT_IDS[0])


def _make_message_update(text: str):
    update = MagicMock()
    update.effective_chat.id = _CHAT_ID
    update.message.text = text
    update.message.reply_text = AsyncMock(return_value=MagicMock(message_id=99))
    return update


def _make_context(args=None):
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.args = args
    ctx.job_queue = MagicMock()
    ctx.job_queue.get_jobs_by_name = MagicMock(return_value=[])
    ctx.job_queue.run_once = MagicMock()
    return ctx


def _fill_missing_session(
    fields: list[str], parsed_data: dict | None = None
) -> Session:
    s = Session(mode="fill_missing")
    base_parsed = {
        "client_id": "client_a",
        "description": None,
        "line_items": [
            {
                "service_date": "26/03/2026",
                "service_description": "Service for Client A",
                "time_start": "22:00",
                "time_end": "00:00",
                "rate": 500,
                "rate_type": "hourly",
                "total": None,
            }
        ],
        "missing_fields": list(fields),
    }
    if parsed_data is not None:
        base_parsed.update(parsed_data)
    s.parsed_data = base_parsed
    s.contact_draft = {"_fields": list(fields), "_client_id": base_parsed.get("client_id")}
    return s


# ---------------------------------------------------------------------------
# build_overview_text
# ---------------------------------------------------------------------------


def test_overview_contains_all_fields():
    text = build_overview_text(["description", "rate"])
    # Both bullets present
    assert "• description" in text
    assert "• rate" in text
    # Location notes present
    assert "header line above the invoice table" in text
    assert "'Rate' column" in text
    # Examples present
    assert "Example:" in text
    assert "Invoice for Aesthetic Radio" in text
    assert "500" in text
    # First field's question is the trailing prompt
    assert "What's the header line for this invoice?" in text


def test_overview_unknown_field_no_crash():
    text = build_overview_text(["whatever_unknown"])
    assert isinstance(text, str)
    assert "• whatever_unknown" in text
    # No example/location note for the unknown field
    assert "Example:" not in text
    # Falls back to a generic prompt
    assert "Please provide whatever_unknown." in text


# ---------------------------------------------------------------------------
# Per-answer behavior — direct local assignment
# ---------------------------------------------------------------------------


async def test_first_answer_advances_to_next_field():
    _sessions.clear()
    s = _fill_missing_session(["description", "rate"])
    _sessions[_CHAT_ID] = s
    update = _make_message_update("DJ services")
    ctx = _make_context()
    await handle_missing_field_message(update, ctx, s, _CHAT_ID)

    assert s.contact_draft["_fields"] == ["rate"]
    assert s.parsed_data["description"] == "DJ services"


async def test_rate_validation_rejects_text():
    _sessions.clear()
    s = _fill_missing_session(["rate"])
    _sessions[_CHAT_ID] = s
    update = _make_message_update("lots")
    ctx = _make_context()
    await handle_missing_field_message(update, ctx, s, _CHAT_ID)

    # Field NOT consumed; user is re-prompted.
    assert s.contact_draft["_fields"] == ["rate"]
    reply = update.message.reply_text.await_args[0][0]
    assert "Rate must be a number" in reply
    assert "Try again" in reply


async def test_rate_validation_accepts_number():
    _sessions.clear()
    # Provide enough state that finishing rate triggers final merge — but we
    # only need to assert the patch into parsed_data here. To avoid the final
    # merge path, we make rate NOT the last field.
    s = _fill_missing_session(["rate", "description"])
    _sessions[_CHAT_ID] = s
    update = _make_message_update("500")
    ctx = _make_context()
    await handle_missing_field_message(update, ctx, s, _CHAT_ID)

    assert s.parsed_data["line_items"][0]["rate"] == "500"
    assert s.contact_draft["_fields"] == ["description"]


async def test_last_field_triggers_confirmation():
    _sessions.clear()
    s = _fill_missing_session(["rate"])
    _sessions[_CHAT_ID] = s
    update = _make_message_update("500")
    ctx = _make_context()

    fake_contact = Contact(
        client_id="client_a",
        display_name="Client A Ltd.",
        address="HK",
        email="billing@client-a.com",
    )
    fake_data = {
        "client_id": "client_a",
        "display_name": "Client A Ltd.",
        "address_lines": ["HK"],
        "description": "Invoice for Client A booking",
        "service_description": "Service for Client A",
        "rate": Decimal("500"),
        "total": Decimal("1000"),
        "email": "billing@client-a.com",
    }
    with (
        patch(
            "bot.missing_field_flow.get_contact",
            new=AsyncMock(return_value=fake_contact),
        ),
        patch(
            "bot.missing_field_flow.merge_and_compute",
            return_value=fake_data,
        ),
        patch(
            "bot.missing_field_flow.format_confirmation",
            return_value="CONFIRMATION-TEXT",
        ),
    ):
        await handle_missing_field_message(update, ctx, s, _CHAT_ID)

    # Last reply should be the confirmation message with keyboard.
    final_call = update.message.reply_text.await_args
    assert final_call[0][0] == "CONFIRMATION-TEXT"
    assert final_call.kwargs.get("reply_markup") is not None
    assert s.mode == "invoice"
    assert s.contact_draft is None
    assert s.computed_data == fake_data


async def test_client_id_not_found_re_prompts():
    _sessions.clear()
    s = _fill_missing_session(
        ["client_id"], parsed_data={"client_id": None}
    )
    s.contact_draft = {"_fields": ["client_id"], "_client_id": None}
    _sessions[_CHAT_ID] = s
    update = _make_message_update("ghost_client")
    ctx = _make_context()

    with patch(
        "bot.missing_field_flow.get_contact",
        new=AsyncMock(return_value=None),
    ):
        await handle_missing_field_message(update, ctx, s, _CHAT_ID)

    # Field NOT consumed.
    assert s.contact_draft["_fields"] == ["client_id"]
    reply = update.message.reply_text.await_args[0][0]
    assert "ghost_client" in reply
    assert "not found" in reply.lower()


async def test_empty_text_re_prompts():
    _sessions.clear()
    s = _fill_missing_session(["description"])
    _sessions[_CHAT_ID] = s
    update = _make_message_update("   ")
    ctx = _make_context()
    await handle_missing_field_message(update, ctx, s, _CHAT_ID)

    assert s.contact_draft["_fields"] == ["description"]
    reply = update.message.reply_text.await_args[0][0]
    assert "Please send a value" in reply


# ---------------------------------------------------------------------------
# Routing from handle_message
# ---------------------------------------------------------------------------


async def test_session_mode_routes_to_handler():
    _sessions.clear()
    s = _fill_missing_session(["description"])
    _sessions[_CHAT_ID] = s
    update = _make_message_update("anything")
    ctx = _make_context()

    with patch(
        "bot.handlers.handle_missing_field_message", new=AsyncMock()
    ) as mock_handler:
        await handle_message(update, ctx)

    mock_handler.assert_awaited_once()
