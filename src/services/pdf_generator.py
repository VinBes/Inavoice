from models.schemas import InvoiceData


async def generate_pdf(data: InvoiceData, invoice_number: str) -> bytes:
    raise NotImplementedError
