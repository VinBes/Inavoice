import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, Optional
from zoneinfo import ZoneInfo

import structlog

import config
from db.client import get_client
from db.contacts import get_contact
from db.invoices import (
    download_pdf,
    get_invoice,
    next_invoice_number,
    save_invoice,
    update_last_resent_at,
)
from models.schemas import Contact, LLMOutput
from services.email_sender import send_invoice_email
from services.pdf_generator import generate_pdf

log = structlog.get_logger()

HKT = ZoneInfo(config.TIMEZONE)


EmailStatus = Literal["not_requested", "sent", "skipped_no_email", "failed"]


class InvoiceNotFoundError(Exception):
    """Raised by resend_invoice when the invoice number is not in the DB."""


@dataclass
class ResendResult:
    pdf_bytes: bytes
    invoice_number: str
    email_status: EmailStatus
    email_status_message: Optional[str]


def merge_and_compute(parsed: LLMOutput, contact: Contact) -> dict:
    """Merge LLM output with client defaults and compute derived fields.

    Returns a flat dict ready for format_confirmation and PDF generation.
    Raises ValueError for invalid rate or zero-duration hourly sessions.
    """
    item = parsed.line_items[0]

    description = parsed.description or contact.default_description
    service_description = item.service_description or contact.default_service_description

    raw_rate = item.rate if item.rate is not None else contact.default_rate
    if raw_rate is None:
        raise ValueError("rate is required but not provided and contact has no default_rate")
    rate = Decimal(str(raw_rate))
    if rate <= 0:
        raise ValueError(f"rate must be positive, got {rate}")

    hours = total = None
    if item.rate_type == "hourly":
        if item.time_start and item.time_end:
            hours = _compute_hours(item.time_start, item.time_end)
        if hours is not None:
            total = rate * hours
    elif item.rate_type == "flat":
        total = rate

    today = datetime.now(HKT).date()
    return {
        "client_id": parsed.client_id,
        "display_name": contact.display_name,
        "contact_person": contact.contact_person,
        "address": contact.address,
        "email": contact.email,
        "description": description,
        "service_date": item.service_date,
        "service_description": service_description,
        "time_start": item.time_start,
        "time_end": item.time_end,
        "hours": hours,
        "rate": rate,
        "rate_type": item.rate_type,
        "total": total,
        "invoice_date": today,
        "due_date": today + timedelta(days=14),
    }


def _compute_hours(time_start: str, time_end: str) -> Decimal:
    sh, sm = map(int, time_start.split(":"))
    eh, em = map(int, time_end.split(":"))
    start = sh * 60 + sm
    end = eh * 60 + em
    if start == end:
        raise ValueError("time_start and time_end are the same — 0 hours is invalid")
    if end < start:
        end += 1440
    return Decimal(end - start) / 60


async def create_invoice(data: dict) -> tuple[str, bytes]:
    """Claim invoice number, generate PDF, upload to storage, save to DB.

    Returns (invoice_number, pdf_bytes). pdf_bytes are returned so the handler
    can deliver them via Telegram without a second download from storage.
    """
    today = datetime.now(HKT).date()
    invoice_number = await next_invoice_number(today.year)

    pdf_bytes = await generate_pdf(data, invoice_number)

    if data.get("total") is None:
        raise ValueError("Cannot create invoice: total is None")

    storage_path = f"{today.year}/{invoice_number}.pdf"

    def _upload() -> None:
        get_client().storage.from_("invoices").upload(
            storage_path, pdf_bytes, {"content-type": "application/pdf"}
        )

    await asyncio.to_thread(_upload)

    try:
        await save_invoice({
            "invoice_number": invoice_number,
            "client_id": data["client_id"],
            "invoice_date": str(data["invoice_date"]),
            "due_date": str(data["due_date"]),
            "description": data["description"],
            "line_items": [{
                "service_date": data["service_date"],
                "service_description": data["service_description"],
                "time_start": data.get("time_start"),
                "time_end": data.get("time_end"),
                "rate": str(data["rate"]),
                "rate_type": data["rate_type"],
                "total": str(data["total"]),
            }],
            "subtotal": str(data["total"]),
            "pdf_storage_path": storage_path,
            "email_sent": False,
        })
    except Exception:
        # DB row failed: remove the orphaned PDF so storage doesn't accumulate
        # files with no matching invoice record. Invoice number stays burned.
        log.exception("invoice_service.save_failed", invoice_number=invoice_number)
        try:
            await asyncio.to_thread(
                lambda: get_client().storage.from_("invoices").remove([storage_path])
            )
            log.info("invoice_service.storage_cleanup", storage_path=storage_path)
        except Exception:
            log.exception(
                "invoice_service.storage_cleanup_failed", storage_path=storage_path
            )
        raise

    log.info(
        "invoice_service.created",
        invoice_number=invoice_number,
        client_id=data["client_id"],
    )
    return invoice_number, pdf_bytes


async def resend_invoice(invoice_number: str, *, send_email: bool) -> ResendResult:
    """Re-deliver an existing invoice. Telegram-only by default; opt in to re-email.

    Raises InvoiceNotFoundError if the invoice_number does not exist.
    Never raises on email failure or missing-email — those are reflected in
    ResendResult.email_status so the caller can render a graceful response.
    """
    invoice = await get_invoice(invoice_number)
    if invoice is None:
        raise InvoiceNotFoundError(invoice_number)

    pdf_bytes = await download_pdf(invoice["pdf_storage_path"])

    if not send_email:
        log.info(
            "resend.telegram_only",
            invoice_number=invoice_number,
            client_id=invoice["client_id"],
        )
        return ResendResult(pdf_bytes, invoice_number, "not_requested", None)

    contact = await get_contact(invoice["client_id"])
    if contact is None or not contact.email:
        log.info(
            "resend.skipped_no_email",
            invoice_number=invoice_number,
            client_id=invoice["client_id"],
        )
        return ResendResult(
            pdf_bytes,
            invoice_number,
            "skipped_no_email",
            f"Cannot re-email: contact {invoice['client_id']} has no email on file.",
        )

    try:
        await send_invoice_email(
            contact.email,
            invoice_number,
            pdf_bytes,
            contact.contact_person,
            contact.display_name,
            str(invoice["due_date"]),
        )
    except Exception as e:
        log.error(
            "resend.email_failed",
            invoice_number=invoice_number,
            error_type=type(e).__name__,
        )
        return ResendResult(
            pdf_bytes,
            invoice_number,
            "failed",
            "Email re-send failed. Sending PDF via Telegram only.",
        )

    await update_last_resent_at(invoice_number)
    log.info(
        "resend.emailed",
        invoice_number=invoice_number,
        client_id=invoice["client_id"],
    )
    return ResendResult(pdf_bytes, invoice_number, "sent", None)
