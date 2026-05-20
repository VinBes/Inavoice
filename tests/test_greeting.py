"""Tests for greeting detection and welcome-message refactor (PB3-4)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot import handlers
from bot.handlers import (
    _build_start_message,
    _is_greeting,
    _sessions,
    handle_message,
)
from models.schemas import Contact
from models.session import PENDING, Session

_CHAT_ID = int(config.ALLOWED_CHAT_IDS[0])


# ---------------------------------------------------------------------------
# Helpers (mirrors patterns from tests/test_contact_flow.py)
# ---------------------------------------------------------------------------


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


@pytest.fixture(autouse=True)
def _clear_sessions():
    """Module-level _sessions dict must be clean between tests."""
    _sessions.clear()
    yield
    _sessions.clear()


# ---------------------------------------------------------------------------
# _is_greeting unit tests
# ---------------------------------------------------------------------------


def test_is_greeting_hi():
    assert _is_greeting("hi") is True


def test_is_greeting_hello_punctuation():
    assert _is_greeting("Hello!") is True


def test_is_greeting_uppercase():
    assert _is_greeting("HEY") is True


def test_is_greeting_with_question_mark():
    assert _is_greeting("hi?") is True


def test_is_greeting_invoice_text_not_greeting():
    assert _is_greeting("Invoice for aesthetic_radio") is False


def test_is_greeting_partial_not_greeting():
    assert _is_greeting("hi please invoice for aer") is False


def test_is_greeting_good_morning():
    assert _is_greeting("good morning") is True


def test_is_greeting_good_day():
    assert _is_greeting("good day") is True
    assert _is_greeting("Good Day!") is True


def test_is_greeting_empty():
    assert _is_greeting("") is False


# ---------------------------------------------------------------------------
# _build_start_message unit tests
# ---------------------------------------------------------------------------


async def test_build_start_message_no_contacts():
    msg = await _build_start_message([])
    assert f"env: {config.DEPLOY_ENV}" in msg
    assert "Invoice for {client}" in msg
    assert "Known clients:" not in msg
    assert "/help" in msg


async def test_build_start_message_with_contacts():
    contacts = [
        Contact(client_id="client_a", display_name="Client A Ltd.", address="HK"),
        Contact(client_id="aesthetic_radio", display_name="Aesthetic Radio", address="HK"),
    ]
    msg = await _build_start_message(contacts)
    assert "Known clients:" in msg
    assert "client_a → Client A Ltd." in msg
    assert "aesthetic_radio → Aesthetic Radio" in msg


# ---------------------------------------------------------------------------
# handle_message greeting short-circuit
# ---------------------------------------------------------------------------


async def test_handle_message_greeting_no_session_short_circuits():
    """A bare 'hi' with no active session must NOT call parse_invoice_text."""
    update = _make_message_update("hi")
    ctx = _make_context()

    fake_contact = Contact(
        client_id="client_a", display_name="Client A Ltd.", address="HK"
    )

    with patch(
        "bot.handlers.list_contacts", new=AsyncMock(return_value=[fake_contact])
    ), patch("bot.handlers.parse_invoice_text", new=AsyncMock()) as mock_parse:
        await handle_message(update, ctx)

    mock_parse.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.await_args[0][0]
    assert "Known clients:" in reply
    assert "client_a → Client A Ltd." in reply
    # Session must NOT be created for a bare greeting
    assert _CHAT_ID not in _sessions


async def test_handle_message_greeting_with_pending_session_does_not_short_circuit():
    """When a session is active (PENDING), 'hi' is treated as a normal message and parsed."""
    pending = Session(state=PENDING)
    _sessions[_CHAT_ID] = pending

    update = _make_message_update("hi")
    ctx = _make_context()

    parsed_result = MagicMock()
    parsed_result.client_id = None
    parsed_result.line_items = []
    parsed_result.description = None
    parsed_result.missing_fields = []
    parsed_result.model_dump = MagicMock(return_value={})

    with patch(
        "bot.handlers.list_contacts", new=AsyncMock(return_value=[])
    ), patch(
        "bot.handlers.parse_invoice_text", new=AsyncMock(return_value=parsed_result)
    ) as mock_parse:
        await handle_message(update, ctx)

    mock_parse.assert_awaited_once()
