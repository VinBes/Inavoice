"""Tests 4.1–4.3: email delivery — Resend mock, keyboard visibility, failure handling."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot import handlers
from bot.handlers import _sessions, handle_callback
from bot.keyboards import confirm_keyboard
from models.session import COMPLETE, PENDING, Session

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


def _pending_session():
    s = Session()
    s.state = PENDING
    s.computed_data = _COMPUTED_WITH_EMAIL.copy()
    return s


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
# Test 4.2 — Confirm keyboard shape based on email availability
# ---------------------------------------------------------------------------

def test_4_2_no_email_keyboard_single_confirm():
    kb = confirm_keyboard(has_email=False)
    rows = kb.inline_keyboard
    assert len(rows) == 1
    datas = {b.callback_data for b in rows[0]}
    assert datas == {"confirm", "edit", "cancel"}


def test_4_2_with_email_keyboard_has_split_confirm():
    kb = confirm_keyboard(has_email=True)
    rows = kb.inline_keyboard
    assert len(rows) == 2
    row1 = {b.callback_data for b in rows[0]}
    row2 = {b.callback_data for b in rows[1]}
    assert row1 == {"confirm_email", "confirm_telegram"}
    assert row2 == {"edit", "cancel"}
    # The deprecated "deliver_*" / "Both" callbacks must be gone
    all_datas = row1 | row2
    assert "deliver_email" not in all_datas
    assert "deliver_both" not in all_datas


# ---------------------------------------------------------------------------
# Test 4.3 — Email failure during Confirm + Email: PDF still delivered via Telegram
# ---------------------------------------------------------------------------

async def test_4_3_email_failure_still_sends_pdf():
    _sessions.clear()
    _sessions[_CHAT_ID] = _pending_session()

    update, query = _make_callback("confirm_email")
    ctx = MagicMock()
    ctx.user_data = {}

    with (
        patch("bot.handlers.create_invoice", return_value=("ZARAFFA26-1", b"%PDF")),
        patch(
            "bot.handlers.send_invoice_email",
            side_effect=Exception("Resend API error"),
        ),
    ):
        await handle_callback(update, ctx)

    # PDF was still sent via Telegram
    query.message.reply_document.assert_awaited_once()
    # Status message mentions email failure
    last_edit = query.edit_message_text.await_args_list[-1].args[0]
    assert "Email failed" in last_edit
    # Session was cleared (collapsed flow always ends at delivery)
    assert _CHAT_ID not in _sessions


# ---------------------------------------------------------------------------
# email_id capture: send_invoice_email returns the Resend message id, and the
# confirm pipeline persists it via update_email_id so webhooks can find the
# invoice later.
# ---------------------------------------------------------------------------


async def test_send_invoice_email_returns_id_in_prod_mode(monkeypatch):
    from services import email_sender

    monkeypatch.setattr(config, "MOCK_MODE", False)

    fake_resp = {"id": "abc123"}
    with patch.object(
        email_sender.resend.Emails, "send", return_value=fake_resp
    ) as mock_send:
        result = await email_sender.send_invoice_email(
            "to@example.com",
            "ZARAFFA26-1",
            b"%PDF",
            "Alice",
            "Client A Ltd.",
            "9 April 2026",
        )

    assert result == "abc123"
    mock_send.assert_called_once()


async def test_send_invoice_email_returns_none_in_mock_mode():
    from services.email_sender import send_invoice_email

    # MOCK_MODE is True in conftest.
    result = await send_invoice_email(
        "to@example.com",
        "ZARAFFA26-1",
        b"%PDF",
        None,
        "Client A Ltd.",
        "9 April 2026",
    )
    assert result is None


async def test_execute_confirm_persists_email_id():
    """The confirm pipeline must call update_email_id with the id returned by
    send_invoice_email, so a later Resend webhook can match the row."""
    _sessions.clear()
    _sessions[_CHAT_ID] = _pending_session()

    update, query = _make_callback("confirm_email")
    ctx = MagicMock()
    ctx.user_data = {}
    # job_queue.get_jobs_by_name() is iterated for cleanup; an empty list is fine.
    ctx.job_queue.get_jobs_by_name.return_value = []

    with (
        patch("bot.handlers.create_invoice", return_value=("ZARAFFA26-1", b"%PDF")),
        patch(
            "bot.handlers.send_invoice_email",
            AsyncMock(return_value="abc123"),
        ),
        patch("bot.handlers.update_email_id", AsyncMock()) as mock_update,
    ):
        await handle_callback(update, ctx)

    mock_update.assert_awaited_once_with("ZARAFFA26-1", "abc123")
    assert _CHAT_ID not in _sessions
