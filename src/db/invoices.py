import asyncio

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
