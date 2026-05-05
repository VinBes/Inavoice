"""Tests 5.1–5.2: daily API cap and per-session LLM call cap."""
from datetime import date

import pytest

import config
import services.llm_parser as llm_parser
from services.llm_parser import (
    DailyCapExceededError,
    SessionCapExceededError,
    parse_invoice_text,
)


def _reset_daily():
    llm_parser._daily_calls = 0
    llm_parser._daily_reset_date = date.today()


# ---------------------------------------------------------------------------
# Test 5.1 — Daily Claude API cap blocks further calls
# ---------------------------------------------------------------------------

async def test_5_1_daily_cap_raises():
    _reset_daily()
    llm_parser._daily_calls = config.DAILY_CLAUDE_API_CAP

    with pytest.raises(DailyCapExceededError):
        await parse_invoice_text("invoice for client a", session_call_count=0)

    _reset_daily()


async def test_5_1_daily_cap_resets_at_midnight():
    # Simulating a new day: set reset_date to yesterday, calls to max
    import datetime
    yesterday = date.today() - datetime.timedelta(days=1)
    llm_parser._daily_calls = config.DAILY_CLAUDE_API_CAP
    llm_parser._daily_reset_date = yesterday

    # First call on a "new day" should reset the counter (MOCK_MODE returns fixture)
    # Should NOT raise DailyCapExceededError — counter resets because date changed
    try:
        await parse_invoice_text("client a invoice", session_call_count=0, contacts=[])
    except DailyCapExceededError:
        pytest.fail("DailyCapExceededError should not be raised on a new day")
    except Exception:
        pass  # LLMParseError from mock is fine — we only care it's not the cap error

    assert llm_parser._daily_reset_date == date.today()
    _reset_daily()


# ---------------------------------------------------------------------------
# Test 5.2 — Per-session LLM call cap blocks further calls
# ---------------------------------------------------------------------------

async def test_5_2_session_cap_raises():
    with pytest.raises(SessionCapExceededError):
        await parse_invoice_text(
            "invoice for client a",
            session_call_count=config.SESSION_LLM_CALL_CAP,
        )


async def test_5_2_session_cap_at_boundary():
    # session_call_count == cap - 1 should NOT raise (still within limit)
    # MOCK_MODE will handle the actual parse
    try:
        await parse_invoice_text(
            "client a invoice",
            session_call_count=config.SESSION_LLM_CALL_CAP - 1,
            contacts=[],
        )
    except SessionCapExceededError:
        pytest.fail("SessionCapExceededError should not be raised below the cap")
    except Exception:
        pass  # LLMParseError from mock with no contacts is fine
