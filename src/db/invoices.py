from db.client import get_client


async def next_invoice_number(year: int) -> str:
    """Atomically increment counter for year and return formatted invoice number."""
    raise NotImplementedError


async def save_invoice(data: dict) -> None:
    raise NotImplementedError
