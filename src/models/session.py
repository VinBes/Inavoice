from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

from models.schemas import InvoiceData


@dataclass
class Session:
    chat_id: int
    started_at: datetime = field(default_factory=datetime.utcnow)
    raw_input: Optional[str] = None
    parsed_data: Optional[InvoiceData] = None
    llm_call_count: int = 0
    state: str = "idle"  # idle | awaiting_confirm | awaiting_delivery
