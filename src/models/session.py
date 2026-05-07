from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal, Optional

PENDING = "PENDING"
CONFIRMED = "CONFIRMED"
GENERATING = "GENERATING"
COMPLETE = "COMPLETE"
CANCELLED = "CANCELLED"

SessionMode = Literal["invoice", "add_contact", "edit_contact"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Session:
    state: str = PENDING
    mode: SessionMode = "invoice"
    parsed_data: Optional[dict] = None   # LLMOutput-shaped dict; used as previous_data for correction LLM calls
    computed_data: Optional[dict] = None  # flat merged/computed dict; used for PDF + confirmation display
    llm_call_count: int = 0
    created_at: datetime = field(default_factory=_now)
    last_active: datetime = field(default_factory=_now)
    invoice_number: Optional[str] = None
    message_id: Optional[int] = None
    contact_draft: Optional[dict] = None  # partial dict during /contacts add; validated to Contact at confirm
    delete_target: Optional[str] = None   # client_id pending deletion; populated by /contacts delete, cleared on confirm/cancel
