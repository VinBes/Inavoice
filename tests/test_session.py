"""Tests 3.1–3.7: session state machine via mocked Telegram objects."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot import handlers
from bot.handlers import _sessions, _timeout_callback, handle_callback, handle_message
from models.session import CANCELLED, COMPLETE, GENERATING, PENDING, Session
from models.schemas import Contact, LLMLineItem, LLMOutput
from services.llm_parser import SessionCapExceededError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CHAT_ID = int(config.ALLOWED_CHAT_IDS[0])

# Flat computed dict (what merge_and_compute returns → stored in session.computed_data)
_COMPUTED_DATA = {
    "client_id": "client_a",
    "display_name": "Client A Ltd.",
    "contact_person": None,
    "address": "Test Address",
    "email": "test@client-a.example.com",
    "description": "Invoice for Client A booking",
    "service_date": "26/03/2026",
    "service_description": "Service for Client A",
    "time_start": "22:00",
    "time_end": "00:00",
    "hours": Decimal("2"),
    "rate": Decimal("500"),
    "rate_type": "hourly",
    "total": Decimal("1000"),
    "invoice_date": __import__("datetime").date(2026, 3, 26),
    "due_date": __import__("datetime").date(2026, 4, 9),
}

# LLMOutput-shaped dict (what result.model_dump() returns → stored in session.parsed_data)
_LLM_DATA = {
    "client_id": "client_a",
    "description": "Invoice for Client A booking",
    "line_items": [{
        "service_date": "26/03/2026",
        "service_description": "Service for Client A",
        "time_start": "22:00",
        "time_end": "00:00",
        "rate": 500,
        "rate_type": "hourly",
        "total": None,
    }],
    "missing_fields": [],
}


def _make_message_update(text="invoice for client a"):
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


def _make_callback(data):
    query = MagicMock()
    query.data = data
    query.message.chat_id = _CHAT_ID
    query.from_user.id = _CHAT_ID  # auth checks this, not message.chat_id
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.reply_text = AsyncMock()
    query.message.reply_document = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


def _pending_session_with_data():
    s = Session()
    s.state = PENDING
    s.parsed_data = _LLM_DATA.copy()
    s.computed_data = _COMPUTED_DATA.copy()
    return s


# ---------------------------------------------------------------------------
# Test 3.1 — Happy path: PENDING → Confirm → COMPLETE
# ---------------------------------------------------------------------------

async def test_3_1_confirm_telegram_happy_path():
    """Confirm + Telegram (has_email path): full pipeline runs in one callback,
    PDF delivered via Telegram, session cleared."""
    _sessions.clear()
    _sessions[_CHAT_ID] = _pending_session_with_data()

    update, query = _make_callback("confirm_telegram")
    ctx = _make_context()

    with patch("bot.handlers.create_invoice", return_value=("ZARAFFA26-1", b"%PDF")):
        await handle_callback(update, ctx)

    # Session is cleared after delivery in the collapsed flow
    assert _CHAT_ID not in _sessions
    # PDF was delivered via Telegram
    query.message.reply_document.assert_awaited_once()
    kwargs = query.message.reply_document.await_args.kwargs
    assert kwargs["document"] == b"%PDF"
    assert kwargs["filename"] == "Invoice_ZARAFFA26-1.pdf"


async def test_3_1b_confirm_email_happy_path():
    """Confirm + Email: email_sender called AND PDF still sent via Telegram."""
    _sessions.clear()
    _sessions[_CHAT_ID] = _pending_session_with_data()

    update, query = _make_callback("confirm_email")
    ctx = _make_context()

    with (
        patch("bot.handlers.create_invoice", return_value=("ZARAFFA26-1", b"%PDF")),
        patch("bot.handlers.send_invoice_email") as mock_send,
    ):
        await handle_callback(update, ctx)

    mock_send.assert_awaited_once()
    query.message.reply_document.assert_awaited_once()
    assert _CHAT_ID not in _sessions


async def test_3_1d_confirm_cancels_pending_timeout_job():
    """Regression: _execute_confirm must cancel the timeout job that
    handle_message scheduled. Without this, the user sees a spurious
    'session expired' message ~30 minutes after a successful invoice."""
    _sessions.clear()
    _sessions[_CHAT_ID] = _pending_session_with_data()

    update, query = _make_callback("confirm_telegram")
    ctx = _make_context()
    fake_job = MagicMock()
    ctx.job_queue.get_jobs_by_name = MagicMock(return_value=[fake_job])

    with patch("bot.handlers.create_invoice", return_value=("ZARAFFA26-1", b"%PDF")):
        await handle_callback(update, ctx)

    fake_job.schedule_removal.assert_called_once()


async def test_3_1c_confirm_no_email_uses_plain_confirm():
    """Contact with no email: keyboard shows single 'Confirm' button (cb='confirm').
    Behaves exactly like confirm_telegram — no email branch."""
    _sessions.clear()
    s = _pending_session_with_data()
    s.computed_data["email"] = None  # no-email path
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("confirm")
    ctx = _make_context()

    with (
        patch("bot.handlers.create_invoice", return_value=("ZARAFFA26-1", b"%PDF")),
        patch("bot.handlers.send_invoice_email") as mock_send,
    ):
        await handle_callback(update, ctx)

    mock_send.assert_not_awaited()
    query.message.reply_document.assert_awaited_once()
    assert _CHAT_ID not in _sessions


# ---------------------------------------------------------------------------
# Test 3.2 — Edit loop: PENDING → Edit → still PENDING → Confirm → COMPLETE
# ---------------------------------------------------------------------------

async def test_3_2_edit_loop():
    _sessions.clear()
    _sessions[_CHAT_ID] = _pending_session_with_data()

    # Tap Edit
    update, query = _make_callback("edit")
    ctx = _make_context()
    await handle_callback(update, ctx)

    assert _sessions[_CHAT_ID].state == PENDING
    query.edit_message_text.assert_awaited_once()

    # Send correction → parse → re-confirm
    _llm_result = LLMOutput(
        client_id="client_a",
        description="Updated description",
        line_items=[LLMLineItem(
            service_date="26/03/2026", service_description="Service for Client A",
            time_start="22:00", time_end="00:00", rate=500, rate_type="hourly", total=None,
        )],
        missing_fields=[],
    )
    _contact = Contact(
        client_id="client_a", display_name="Client A Ltd.", contact_person=None,
        address="Test Address", email="test@client-a.example.com",
        default_description="Invoice for Client A booking",
        default_service_description="Service for Client A", default_rate=Decimal("500"),
    )
    msg_update = _make_message_update("change description to Updated description")
    ctx2 = _make_context()
    with (
        patch("bot.handlers.parse_invoice_text", return_value=_llm_result),
        patch("bot.handlers.get_contact", return_value=_contact),
        patch("bot.handlers.list_contacts", return_value=[_contact]),
    ):
        await handle_message(msg_update, ctx2)

    assert _sessions[_CHAT_ID].state == PENDING
    assert _sessions[_CHAT_ID].computed_data is not None

    # Confirm (Telegram path since this contact has email)
    update2, query2 = _make_callback("confirm_telegram")
    ctx3 = _make_context()
    with patch("bot.handlers.create_invoice", return_value=("ZARAFFA26-2", b"%PDF")):
        await handle_callback(update2, ctx3)

    # Session is cleared after delivery in the collapsed flow
    assert _CHAT_ID not in _sessions


# ---------------------------------------------------------------------------
# Test 3.3 — Cancel from PENDING
# ---------------------------------------------------------------------------

async def test_3_3_cancel_from_pending():
    _sessions.clear()
    _sessions[_CHAT_ID] = _pending_session_with_data()

    update, query = _make_callback("cancel")
    ctx = _make_context()
    await handle_callback(update, ctx)

    assert _CHAT_ID not in _sessions
    query.edit_message_text.assert_awaited_once_with("Invoice cancelled.")


# ---------------------------------------------------------------------------
# Test 3.4 — Cancel while GENERATING (already past PENDING)
# ---------------------------------------------------------------------------

async def test_3_4_cancel_while_generating():
    _sessions.clear()
    s = Session()
    s.state = GENERATING
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("cancel")
    ctx = _make_context()
    await handle_callback(update, ctx)

    assert _CHAT_ID not in _sessions


# ---------------------------------------------------------------------------
# Test 3.5 — Duplicate Confirm (state != PENDING)
# ---------------------------------------------------------------------------

async def test_3_5_duplicate_confirm():
    _sessions.clear()
    s = Session()
    s.state = GENERATING
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("confirm")
    ctx = _make_context()
    await handle_callback(update, ctx)

    query.answer.assert_awaited_once_with(
        "Already processing your invoice.", show_alert=True
    )
    query.edit_message_text.assert_not_awaited()


# ---------------------------------------------------------------------------
# Test 3.6 — Session timeout
# ---------------------------------------------------------------------------

async def test_3_6_session_timeout():
    _sessions.clear()
    _sessions[_CHAT_ID] = Session()

    ctx = MagicMock()
    ctx.job = MagicMock()
    ctx.job.chat_id = _CHAT_ID
    ctx.bot = MagicMock()
    ctx.bot.send_message = AsyncMock()

    await _timeout_callback(ctx)

    assert _CHAT_ID not in _sessions
    ctx.bot.send_message.assert_awaited_once_with(
        _CHAT_ID, "Your invoice session has expired. Please start over."
    )


# ---------------------------------------------------------------------------
# Test 3.7 — Max corrections (SessionCapExceededError)
# ---------------------------------------------------------------------------

async def test_3_7_max_corrections():
    _sessions.clear()
    s = Session()
    s.llm_call_count = config.SESSION_LLM_CALL_CAP
    s.parsed_data = _LLM_DATA.copy()
    s.computed_data = _COMPUTED_DATA.copy()
    _sessions[_CHAT_ID] = s

    update = _make_message_update("change rate to 600")
    ctx = _make_context()

    with patch(
        "bot.handlers.parse_invoice_text",
        side_effect=SessionCapExceededError("cap reached"),
    ):
        with patch("bot.handlers.list_contacts", return_value=[]):
            await handle_message(update, ctx)

    reply_text = update.message.reply_text.call_args[0][0]
    assert "Too many corrections" in reply_text
