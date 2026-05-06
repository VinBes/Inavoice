"""Tests 1.1–1.9: merge_and_compute computation, defaults merging, and edge cases.

These tests call merge_and_compute directly with mock LLMOutput objects and mock
contact dicts. No I/O, no real API calls.
"""
from decimal import Decimal

import pytest

from models.schemas import LLMLineItem, LLMOutput
from services.invoice_service import merge_and_compute
from services.llm_parser import _strip_code_fence

# ---------------------------------------------------------------------------
# Shared test data (per testing.md)
# ---------------------------------------------------------------------------

CLIENT_A = {
    "client_id": "client_a",
    "display_name": "Client A Ltd.",
    "contact_person": None,
    "address": "{{CLIENT_A_ADDRESS}}",
    "email": "accounts@client-a.example.com",
    "default_description": "Invoice for Client A booking",
    "default_service_description": "Service for Client A",
    "default_rate": 500,
}

CLIENT_B = {
    "client_id": "client_b",
    "display_name": "Client B Ltd.",
    "contact_person": "{{CLIENT_B_CONTACT}}",
    "address": "{{CLIENT_B_ADDRESS}}",
    "email": None,
    "default_description": "Invoice for Client B services",
    "default_service_description": "Service for Client B",
    "default_rate": None,
}


def _make_output(
    client_id="client_a",
    description=None,
    service_date="26/03/2026",
    service_description=None,
    time_start="22:00",
    time_end="00:00",
    rate=500,
    rate_type="hourly",
) -> LLMOutput:
    return LLMOutput(
        client_id=client_id,
        description=description,
        line_items=[
            LLMLineItem(
                service_date=service_date,
                service_description=service_description,
                time_start=time_start,
                time_end=time_end,
                rate=rate,
                rate_type=rate_type,
                total=None,
            )
        ],
        missing_fields=[],
    )


# ---------------------------------------------------------------------------
# Test 1.1 — Full input, hourly rate
# ---------------------------------------------------------------------------

def test_1_1_full_hourly():
    parsed = _make_output(
        description="Invoice for Client A booking",
        service_description="Service for Client A",
        time_start="22:00",
        time_end="00:00",
        rate=500,
        rate_type="hourly",
    )
    result = merge_and_compute(parsed, CLIENT_A)

    assert result["hours"] == Decimal("2")
    assert result["total"] == Decimal("1000")
    assert result["rate"] == Decimal("500")
    assert result["display_name"] == "Client A Ltd."
    assert result["due_date"] == result["invoice_date"] + __import__("datetime").timedelta(days=14)


# ---------------------------------------------------------------------------
# Test 1.2 — Full input, flat rate
# ---------------------------------------------------------------------------

def test_1_2_full_flat():
    parsed = _make_output(
        client_id="client_b",
        description="Invoice for Client B services",
        service_description="Service for Client B",
        service_date="15/04/2026",
        time_start=None,
        time_end=None,
        rate=2000,
        rate_type="flat",
    )
    result = merge_and_compute(parsed, CLIENT_B)

    assert result["hours"] is None
    assert result["total"] == Decimal("2000")
    assert result["time_start"] is None
    assert result["time_end"] is None


# ---------------------------------------------------------------------------
# Test 1.3 — Null fields filled from client defaults
# ---------------------------------------------------------------------------

def test_1_3_defaults_applied():
    parsed = _make_output(
        description=None,
        service_description=None,
        rate=None,
        rate_type="hourly",
        time_start="22:00",
        time_end="00:00",
    )
    result = merge_and_compute(parsed, CLIENT_A)

    assert result["description"] == "Invoice for Client A booking"
    assert result["service_description"] == "Service for Client A"
    assert result["rate"] == Decimal("500")
    assert result["hours"] == Decimal("2")
    assert result["total"] == Decimal("1000")


# ---------------------------------------------------------------------------
# Test 1.4 — Midnight crossing
# ---------------------------------------------------------------------------

def test_1_4_midnight_crossing():
    parsed = _make_output(time_start="22:00", time_end="02:00", rate=500, rate_type="hourly")
    result = merge_and_compute(parsed, CLIENT_A)

    assert result["hours"] == Decimal("4")
    assert result["total"] == Decimal("2000")


# ---------------------------------------------------------------------------
# Test 1.5 — Same start and end time → ValueError
# ---------------------------------------------------------------------------

def test_1_5_zero_hours_raises():
    parsed = _make_output(time_start="22:00", time_end="22:00", rate=500, rate_type="hourly")
    with pytest.raises(ValueError, match="0 hours is invalid"):
        merge_and_compute(parsed, CLIENT_A)


# ---------------------------------------------------------------------------
# Test 1.6 — Missing rate, no client default → ValueError
# ---------------------------------------------------------------------------

def test_1_6_missing_rate_no_default():
    parsed = _make_output(
        client_id="client_b",
        rate=None,
        rate_type="hourly",
        time_start="22:00",
        time_end="00:00",
    )
    with pytest.raises(ValueError, match="rate is required"):
        merge_and_compute(parsed, CLIENT_B)


# ---------------------------------------------------------------------------
# Test 1.7 — Unknown client_id: note on design
# ---------------------------------------------------------------------------

def test_1_7_unknown_client_note():
    """Client existence validation is the caller's responsibility (handler layer).

    merge_and_compute only operates on the contact dict passed in. If the
    caller passes a valid contact for an unknown client_id, computation succeeds.
    The handler verifies client_id against the contacts table before calling here.
    """
    fake_contact = {
        "client_id": "nonexistent",
        "display_name": "Ghost Client",
        "email": None,
        "default_description": "Ghost invoice",
        "default_service_description": "Ghost service",
        "default_rate": 100,
    }
    parsed = _make_output(client_id="nonexistent", rate=100, rate_type="hourly",
                          time_start="10:00", time_end="12:00")
    result = merge_and_compute(parsed, fake_contact)
    assert result["total"] == Decimal("200")


# ---------------------------------------------------------------------------
# Test 1.8 — Service date far in future: no error in compute
# ---------------------------------------------------------------------------

def test_1_8_future_date_no_error():
    """Date range validation (>90 days future) is the caller's responsibility.

    merge_and_compute does not validate service_date range. The handler checks
    this before calling merge_and_compute and asks the user to confirm.
    """
    parsed = _make_output(service_date="01/01/2099", rate=500, rate_type="hourly",
                          time_start="10:00", time_end="12:00")
    result = merge_and_compute(parsed, CLIENT_A)
    assert result["service_date"] == "01/01/2099"
    assert result["total"] == Decimal("1000")


# ---------------------------------------------------------------------------
# Test 1.9 — Negative rate → ValueError
# ---------------------------------------------------------------------------

def test_1_9_negative_rate():
    parsed = _make_output(rate=-500, rate_type="hourly", time_start="22:00", time_end="00:00")
    with pytest.raises(ValueError, match="rate must be positive"):
        merge_and_compute(parsed, CLIENT_A)


# ---------------------------------------------------------------------------
# _strip_code_fence — defensive parsing for markdown-wrapped LLM responses
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("wrapped,expected", [
    ('```json\n{"a": 1}\n```', '{"a": 1}'),
    ('```\n{"a": 1}\n```', '{"a": 1}'),
    ('  ```json\n{"a": 1}\n```  ', '{"a": 1}'),
    ('{"a": 1}', '{"a": 1}'),
    ('```json\n{\n  "client_id": "client_a"\n}\n```', '{\n  "client_id": "client_a"\n}'),
])
def test_strip_code_fence(wrapped, expected):
    assert _strip_code_fence(wrapped) == expected
