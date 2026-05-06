"""Tests 5.1–5.2: daily API cap and per-session LLM call cap."""
from datetime import date
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest

import config
import services.llm_parser as llm_parser
from services.llm_parser import (
    DailyCapExceededError,
    LLMAPIError,
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


# ---------------------------------------------------------------------------
# Anthropic API errors (e.g. insufficient credits, auth, rate limit) are
# converted to the domain-level LLMAPIError so the handler can reply to the
# user instead of letting the exception bubble out of python-telegram-bot.
# ---------------------------------------------------------------------------

async def test_anthropic_api_error_becomes_llm_api_error(monkeypatch):
    _reset_daily()
    monkeypatch.setattr(config, "MOCK_MODE", False)

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(
        400,
        request=request,
        json={"type": "error", "error": {"type": "invalid_request_error",
                                          "message": "Your credit balance is too low"}},
    )

    fake_client = AsyncMock()
    fake_client.messages.create.side_effect = anthropic.BadRequestError(
        message="credit balance too low", response=response, body=None
    )
    monkeypatch.setattr(llm_parser, "_get_client", lambda: fake_client)

    with pytest.raises(LLMAPIError):
        await parse_invoice_text("invoice for client a", contacts=[], session_call_count=0)

    _reset_daily()
