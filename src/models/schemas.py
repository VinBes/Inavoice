from pydantic import BaseModel
from typing import Optional
from decimal import Decimal


class LineItem(BaseModel):
    description: str
    quantity: Decimal
    unit_price: Decimal
    total: Decimal


class InvoiceData(BaseModel):
    client_id: str
    invoice_date: str       # ISO 8601, e.g. "2026-04-11"
    due_date: str           # ISO 8601
    description: str
    line_items: list[LineItem]
    total: Decimal
    currency: str = "HKD"
    recipient_email: Optional[str] = None
