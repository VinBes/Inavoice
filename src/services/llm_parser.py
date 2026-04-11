from models.schemas import InvoiceData


async def parse_invoice_text(text: str) -> InvoiceData:
    raise NotImplementedError
