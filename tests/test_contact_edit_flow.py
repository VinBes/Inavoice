"""Tests for the guided /contacts edit flow."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot import contact_flow
from bot.contact_flow import (
    _execute_contact_edit_done,
    _execute_contact_edit_field_pick,
    _start_contact_edit,
    handle_contact_edit_message,
)
from bot.handlers import _sessions
from bot.keyboards import contact_field_picker_keyboard
from models.schemas import Contact
from models.session import GENERATING, PENDING, Session

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


def _make_callback(data):
    query = MagicMock()
    query.data = data
    query.message.chat_id = _CHAT_ID
    query.from_user.id = _CHAT_ID
    query.message.reply_text = AsyncMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


def _sample_contact(**overrides) -> Contact:
    base = {
        "client_id": "aesthetic_radio",
        "display_name": "Aesthetic Radio HK",
        "address": "1 HK Way",
        "contact_person": "Alice",
        "email": "accounts@aesthetic.example",
        "default_description": "DJ services",
        "default_service_description": "Live mix",
        "default_rate": Decimal("500"),
    }
    base.update(overrides)
    return Contact(**base)


def _edit_session(**draft_extras) -> Session:
    s = Session(mode="edit_contact")
    draft = {"client_id": "aesthetic_radio"}
    draft.update(draft_extras)
    s.contact_draft = draft
    return s


# ---------------------------------------------------------------------------
# /contacts edit <client_id> command entry
# ---------------------------------------------------------------------------

async def test_edit_command_loads_contact_and_shows_picker():
    _sessions.clear()
    update = _make_message_update("/contacts edit aesthetic_radio")
    ctx = _make_context(args=["edit", "aesthetic_radio"])
    with patch(
        "bot.contact_flow.get_contact",
        new=AsyncMock(return_value=_sample_contact()),
    ):
        await _start_contact_edit(update, ctx, _CHAT_ID, "aesthetic_radio")

    assert _CHAT_ID in _sessions
    assert _sessions[_CHAT_ID].mode == "edit_contact"
    assert _sessions[_CHAT_ID].contact_draft["client_id"] == "aesthetic_radio"
    call = update.message.reply_text.await_args
    assert call.kwargs.get("reply_markup") is not None


async def test_edit_command_unknown_client_id():
    _sessions.clear()
    update = _make_message_update("/contacts edit nope")
    ctx = _make_context(args=["edit", "nope"])
    with patch("bot.contact_flow.get_contact", new=AsyncMock(return_value=None)):
        await _start_contact_edit(update, ctx, _CHAT_ID, "nope")

    assert _CHAT_ID not in _sessions
    text = update.message.reply_text.await_args[0][0]
    assert "No contact named nope" in text


async def test_edit_command_blocked_when_invoice_generating():
    _sessions.clear()
    generating = Session()
    generating.state = GENERATING
    _sessions[_CHAT_ID] = generating

    update = _make_message_update("/contacts edit aesthetic_radio")
    ctx = _make_context(args=["edit", "aesthetic_radio"])
    with patch(
        "bot.contact_flow.get_contact",
        new=AsyncMock(return_value=_sample_contact()),
    ):
        await _start_contact_edit(update, ctx, _CHAT_ID, "aesthetic_radio")

    # GENERATING session must be preserved
    assert _sessions[_CHAT_ID] is generating
    msg = update.message.reply_text.await_args[0][0]
    assert "being generated" in msg.lower() or "wait" in msg.lower()


async def test_edit_command_replaces_pending_invoice():
    _sessions.clear()
    pending = Session()
    pending.state = PENDING
    pending.parsed_data = {"some": "thing"}
    _sessions[_CHAT_ID] = pending

    update = _make_message_update("/contacts edit aesthetic_radio")
    ctx = _make_context(args=["edit", "aesthetic_radio"])
    with patch(
        "bot.contact_flow.get_contact",
        new=AsyncMock(return_value=_sample_contact()),
    ):
        await _start_contact_edit(update, ctx, _CHAT_ID, "aesthetic_radio")

    assert _sessions[_CHAT_ID].mode == "edit_contact"
    first_reply = update.message.reply_text.await_args_list[0][0][0]
    assert "cancelled" in first_reply.lower()


# ---------------------------------------------------------------------------
# Field picker callback
# ---------------------------------------------------------------------------

async def test_edit_field_button_prompts_with_current_value():
    _sessions.clear()
    _sessions[_CHAT_ID] = _edit_session()
    update, query = _make_callback("contact_edit_field:email")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.get_contact",
        new=AsyncMock(return_value=_sample_contact()),
    ):
        await _execute_contact_edit_field_pick(
            query, _sessions[_CHAT_ID], _CHAT_ID, ctx, "email"
        )

    assert _sessions[_CHAT_ID].contact_draft["_editing_field"] == "email"
    text = query.message.reply_text.await_args[0][0]
    assert "accounts@aesthetic.example" in text
    assert "new value" in text.lower()


# ---------------------------------------------------------------------------
# Field-edit message handling
# ---------------------------------------------------------------------------

async def test_edit_field_invalid_email_rejected():
    _sessions.clear()
    _sessions[_CHAT_ID] = _edit_session(_editing_field="email")

    update = _make_message_update("not-an-email")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.get_contact",
        new=AsyncMock(return_value=_sample_contact()),
    ), patch(
        "bot.contact_flow.upsert_contact", new=AsyncMock()
    ) as mock_upsert:
        await handle_contact_edit_message(
            update, ctx, _sessions[_CHAT_ID], _CHAT_ID
        )

    mock_upsert.assert_not_awaited()
    # Session preserved with _editing_field still set so the user can retry.
    assert _CHAT_ID in _sessions
    assert _sessions[_CHAT_ID].contact_draft["_editing_field"] == "email"
    msg = update.message.reply_text.await_args[0][0].lower()
    assert "email" in msg or "try again" in msg


async def test_edit_field_valid_email_persists_and_reshows_picker():
    _sessions.clear()
    _sessions[_CHAT_ID] = _edit_session(_editing_field="email")

    update = _make_message_update("new@example.com")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.get_contact",
        new=AsyncMock(return_value=_sample_contact()),
    ), patch(
        "bot.contact_flow.upsert_contact", new=AsyncMock()
    ) as mock_upsert:
        await handle_contact_edit_message(
            update, ctx, _sessions[_CHAT_ID], _CHAT_ID
        )

    mock_upsert.assert_awaited_once()
    saved = mock_upsert.await_args.args[0]
    assert isinstance(saved, Contact)
    assert saved.email == "new@example.com"

    # Final reply should show summary + picker keyboard
    final_call = update.message.reply_text.await_args
    assert "Contact Preview" in final_call[0][0]
    assert final_call.kwargs.get("reply_markup") is not None

    # _editing_field cleared after successful update
    assert "_editing_field" not in _sessions[_CHAT_ID].contact_draft


async def test_edit_field_skip_clears_optional_field():
    _sessions.clear()
    _sessions[_CHAT_ID] = _edit_session(_editing_field="email")

    update = _make_message_update("skip")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.get_contact",
        new=AsyncMock(return_value=_sample_contact()),
    ), patch(
        "bot.contact_flow.upsert_contact", new=AsyncMock()
    ) as mock_upsert:
        await handle_contact_edit_message(
            update, ctx, _sessions[_CHAT_ID], _CHAT_ID
        )

    mock_upsert.assert_awaited_once()
    saved = mock_upsert.await_args.args[0]
    assert saved.email is None


# ---------------------------------------------------------------------------
# Done callback
# ---------------------------------------------------------------------------

async def test_edit_done_clears_session():
    _sessions.clear()
    _sessions[_CHAT_ID] = _edit_session()
    update, query = _make_callback("contact_edit_done")
    ctx = _make_context()
    await _execute_contact_edit_done(query, _sessions[_CHAT_ID], _CHAT_ID, ctx)

    assert _CHAT_ID not in _sessions
    msg = query.edit_message_text.await_args[0][0]
    assert "saved" in msg.lower()


# ---------------------------------------------------------------------------
# Keyboard guarantees
# ---------------------------------------------------------------------------

def test_edit_field_picker_excludes_client_id():
    kb = contact_field_picker_keyboard()
    callback_data = []
    for row in kb.inline_keyboard:
        for btn in row:
            callback_data.append(btn.callback_data)
    assert "contact_edit_field:client_id" not in callback_data
    # And confirm the editable fields ARE present
    assert "contact_edit_field:display_name" in callback_data
    assert "contact_edit_field:email" in callback_data
    assert "contact_edit_field:aliases" in callback_data
    assert "contact_edit_done" in callback_data


async def test_edit_field_aliases_persists_comma_string():
    """Aliases edit accepts a comma-separated string; Contact coerces to list."""
    _sessions.clear()
    _sessions[_CHAT_ID] = _edit_session(_editing_field="aliases")

    update = _make_message_update("AER, aesthetic")
    ctx = _make_context()
    with patch(
        "bot.contact_flow.get_contact",
        new=AsyncMock(return_value=_sample_contact()),
    ), patch(
        "bot.contact_flow.upsert_contact", new=AsyncMock()
    ) as mock_upsert:
        await handle_contact_edit_message(
            update, ctx, _sessions[_CHAT_ID], _CHAT_ID
        )

    mock_upsert.assert_awaited_once()
    saved = mock_upsert.await_args.args[0]
    assert isinstance(saved, Contact)
    assert saved.aliases == ["AER", "aesthetic"]
