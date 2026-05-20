"""Tests for PB3-2: 'Did you mean X?' inline keyboard picker.

When the LLM returns ``client_id: None`` and that's the ONLY missing field,
``handle_message`` shows an inline keyboard listing known contacts instead of
falling through to the sequential missing-field flow. Each contact button has
callback data ``pick_client:<client_id>``; an extra ``pick_client:__none__``
button dismisses the prompt.

The picker's callback handler (in ``bot.handlers.handle_callback``) patches the
chosen ``client_id`` into the stashed parsed data, re-runs
``_augment_missing_fields`` against the picked contact's defaults, and either
hands off to the missing-field flow (if other fields are still null and the
contact has no defaults) or shows the confirmation card directly.
"""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import config
from bot.handlers import _sessions, handle_callback, handle_message
from bot.keyboards import pick_client_keyboard
from models.schemas import Contact, LLMLineItem, LLMOutput
from models.session import PENDING, Session

_CHAT_ID = int(config.ALLOWED_CHAT_IDS[0])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message_update(text: str):
    update = MagicMock()
    update.effective_chat.id = _CHAT_ID
    update.message.text = text
    update.message.reply_text = AsyncMock(return_value=MagicMock(message_id=99))
    return update


def _make_context():
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.job_queue = MagicMock()
    ctx.job_queue.get_jobs_by_name = MagicMock(return_value=[])
    ctx.job_queue.run_once = MagicMock()
    return ctx


def _make_callback(data: str):
    query = MagicMock()
    query.data = data
    query.message.chat_id = _CHAT_ID
    query.from_user.id = _CHAT_ID
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.reply_text = AsyncMock(return_value=MagicMock(message_id=101))
    query.message.reply_document = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


def _full_parsed_data(client_id: str | None = "client_a") -> dict:
    """A complete LLMOutput-shaped dict (used as session.parsed_data)."""
    return {
        "client_id": client_id,
        "description": "Invoice for Client A booking",
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
        "missing_fields": ["client_id"],
    }


def _client_a_contact() -> Contact:
    return Contact(
        client_id="client_a",
        display_name="Client A Ltd.",
        contact_person=None,
        address="HK",
        email="billing@client-a.com",
        default_description="Invoice for Client A booking",
        default_service_description="Service for Client A",
        default_rate=Decimal("500"),
    )


def _client_b_contact() -> Contact:
    return Contact(
        client_id="client_b",
        display_name="Client B Ltd.",
        contact_person=None,
        address="Kowloon",
        email=None,
        default_description=None,
        default_service_description=None,
        default_rate=None,
    )


# ---------------------------------------------------------------------------
# Keyboard shape
# ---------------------------------------------------------------------------


def test_pick_client_keyboard_shape():
    contacts = [_client_a_contact(), _client_b_contact()]
    kb = pick_client_keyboard(contacts)
    rows = kb.inline_keyboard

    # One row per contact + final "None of these" row.
    assert len(rows) == 3

    # First row: client_a button.
    assert len(rows[0]) == 1
    btn_a = rows[0][0]
    assert btn_a.text == "Client A Ltd. (client_a)"
    assert btn_a.callback_data == "pick_client:client_a"

    # Second row: client_b button.
    btn_b = rows[1][0]
    assert btn_b.text == "Client B Ltd. (client_b)"
    assert btn_b.callback_data == "pick_client:client_b"

    # Final row: dismissal button.
    assert len(rows[2]) == 1
    none_btn = rows[2][0]
    assert none_btn.text == "None of these"
    assert none_btn.callback_data == "pick_client:__none__"


# ---------------------------------------------------------------------------
# handle_message — picker shown when only client_id is missing
# ---------------------------------------------------------------------------


async def test_unknown_client_shows_picker():
    """When the LLM returns client_id=None and everything else is filled, the
    bot replies with the picker keyboard rather than starting the missing-field
    flow."""
    _sessions.clear()

    llm_result = LLMOutput(
        client_id=None,
        description="Invoice for tonight",
        line_items=[
            LLMLineItem(
                service_date="26/03/2026",
                service_description="DJ set",
                time_start="22:00",
                time_end="00:00",
                rate=500,
                rate_type="hourly",
                total=None,
            )
        ],
        missing_fields=[],
    )
    contacts = [_client_a_contact(), _client_b_contact()]

    update = _make_message_update("invoice for tonight 22:00 to 00:00 at 500/hr")
    ctx = _make_context()

    with (
        patch("bot.handlers.parse_invoice_text", return_value=llm_result),
        patch("bot.handlers.list_contacts", return_value=contacts),
        patch(
            "bot.handlers._start_missing_field_flow", new=AsyncMock()
        ) as mock_start_missing,
    ):
        await handle_message(update, ctx)

    # _start_missing_field_flow must NOT be invoked for the client_id-only case.
    mock_start_missing.assert_not_called()

    # reply_text was called with picker text + a keyboard whose first button
    # carries a pick_client:* callback.
    call = update.message.reply_text.await_args
    text = call[0][0]
    assert "Who is this invoice for?" in text
    reply_markup = call.kwargs.get("reply_markup")
    assert reply_markup is not None
    first_button = reply_markup.inline_keyboard[0][0]
    assert first_button.callback_data.startswith("pick_client:")


