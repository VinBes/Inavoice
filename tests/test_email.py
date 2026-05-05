"""Tests 4.1–4.3: email delivery — Resend mock, keyboard visibility, failure handling."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot import handlers
from bot.handlers import _sessions, handle_callback
from bot.keyboards import delivery_keyboard
from models.session import COMPLETE, Session

_CHAT_ID = int(config.ALLOWED_CHAT_IDS[0])

_COMPUTED_WITH_EMAIL = {
    "client_id": "client_a",
    "display_name": "Client A Ltd.",
    "contact_person": None,
    "email": "accounts@client-a.example.com",
    "total": __import__("decimal").Decimal("1000"),
    "due_date": __import__("datetime").date(2026, 4, 9),
}


def _make_callback(data, chat_id=_CHAT_ID):
    query = MagicMock()
    query.data = data
    query.message.chat_id = chat_id
    query.from_user.id = chat_id  # auth checks from_user.id
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.reply_text = AsyncMock()
    query.message.reply_document = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    return update, query


# ---------------------------------------------------------------------------
# Test 4.1 — MOCK_MODE: send_invoice_email logs to stdout, no Resend call
# ---------------------------------------------------------------------------

async def test_4_1_mock_mode_logs_stdout(capsys):
    from services.email_sender import send_invoice_email
    await send_invoice_email(
        "test@client-a.example.com",
        "ZARAFFA26-1",
        b"%PDF",
        None,
        "Client A Ltd.",
        "9 April 2026",
    )
    captured = capsys.readouterr()
    assert "[MOCK EMAIL]" in captured.out
    assert "ZARAFFA26-1" in captured.out
    # Email address must NOT appear in stdout (PII rule)
    assert "test@client-a.example.com" not in captured.out


# ---------------------------------------------------------------------------
# Test 4.2 — Delivery keyboard shape based on email availability
# ---------------------------------------------------------------------------

def test_4_2_no_email_keyboard_telegram_only():
    kb = delivery_keyboard(has_email=False)
    buttons = kb.inline_keyboard[0]
    assert len(buttons) == 1
    assert buttons[0].callback_data == "deliver_telegram"


def test_4_2_with_email_keyboard_has_three_options():
    kb = delivery_keyboard(has_email=True)
    buttons = kb.inline_keyboard[0]
    assert len(buttons) == 3
    datas = {b.callback_data for b in buttons}
    assert datas == {"deliver_email", "deliver_telegram", "deliver_both"}


# ---------------------------------------------------------------------------
# Test 4.3 — Email failure: PDF still delivered via Telegram
# ---------------------------------------------------------------------------

async def test_4_3_email_failure_still_sends_pdf():
    _sessions.clear()
    s = Session()
    s.state = COMPLETE
    s.computed_data = _COMPUTED_WITH_EMAIL.copy()
    _sessions[_CHAT_ID] = s

    update, query = _make_callback("deliver_email")
    ctx = MagicMock()
    ctx.user_data = {"pdf_bytes": b"%PDF", "invoice_number": "ZARAFFA26-1"}

    with patch(
        "bot.handlers.send_invoice_email",
        side_effect=Exception("Resend API error"),
    ):
        await handle_callback(update, ctx)

    # PDF was still sent via Telegram
    query.message.reply_document.assert_awaited_once()
    # Error message was shown
    error_text = query.message.reply_text.call_args[0][0]
    assert "email failed" in error_text.lower()
