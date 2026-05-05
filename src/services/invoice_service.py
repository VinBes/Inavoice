from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from models.schemas import LLMOutput
import config

HKT = ZoneInfo(config.TIMEZONE)


def merge_and_compute(parsed: LLMOutput, contact: dict) -> dict:
    """Merge LLM output with client defaults and compute derived fields.

    Returns a flat dict ready for format_confirmation and PDF generation.
    Raises ValueError for invalid rate or zero-duration hourly sessions.
    """
    item = parsed.line_items[0]

    description = parsed.description or contact.get("default_description")
    service_description = item.service_description or contact.get("default_service_description")

    raw_rate = item.rate if item.rate is not None else contact.get("default_rate")
    if raw_rate is None:
        raise ValueError("rate is required but not provided and contact has no default_rate")
    rate = Decimal(str(raw_rate))
    if rate <= 0:
        raise ValueError(f"rate must be positive, got {rate}")

    hours = total = None
    if item.rate_type == "hourly":
        if item.time_start and item.time_end:
            hours = _compute_hours(item.time_start, item.time_end)
        if hours is not None:
            total = rate * hours
    elif item.rate_type == "flat":
        total = rate

    today = datetime.now(HKT).date()
    return {
        "client_id": parsed.client_id,
        "display_name": contact["display_name"],
        "email": contact.get("email"),
        "description": description,
        "service_date": item.service_date,
        "service_description": service_description,
        "time_start": item.time_start,
        "time_end": item.time_end,
        "hours": hours,
        "rate": rate,
        "rate_type": item.rate_type,
        "total": total,
        "invoice_date": today,
        "due_date": today + timedelta(days=14),
    }


def _compute_hours(time_start: str, time_end: str) -> Decimal:
    sh, sm = map(int, time_start.split(":"))
    eh, em = map(int, time_end.split(":"))
    start = sh * 60 + sm
    end = eh * 60 + em
    if start == end:
        raise ValueError("time_start and time_end are the same — 0 hours is invalid")
    if end < start:
        end += 1440
    return Decimal(end - start) / 60


async def create_invoice(data: dict) -> str:
    """Generate invoice number, store PDF, save to DB. Returns invoice_number."""
    raise NotImplementedError