# ---------------------------------------------------------------------------
# Callback handler
# ---------------------------------------------------------------------------


async def test_callback_pick_client_full_data_shows_confirmation():
    """Picking a contact whose defaults fill every remaining field jumps
    straight to the confirmation card (no missing-field flow)."""
    _sessions.clear()
    s = Session()
    s.state = PENDING
    s.parsed_data = _full_parsed_data(client_id=None)
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("pick_client:client_a")
    ctx = _make_context()
    contact = _client_a_contact()

    fake_computed = {
        "client_id": "client_a",
        "display_name": "Client A Ltd.",
        "address": "HK",
        "email": "billing@client-a.com",
        "description": "Invoice for Client A booking",
        "service_description": "Service for Client A",
        "rate": Decimal("500"),
        "total": Decimal("1000"),
    }

    with (
        patch("bot.handlers.get_contact", new=AsyncMock(return_value=contact)),
        patch("bot.handlers.merge_and_compute", return_value=fake_computed),
        patch(
            "bot.handlers.format_confirmation",
            return_value="CONFIRMATION-TEXT",
        ),
        patch(
            "bot.handlers._start_missing_field_flow", new=AsyncMock()
        ) as mock_start_missing,
    ):
        await handle_callback(update, ctx)

    # Confirmation card shown.
    final_call = query.message.reply_text.await_args
    assert final_call[0][0] == "CONFIRMATION-TEXT"
    assert final_call.kwargs.get("reply_markup") is not None
    # session.computed_data populated.
    assert _sessions[_CHAT_ID].computed_data == fake_computed
    # No missing-field flow taken.
    mock_start_missing.assert_not_called()
    # query.answer acked.
    query.answer.assert_awaited_once()


async def test_callback_pick_client_missing_other_fields_routes_to_fill_missing():
    """Picking a contact with no defaults, when the LLM didn't supply rate
    either, hands off to the sequential missing-field flow."""
    _sessions.clear()
    s = Session()
    s.state = PENDING
    # description and rate are null; contact_b has no defaults → both still missing.
    s.parsed_data = {
        "client_id": None,
        "description": None,
        "line_items": [
            {
                "service_date": "26/03/2026",
                "service_description": None,
                "time_start": "22:00",
                "time_end": "00:00",
                "rate": None,
                "rate_type": "hourly",
                "total": None,
            }
        ],
        "missing_fields": ["client_id"],
    }
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("pick_client:client_b")
    ctx = _make_context()
    contact = _client_b_contact()  # no defaults

    with (
        patch("bot.handlers.get_contact", new=AsyncMock(return_value=contact)),
        patch(
            "bot.handlers._start_missing_field_flow", new=AsyncMock()
        ) as mock_start_missing,
    ):
        await handle_callback(update, ctx)

    mock_start_missing.assert_awaited_once()
    # Signature: (query.message, context, session, chat_id, fields)
    args, _kwargs = mock_start_missing.await_args
    fields = args[4]
    # client_id is now filled; the still-missing ones are description, service_description, rate.
    assert "description" in fields
    assert "service_description" in fields
    assert "rate" in fields
    assert "client_id" not in fields
    # parsed_data has the picked client_id patched in.
    assert _sessions[_CHAT_ID].parsed_data["client_id"] == "client_b"


async def test_callback_pick_client_none_clears_session():
    """Tapping 'None of these' clears the session and tells the user to retry."""
    _sessions.clear()
    s = Session()
    s.state = PENDING
    s.parsed_data = _full_parsed_data(client_id=None)
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("pick_client:__none__")
    ctx = _make_context()

    await handle_callback(update, ctx)

    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args[0][0]
    assert "No client selected" in text
    assert _CHAT_ID not in _sessions


async def test_callback_pick_client_unknown_contact_clears_session():
    """If the picked client_id no longer exists in the DB, the bot tells the
    user to start over and clears the session."""
    _sessions.clear()
    s = Session()
    s.state = PENDING
    s.parsed_data = _full_parsed_data(client_id=None)
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("pick_client:client_a")
    ctx = _make_context()

    with patch("bot.handlers.get_contact", new=AsyncMock(return_value=None)):
        await handle_callback(update, ctx)

    query.edit_message_text.assert_awaited_once()
    text = query.edit_message_text.await_args[0][0]
    assert "no longer exists" in text
    assert _CHAT_ID not in _sessions


async def test_callback_pick_client_no_session_returns_silently():
    """Stale callback (no session in _sessions) is acknowledged but does
    nothing further — no edit, no reply, no contact lookup."""
    _sessions.clear()

    update, query = _make_callback("pick_client:client_a")
    ctx = _make_context()

    with patch(
        "bot.handlers.get_contact", new=AsyncMock(return_value=_client_a_contact())
    ) as mock_get:
        await handle_callback(update, ctx)

    query.answer.assert_awaited_once()
    query.edit_message_text.assert_not_awaited()
    query.message.reply_text.assert_not_awaited()
    mock_get.assert_not_awaited()
