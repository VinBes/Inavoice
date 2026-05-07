"""Tests for the /resend command and the resend_invoice service function.

Covers:
- Service: telegram-only happy path, email happy path, invoice-not-found,
  contact-missing-email graceful degrade, email send failure.
- Handler: usage hint with no args, unknown second arg, too many args,
  invoice not found, full delivery on email path.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import config
from bot.handlers import resend_command
from services.invoice_service import (
    InvoiceNotFoundError,
    ResendResult,
    resend_invoice,
)

_CHAT_ID = int(config.ALLOWED_CHAT_IDS[0])

_INVOICE_ROW = {
    "invoice_number": "ZARAFFA26-3",
    "client_id": "client_a",
    "invoice_date": "2026-04-01",
    "due_date": "2026-04-15",
    "pdf_storage_path": "2026/ZARAFFA26-3.pdf",
}

_CONTACT_WITH_EMAIL = {
    "client_id": "client_a",
    "display_name": "Client A Ltd.",
    "contact_person": "Alice",
    "email": "accounts@client-a.example.com",
}

_CONTACT_NO_EMAIL = {
    "client_id": "client_a",
    "display_name": "Client A Ltd.",
    "contact_person": None,
    "email": None,
}


def _make_command_update(text="/resend"):
    update = MagicMock()
    update.effective_chat.id = _CHAT_ID
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.message.reply_document = AsyncMock()
    return update


def _make_command_context(args=None):
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


# ---------------------------------------------------------------------------
# Service: resend_invoice
# ---------------------------------------------------------------------------

async def test_resend_telegram_only_happy_path():
    with (
        patch("services.invoice_service.get_invoice", return_value=_INVOICE_ROW),
        patch("services.invoice_service.download_pdf", return_value=b"%PDF"),
        patch("services.invoice_service.send_invoice_email") as mock_send,
        patch("services.invoice_service.update_last_resent_at") as mock_update,
    ):
        result = await resend_invoice("ZARAFFA26-3", send_email=False)

    assert isinstance(result, ResendResult)
    assert result.pdf_bytes == b"%PDF"
    assert result.invoice_number == "ZARAFFA26-3"
    assert result.email_status == "not_requested"
    assert result.email_status_message is None
    mock_send.assert_not_awaited()
    mock_update.assert_not_awaited()  # only updated on successful re-email


async def test_resend_email_happy_path():
    with (
        patch("services.invoice_service.get_invoice", return_value=_INVOICE_ROW),
        patch("services.invoice_service.download_pdf", return_value=b"%PDF"),
        patch("services.invoice_service.get_contact", return_value=_CONTACT_WITH_EMAIL),
        patch("services.invoice_service.send_invoice_email") as mock_send,
        patch("services.invoice_service.update_last_resent_at") as mock_update,
    ):
        result = await resend_invoice("ZARAFFA26-3", send_email=True)

    assert result.email_status == "sent"
    assert result.email_status_message is None
    mock_send.assert_awaited_once()
    # last_resent_at must be updated only on successful re-email
    mock_update.assert_awaited_once_with("ZARAFFA26-3")


async def test_resend_invoice_not_found_raises():
    with patch("services.invoice_service.get_invoice", return_value=None):
        with pytest.raises(InvoiceNotFoundError):
            await resend_invoice("ZARAFFA99-99", send_email=False)


async def test_resend_email_requested_but_contact_has_no_email():
    """Q4 graceful degrade: still returns PDF bytes, email_status=skipped_no_email,
    user-facing message names the client_id, last_resent_at NOT updated."""
    with (
        patch("services.invoice_service.get_invoice", return_value=_INVOICE_ROW),
        patch("services.invoice_service.download_pdf", return_value=b"%PDF"),
        patch("services.invoice_service.get_contact", return_value=_CONTACT_NO_EMAIL),
        patch("services.invoice_service.send_invoice_email") as mock_send,
        patch("services.invoice_service.update_last_resent_at") as mock_update,
    ):
        result = await resend_invoice("ZARAFFA26-3", send_email=True)

    assert result.email_status == "skipped_no_email"
    assert "client_a" in result.email_status_message
    assert result.pdf_bytes == b"%PDF"
    mock_send.assert_not_awaited()
    mock_update.assert_not_awaited()


async def test_resend_email_requested_but_contact_missing():
    """Contact deleted/renamed since invoice was issued: same graceful degrade."""
    with (
        patch("services.invoice_service.get_invoice", return_value=_INVOICE_ROW),
        patch("services.invoice_service.download_pdf", return_value=b"%PDF"),
        patch("services.invoice_service.get_contact", return_value=None),
        patch("services.invoice_service.send_invoice_email") as mock_send,
        patch("services.invoice_service.update_last_resent_at") as mock_update,
    ):
        result = await resend_invoice("ZARAFFA26-3", send_email=True)

    assert result.email_status == "skipped_no_email"
    mock_send.assert_not_awaited()
    mock_update.assert_not_awaited()


async def test_resend_email_send_failure():
    """Email send raises: PDF bytes still returned, status=failed, message set,
    last_resent_at NOT updated (we only mark as resent on success)."""
    with (
        patch("services.invoice_service.get_invoice", return_value=_INVOICE_ROW),
        patch("services.invoice_service.download_pdf", return_value=b"%PDF"),
        patch("services.invoice_service.get_contact", return_value=_CONTACT_WITH_EMAIL),
        patch(
            "services.invoice_service.send_invoice_email",
            side_effect=Exception("Resend API error"),
        ),
        patch("services.invoice_service.update_last_resent_at") as mock_update,
    ):
        result = await resend_invoice("ZARAFFA26-3", send_email=True)

    assert result.email_status == "failed"
    assert result.email_status_message
    assert result.pdf_bytes == b"%PDF"
    mock_update.assert_not_awaited()


# ---------------------------------------------------------------------------
# Handler: /resend command
# ---------------------------------------------------------------------------

async def test_resend_command_no_args_shows_usage():
    update = _make_command_update("/resend")
    ctx = _make_command_context(args=[])
    await resend_command(update, ctx)

    update.message.reply_text.assert_awaited_once()
    msg = update.message.reply_text.await_args.args[0]
    assert "Usage" in msg
    update.message.reply_document.assert_not_awaited()


async def test_resend_command_unknown_second_arg_rejected():
    update = _make_command_update("/resend ZARAFFA26-3 nonsense")
    ctx = _make_command_context(args=["ZARAFFA26-3", "nonsense"])
    await resend_command(update, ctx)

    msg = update.message.reply_text.await_args.args[0]
    assert "Unknown option" in msg
    assert "nonsense" in msg
    update.message.reply_document.assert_not_awaited()


async def test_resend_command_too_many_args():
    update = _make_command_update("/resend ZARAFFA26-3 email extra")
    ctx = _make_command_context(args=["ZARAFFA26-3", "email", "extra"])
    await resend_command(update, ctx)

    msg = update.message.reply_text.await_args.args[0]
    assert "Too many" in msg
    update.message.reply_document.assert_not_awaited()


async def test_resend_command_invoice_not_found():
    update = _make_command_update("/resend ZARAFFA99-99")
    ctx = _make_command_context(args=["ZARAFFA99-99"])

    with patch(
        "bot.handlers.resend_invoice",
        side_effect=InvoiceNotFoundError("ZARAFFA99-99"),
    ):
        await resend_command(update, ctx)

    msg = update.message.reply_text.await_args.args[0]
    assert "not found" in msg.lower()
    update.message.reply_document.assert_not_awaited()


async def test_resend_command_telegram_only_delivers_pdf():
    update = _make_command_update("/resend ZARAFFA26-3")
    ctx = _make_command_context(args=["ZARAFFA26-3"])

    fake_result = ResendResult(
        pdf_bytes=b"%PDF",
        invoice_number="ZARAFFA26-3",
        email_status="not_requested",
        email_status_message=None,
    )
    with patch("bot.handlers.resend_invoice", return_value=fake_result):
        await resend_command(update, ctx)

    update.message.reply_document.assert_awaited_once()
    kwargs = update.message.reply_document.await_args.kwargs
    assert kwargs["filename"] == "Invoice_ZARAFFA26-3.pdf"
    assert kwargs["document"] == b"%PDF"


async def test_resend_command_email_success_announces_then_delivers():
    update = _make_command_update("/resend ZARAFFA26-3 email")
    ctx = _make_command_context(args=["ZARAFFA26-3", "email"])

    fake_result = ResendResult(
        pdf_bytes=b"%PDF",
        invoice_number="ZARAFFA26-3",
        email_status="sent",
        email_status_message=None,
    )
    with patch("bot.handlers.resend_invoice", return_value=fake_result):
        await resend_command(update, ctx)

    # First reply_text says re-sent by email
    msg = update.message.reply_text.await_args.args[0]
    assert "re-sent by email" in msg
    update.message.reply_document.assert_awaited_once()


async def test_resend_command_email_skipped_explains_and_delivers():
    """Email requested, contact has no email: user sees the explanation AND
    still gets the PDF via Telegram."""
    update = _make_command_update("/resend ZARAFFA26-3 email")
    ctx = _make_command_context(args=["ZARAFFA26-3", "email"])

    fake_result = ResendResult(
        pdf_bytes=b"%PDF",
        invoice_number="ZARAFFA26-3",
        email_status="skipped_no_email",
        email_status_message="Cannot re-email: contact client_a has no email on file.",
    )
    with patch("bot.handlers.resend_invoice", return_value=fake_result):
        await resend_command(update, ctx)

    msg = update.message.reply_text.await_args.args[0]
    assert "Cannot re-email" in msg
    update.message.reply_document.assert_awaited_once()


async def test_resend_command_unauthorized_silent():
    update = _make_command_update("/resend ZARAFFA26-3")
    update.effective_chat.id = 999_999_999  # not in ALLOWED_CHAT_IDS
    ctx = _make_command_context(args=["ZARAFFA26-3"])

    await resend_command(update, ctx)

    update.message.reply_text.assert_not_awaited()
    update.message.reply_document.assert_not_awaited()
