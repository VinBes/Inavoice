import asyncio
from datetime import datetime, timezone

from db.client import get_client


async def next_invoice_number(year: int) -> str:
    """Atomically increment counter for year and return formatted invoice number."""

    def _sync():
        return get_client().rpc("increment_invoice_counter", {"p_year": year}).execute().data

    counter = await asyncio.to_thread(_sync)
    yy = str(year)[-2:]
    return f"ZARAFFA{yy}-{counter}"


async def save_invoice(data: dict) -> None:
    def _sync():
        get_client().table("invoices").insert(data).execute()

    await asyncio.to_thread(_sync)


async def list_recent_invoices(limit: int = 10) -> list[dict]:
    def _sync():
        return (
            get_client()
            .table("invoices")
            .select("invoice_number, invoice_date, client_id, subtotal")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data
        )

    return await asyncio.to_thread(_sync)


async def get_invoice(invoice_number: str) -> dict | None:
    def _sync():
        r = (
            get_client()
            .table("invoices")
            .select("*")
            .eq("invoice_number", invoice_number)
            .execute()
        )
        return r.data[0] if r.data else None

    return await asyncio.to_thread(_sync)


async def update_last_resent_at(invoice_number: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()

    def _sync():
        get_client().table("invoices").update(
            {"last_resent_at": timestamp}
        ).eq("invoice_number", invoice_number).execute()

    await asyncio.to_thread(_sync)


async def download_pdf(storage_path: str) -> bytes:
    def _sync():
        return get_client().storage.from_("invoices").download(storage_path)

    return await asyncio.to_thread(_sync)


async def update_email_id(invoice_number: str, email_id: str) -> None:
    """Persist the Resend response id so webhook events can find this invoice."""

    def _sync():
        get_client().table("invoices").update(
            {"email_id": email_id}
        ).eq("invoice_number", invoice_number).execute()

    await asyncio.to_thread(_sync)


async def find_by_email_id(email_id: str) -> dict | None:
    def _sync():
        r = (
            get_client()
            .table("invoices")
            .select("*")
            .eq("email_id", email_id)
            .execute()
        )
        return r.data[0] if r.data else None

    return await asyncio.to_thread(_sync)


async def update_email_delivery(
    invoice_number: str,
    status: str,
    occurred_at: datetime,
) -> None:
    """Set delivery status from a Resend webhook event.

    For `delivered`, also flips `email_sent` true and stamps `email_sent_at` (the
    initial send only logs locally — webhook is the authoritative success signal).
    """
    payload: dict = {
        "email_delivery_status": status,
        "email_delivery_event_at": occurred_at.isoformat(),
    }
    if status == "delivered":
        payload["email_sent"] = True
        payload["email_sent_at"] = occurred_at.isoformat()

    def _sync():
        get_client().table("invoices").update(payload).eq(
            "invoice_number", invoice_number
        ).execute()

    await asyncio.to_thread(_sync)


async def count_invoices_for_contact(client_id: str) -> int:
    """Used by /contacts delete to refuse deletion when invoices reference the contact."""

    def _sync():
        r = (
            get_client()
            .table("invoices")
            .select("invoice_number", count="exact")
            .eq("client_id", client_id)
            .execute()
        )
        return r.count or 0

    return await asyncio.to_thread(_sync)
