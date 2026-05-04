import re
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, field_validator

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class LLMLineItem(BaseModel):
    service_date: str
    service_description: Optional[str] = None
    time_start: Optional[str] = None
    time_end: Optional[str] = None
    rate: Optional[Decimal] = None
    rate_type: Literal["hourly", "flat"]
    total: None = None  # backend computes; LLM must always output null

    @field_validator("service_date")
    @classmethod
    def validate_service_date(cls, v: str) -> str:
        if not _DATE_RE.match(v):
            raise ValueError(f"service_date must be DD/MM/YYYY, got: {v!r}")
        return v

    @field_validator("time_start", "time_end", mode="before")
    @classmethod
    def validate_time(cls, v: object) -> object:
        if v is not None and not _TIME_RE.match(str(v)):
            raise ValueError(f"time field must be HH:MM (24h), got: {v!r}")
        return v


class LLMOutput(BaseModel):
    client_id: Optional[str] = None
    description: Optional[str] = None
    line_items: list[LLMLineItem]
    missing_fields: list[str] = []
