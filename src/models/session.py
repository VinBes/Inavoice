from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

PENDING = "PENDING"
CONFIRMED = "CONFIRMED"
GENERATING = "GENERATING"
COMPLETE = "COMPLETE"
CANCELLED = "CANCELLED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Session:
    state: str = PENDING
    parsed_data: Optional[dict] = None   # LLMOutput-shaped dict; used as previous_data for correction LLM calls
    computed_data: Optional[dict] = None  # flat merged/computed dict; used for PDF + confirmation display
    llm_call_count: int = 0
    created_at: datetime = field(default_factory=_now)
    last_active: datetime = field(default_factory=_now)
    invoice_number: Optional[str] = None
    message_id: Optional[int] = None
