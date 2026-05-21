import asyncio

import resend
import structlog

import config

log = structlog.get_logger()


async def send_invoice_email(
    to: str,
    invoice_number: str,
    pdf_bytes: bytes,
    contact_person: str | None,
    display_name: str,
    due_date: str,
) -> str | None:
    """Send invoice PDF via Resend. In MOCK_MODE logs to stdout instead.

    Returns the Resend message id on success (None in MOCK_MODE). The id is
    persisted on the invoices row so webhook events can find the right invoice.
    """
    if config.MOCK_MODE:
        print(
            f"[MOCK EMAIL] Invoice {invoice_number} — {config.SENDER_NAME} | Due: {due_date}"
        )
        log.info("email_sender.mock", invoice_number=invoice_number)
        return None

    greeting = contact_person or display_name
    signature = f"{config.SENDER_NAME}\n{config.SENDER_COMPANY}" if config.SENDER_COMPANY else config.SENDER_NAME
    body = (
        f"Dear {greeting},\n\n"
        f"Please find attached invoice {invoice_number} for services rendered.\n\n"
        f"Payment is due by {due_date}. Payment details are included in the invoice.\n\n"
        f"Kind regards,\n{signature}"
    )

    def _sync() -> dict:
        resend.api_key = config.RESEND_API_KEY
        return resend.Emails.send({
            "from": config.EMAIL_FROM_ADDRESS,
            "to": [to],
            "subject": f"Invoice {invoice_number} — {config.SENDER_NAME}",
            "text": body,
            "attachments": [{
                "filename": f"Invoice_{invoice_number}.pdf",
                "content": list(pdf_bytes),
                "content_type": "application/pdf",
            }],
        })

    response = await asyncio.to_thread(_sync)
    email_id = (response or {}).get("id")
    log.info(
        "email_sender.sent", invoice_number=invoice_number, email_id=email_id
    )
    return email_id
