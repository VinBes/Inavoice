from models.schemas import InvoiceData


async def create_invoice(data: InvoiceData) -> str:
    """Generate invoice number, store PDF, save to DB. Returns invoice_number."""
    raise NotImplementedError
