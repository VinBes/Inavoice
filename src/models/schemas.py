import re
from decimal import Decimal
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

_DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}$")
_CLIENT_ID_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


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


class Contact(BaseModel):
    client_id: str
    display_name: str
    address: str
    contact_person: Optional[str] = None
    email: Optional[str] = None
    default_description: Optional[str] = None
    default_service_description: Optional[str] = None
    default_rate: Optional[Decimal] = None

    @field_validator("client_id")
    @classmethod
    def _client_id_slug(cls, v: str) -> str:
        if not _CLIENT_ID_RE.match(v):
            raise ValueError(
                "client_id must be lowercase letters, digits, or underscores, max 64 chars"
            )
        return v

    @field_validator("email")
    @classmethod
    def _email_format(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _EMAIL_RE.match(v):
            raise ValueError("email must look like name@domain.tld")
        return v

    @field_validator("default_rate")
    @classmethod
    def _rate_positive(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("default_rate must be positive")
        return v


# Resend webhook payloads. Only the fields the bot uses are typed; extras are
# preserved (`extra="allow"`) so we don't break on new fields Resend adds later.
class _ResendBounceDetails(BaseModel):
    model_config = ConfigDict(extra="allow")
    message: Optional[str] = None
    subType: Optional[str] = None  # "Suppressed", "MessageRejected", etc.
    type: Optional[str] = None     # "Permanent" or "Temporary"


class ResendDeliveredData(BaseModel):
    model_config = ConfigDict(extra="allow")
    email_id: str


class ResendBouncedData(BaseModel):
    model_config = ConfigDict(extra="allow")
    email_id: str
    bounce: Optional[_ResendBounceDetails] = None


class ResendComplainedData(BaseModel):
    model_config = ConfigDict(extra="allow")
    email_id: str


class ResendDeliveredEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["email.delivered"]
    created_at: Optional[str] = None
    data: ResendDeliveredData


class ResendBouncedEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["email.bounced"]
    created_at: Optional[str] = None
    data: ResendBouncedData


class ResendComplainedEvent(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["email.complained"]
    created_at: Optional[str] = None
    data: ResendComplainedData


ResendWebhookEvent = Annotated[
    Union[ResendDeliveredEvent, ResendBouncedEvent, ResendComplainedEvent],
    Field(discriminator="type"),
]
