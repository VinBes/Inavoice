"""Tests for the /invoices command."""
from unittest.mock import AsyncMock, MagicMock, patch

import config
from bot.handlers import invoices_command

_CHAT_ID = int(config.ALLOWED_CHAT_IDS[0])


def _make_command_update():
    update = MagicMock()
    update.effective_chat.id = _CHAT_ID
    update.message.reply_text = AsyncMock()
    return update


async def test_invoices_command_empty_state():
    update = _make_command_update()
    ctx = MagicMock()

    with patch("bot.handlers.list_recent_invoices", return_value=[]):
        await invoices_command(update, ctx)

    update.message.reply_text.assert_awaited_once_with("No invoices yet.")


async def test_invoices_command_renders_compact_lines():
    update = _make_command_update()
    ctx = MagicMock()

    rows = [
        {
            "invoice_number": "ZARAFFA26-3",
            "invoice_date": "2026-04-12",
            "client_id": "client_a",
            "subtotal": "1500",
        },
        {
            "invoice_number": "ZARAFFA26-2",
            "invoice_date": "2026-04-10",
            "client_id": "client_b",
            "subtotal": "2000",
        },
    ]
    with patch("bot.handlers.list_recent_invoices", return_value=rows):
        await invoices_command(update, ctx)

    msg = update.message.reply_text.await_args.args[0]
    assert "Recent invoices" in msg
    assert "ZARAFFA26-3 · 2026-04-12 · client_a · 1500 HKD" in msg
    assert "ZARAFFA26-2 · 2026-04-10 · client_b · 2000 HKD" in msg


async def test_invoices_command_handles_malformed_row():
    """Defensive: a row with a None subtotal must not crash /invoices.
    The schema declares subtotal NOT NULL, but we don't want a malformed row
    to take down the whole command — the row renders as '?' instead."""
    update = _make_command_update()
    ctx = MagicMock()
    rows = [{
        "invoice_number": "ZARAFFA26-3",
        "invoice_date": "2026-04-12",
        "client_id": "client_a",
        "subtotal": None,
    }]
    with patch("bot.handlers.list_recent_invoices", return_value=rows):
        await invoices_command(update, ctx)

    msg = update.message.reply_text.await_args.args[0]
    assert "ZARAFFA26-3" in msg
    assert "? HKD" in msg


async def test_invoices_command_unauthorized_silent():
    update = _make_command_update()
    update.effective_chat.id = 999_999_999  # not in ALLOWED_CHAT_IDS
    ctx = MagicMock()

    await invoices_command(update, ctx)

    update.message.reply_text.assert_not_awaited()
