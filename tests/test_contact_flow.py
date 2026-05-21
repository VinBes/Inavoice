"""Tests for the guided /contacts add flow."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot import handlers
from bot.handlers import _sessions, contacts_command, handle_callback, handle_message
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
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


def _add_contact_session(step: int, draft_extras: dict | None = None) -> Session:
    s = Session(mode="add_contact")
    draft = {"_step": step}
    if draft_extras:
        draft.update(draft_extras)
    s.contact_draft = draft
    return s


# ---------------------------------------------------------------------------
# /contacts add command entry
# ---------------------------------------------------------------------------

async def test_ca_1_start_command_initialises_add_contact_session():
    _sessions.clear()
    update = _make_message_update("/contacts add")
    ctx = _make_context(args=["add"])
    await contacts_command(update, ctx)

    assert _sessions[_CHAT_ID].mode == "add_contact"
    assert _sessions[_CHAT_ID].contact_draft == {"_step": 0}
    text = update.message.reply_text.await_args[0][0]
    assert "client ID" in text


async def test_ca_no_args_lists_contacts_unchanged():
    """Regression: /contacts with no args still lists contacts (uses Contact attrs)."""
    _sessions.clear()
    update = _make_message_update("/contacts")
    ctx = _make_context(args=[])
    fake_contact = Contact(
        client_id="client_a", display_name="Client A Ltd.", address="HK"
    )
    with patch("bot.handlers.list_contacts", return_value=[fake_contact]):
        await contacts_command(update, ctx)

    text = update.message.reply_text.await_args[0][0]
    assert "client_a" in text
    assert "Client A Ltd." in text


# ---------------------------------------------------------------------------
# Step validation
# ---------------------------------------------------------------------------

async def test_ca_2_required_field_empty_rejected():
    _sessions.clear()
    _sessions[_CHAT_ID] = _add_contact_session(step=0)
    update = _make_message_update("   ")
    ctx = _make_context()
    await handle_message(update, ctx)

    assert _sessions[_CHAT_ID].contact_draft["_step"] == 0
    assert "required" in update.message.reply_text.await_args[0][0].lower()


async def test_ca_3_invalid_client_id_rejected():
    _sessions.clear()
    _sessions[_CHAT_ID] = _add_contact_session(step=0)
    update = _make_message_update("My Client")
    ctx = _make_context()
    await handle_message(update, ctx)

    assert _sessions[_CHAT_ID].contact_draft["_step"] == 0
    assert "lowercase" in update.message.reply_text.await_args[0][0].lower()


async def test_ca_4_valid_client_id_advances_step():
    _sessions.clear()
    _sessions[_CHAT_ID] = _add_contact_session(step=0)
    update = _make_message_update("new_client")
    ctx = _make_context()
    await handle_message(update, ctx)

    assert _sessions[_CHAT_ID].contact_draft["_step"] == 1
    assert _sessions[_CHAT_ID].contact_draft["client_id"] == "new_client"


async def test_ca_5_skip_optional_field():
    _sessions.clear()
    # step 3 = contact_person (optional)
    _sessions[_CHAT_ID] = _add_contact_session(
        step=3,
        draft_extras={
            "client_id": "x",
            "display_name": "X Ltd.",
            "address": "HK",
        },
    )
    update = _make_message_update("skip")
    ctx = _make_context()
    await handle_message(update, ctx)

    assert _sessions[_CHAT_ID].contact_draft["_step"] == 4
    assert _sessions[_CHAT_ID].contact_draft["contact_person"] is None


async def test_ca_6_invalid_default_rate_rejected():
    _sessions.clear()
    # step 9 = default_rate (after client_id, display_name, address, contact_person,
    # email, phone, telegram_handle, default_description, default_service_description)
    _sessions[_CHAT_ID] = _add_contact_session(step=9)
    update = _make_message_update("-50")
    ctx = _make_context()
    await handle_message(update, ctx)

    assert _sessions[_CHAT_ID].contact_draft["_step"] == 9
    assert "positive" in update.message.reply_text.await_args[0][0].lower()


async def test_ca_invalid_email_rejected():
    _sessions.clear()
    # step 4 = email
    _sessions[_CHAT_ID] = _add_contact_session(step=4)
    update = _make_message_update("not-an-email")
    ctx = _make_context()
    await handle_message(update, ctx)

    assert _sessions[_CHAT_ID].contact_draft["_step"] == 4


# ---------------------------------------------------------------------------
# Happy path → summary
# ---------------------------------------------------------------------------

async def test_ca_7_full_happy_path_reaches_summary():
    _sessions.clear()
    _sessions[_CHAT_ID] = _add_contact_session(step=0)
    inputs = [
        "new_client",                # client_id
        "New Client Ltd.",           # display_name
        "HK address",                # address
        "skip",                      # contact_person
        "billing@new-client.com",    # email
        "skip",                      # phone
        "skip",                      # telegram_handle
        "skip",                      # default_description
        "skip",                      # default_service_description
        "500",                       # default_rate
        "NC, New Client",            # aliases
    ]
    for text in inputs:
        update = _make_message_update(text)
        ctx = _make_context()
        await handle_message(update, ctx)

    # All 11 steps consumed; final reply should include summary + keyboard
    final_call = update.message.reply_text.await_args
    assert "Contact Preview" in final_call[0][0]
    assert final_call.kwargs.get("reply_markup") is not None
    # Aliases line is rendered in the summary
    assert "Aliases:" in final_call[0][0]
    assert "NC" in final_call[0][0]


async def test_ca_aliases_step_accepts_comma_string():
    """Aliases is the last step (index 10); a comma-separated string is stored verbatim."""
    _sessions.clear()
    _sessions[_CHAT_ID] = _add_contact_session(
        step=10,
        draft_extras={
            "client_id": "aesthetic_radio",
            "display_name": "Aesthetic Radio HK",
            "address": "HK",
            "contact_person": None,
            "email": None,
            "phone": None,
            "telegram_handle": None,
            "default_description": None,
            "default_service_description": None,
            "default_rate": None,
        },
    )
    update = _make_message_update("AER, aesthetic")
    ctx = _make_context()
    await handle_message(update, ctx)

    # Step advances past the last index; draft holds the raw string.
    assert _sessions[_CHAT_ID].contact_draft["_step"] == 11
    assert _sessions[_CHAT_ID].contact_draft["aliases"] == "AER, aesthetic"
    # Summary message includes the aliases line.
    final_call = update.message.reply_text.await_args
    assert "AER" in final_call[0][0]


async def test_ca_aliases_step_skip_clears():
    """Aliases is optional; `skip` should store None (Contact coerces to [])."""
    _sessions.clear()
    _sessions[_CHAT_ID] = _add_contact_session(
        step=10,
        draft_extras={
            "client_id": "aesthetic_radio",
            "display_name": "Aesthetic Radio HK",
            "address": "HK",
            "contact_person": None,
            "email": None,
            "phone": None,
            "telegram_handle": None,
            "default_description": None,
            "default_service_description": None,
            "default_rate": None,
        },
    )
    update = _make_message_update("skip")
    ctx = _make_context()
    await handle_message(update, ctx)

    assert _sessions[_CHAT_ID].contact_draft["_step"] == 11
    assert _sessions[_CHAT_ID].contact_draft["aliases"] is None


# ---------------------------------------------------------------------------
# Confirm / Cancel callbacks
# ---------------------------------------------------------------------------

async def test_ca_8_confirm_saves_contact():
    _sessions.clear()
    s = _add_contact_session(
        step=9,
        draft_extras={
            "client_id": "new_client",
            "display_name": "New Client",
            "address": "HK",
            "contact_person": None,
            "email": None,
            "default_description": None,
            "default_service_description": None,
            "default_rate": Decimal("500"),
            "aliases": None,
        },
    )
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("contact_confirm")
    ctx = _make_context()
    with patch("bot.contact_flow.upsert_contact", new=AsyncMock()) as mock_upsert:
        await handle_callback(update, ctx)

    mock_upsert.assert_awaited_once()
    saved_arg = mock_upsert.await_args.args[0]
    assert isinstance(saved_arg, Contact)
    assert saved_arg.client_id == "new_client"
    assert _CHAT_ID not in _sessions


async def test_ca_9_cancel_clears_session():
    _sessions.clear()
    _sessions[_CHAT_ID] = _add_contact_session(step=9)
    update, query = _make_callback("contact_cancel")
    ctx = _make_context()
    await handle_callback(update, ctx)

    assert _CHAT_ID not in _sessions
    msg = query.edit_message_text.await_args[0][0]
    assert "cancelled" in msg.lower()


async def test_ca_12_contact_confirm_validates_before_upsert():
    """Final guard: if the draft somehow has invalid data, upsert must not run."""
    _sessions.clear()
    s = _add_contact_session(
        step=9,
        draft_extras={
            # Bypass step validation by setting an invalid client_id directly
            "client_id": "BAD ID",
            "display_name": "X",
            "address": "HK",
        },
    )
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("contact_confirm")
    ctx = _make_context()
    with patch("bot.contact_flow.upsert_contact", new=AsyncMock()) as mock_upsert:
        await handle_callback(update, ctx)

    mock_upsert.assert_not_awaited()
    assert _CHAT_ID not in _sessions
    msg = query.edit_message_text.await_args[0][0]
    assert "validation" in msg.lower() or "failed" in msg.lower()


# ---------------------------------------------------------------------------
# Conflict handling
# ---------------------------------------------------------------------------

async def test_ca_10_conflict_invoice_pending_replaced():
    _sessions.clear()
    pending = Session()
    pending.state = PENDING
    pending.parsed_data = {"some": "thing"}
    _sessions[_CHAT_ID] = pending

    update = _make_message_update("/contacts add")
    ctx = _make_context(args=["add"])
    await contacts_command(update, ctx)

    assert _sessions[_CHAT_ID].mode == "add_contact"
    assert _sessions[_CHAT_ID].contact_draft == {"_step": 0}
    # First reply should warn about the cancelled draft
    first_reply = update.message.reply_text.await_args_list[0][0][0]
    assert "cancelled" in first_reply.lower()


async def test_ca_11_conflict_invoice_generating_blocked():
    _sessions.clear()
    generating = Session()
    generating.state = GENERATING
    _sessions[_CHAT_ID] = generating

    update = _make_message_update("/contacts add")
    ctx = _make_context(args=["add"])
    await contacts_command(update, ctx)

    # Existing GENERATING session is preserved
    assert _sessions[_CHAT_ID] is generating
    msg = update.message.reply_text.await_args[0][0]
    assert "being generated" in msg.lower() or "wait" in msg.lower()
