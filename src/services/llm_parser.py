import asyncio
import json
import pathlib
from datetime import date
from zoneinfo import ZoneInfo

import anthropic
import structlog

import config
from db.api_usage import increment_claude_daily_calls
from models.schemas import LLMOutput

log = structlog.get_logger()

HKT = ZoneInfo(config.TIMEZONE)

FIXTURES_DIR = pathlib.Path(__file__).parent.parent.parent / "tests" / "fixtures" / "claude_responses"

_MODEL = "claude-haiku-4-5-20251001"
_RETRY_DELAY_SECONDS = 3

_JSON_SCHEMA = """{
  "client_id": "string | null",
  "description": "string | null",
  "line_items": [
    {
      "service_date": "string (DD/MM/YYYY)",
      "service_description": "string | null",
      "time_start": "string (HH:MM, 24h format) | null",
      "time_end": "string (HH:MM, 24h format) | null",
      "rate": "number | null",
      "rate_type": "hourly | flat",
      "total": null
    }
  ],
  "missing_fields": ["string"]
}"""

_client: anthropic.AsyncAnthropic | None = None
_daily_calls: int = 0
_daily_reset_date: date | None = None


class LLMParseError(Exception):
    pass


class LLMValidationError(Exception):
    pass


class LLMAPIError(Exception):
    """Raised when the Anthropic API itself returns an error (auth, billing, rate limit, network)."""
    pass


class DailyCapExceededError(Exception):
    pass


class SessionCapExceededError(Exception):
    pass


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


async def _check_and_increment_daily(today: date) -> None:
    """Atomically increment the daily Claude call counter and enforce the cap.

    In MOCK_MODE this uses an in-memory counter so tests and local dev don't
    require a live database. In production it goes through the Supabase RPC
    so the counter survives container restarts.
    """
    global _daily_calls, _daily_reset_date
    if config.MOCK_MODE:
        if _daily_reset_date != today:
            _daily_calls = 0
            _daily_reset_date = today
        if _daily_calls >= config.DAILY_CLAUDE_API_CAP:
            raise DailyCapExceededError(
                f"Daily Claude API cap of {config.DAILY_CLAUDE_API_CAP} reached"
            )
        _daily_calls += 1
        return

    new_count = await increment_claude_daily_calls(today)
    if new_count > config.DAILY_CLAUDE_API_CAP:
        raise DailyCapExceededError(
            f"Daily Claude API cap of {config.DAILY_CLAUDE_API_CAP} reached"
        )


def _build_client_list(contacts: list) -> str:
    """Render the known-clients block for the system prompt.

    Accepts either Contact instances (production) or plain dicts (legacy/test
    fixtures); attribute access via getattr handles both without forcing every
    test fixture to wrap rows in Contact.
    """
    return "\n".join(
        f'- "{getattr(c, "client_id", None) or c["client_id"]}" → '
        f'{getattr(c, "display_name", None) or c["display_name"]}'
        for c in contacts
    )


def _strip_code_fence(text: str) -> str:
    """Remove a ```/```json markdown fence if Claude wrapped the JSON in one.

    The system prompt forbids markdown, but Haiku occasionally wraps anyway.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline == -1:
        return text
    inner = text[first_newline + 1 :].rstrip()
    if inner.endswith("```"):
        inner = inner[:-3]
    return inner.strip()


def _load_mock_response(text: str, contacts: list | None) -> LLMOutput:
    text_lower = text.lower()
    matched_fixture: pathlib.Path | None = None

    if contacts:
        for contact in contacts:
            cid = getattr(contact, "client_id", None) or contact["client_id"]
            display_name = (
                getattr(contact, "display_name", None) or contact["display_name"]
            )
            cid_lower = cid.lower()
            if (cid_lower in text_lower
                    or cid_lower.replace("_", " ") in text_lower
                    or display_name.lower() in text_lower):
                candidates = sorted(FIXTURES_DIR.glob(f"{cid}_*.json"))
                if candidates:
                    matched_fixture = candidates[0]
                    break

    if matched_fixture is None:
        fallback = FIXTURES_DIR / "unknown_client.json"
        if fallback.exists():
            matched_fixture = fallback

    if matched_fixture is None or not matched_fixture.exists():
        raise LLMParseError("No mock fixture found for this input")

    raw = json.loads(matched_fixture.read_text())
    try:
        return LLMOutput.model_validate(raw)
    except Exception as e:
        raise LLMValidationError(f"Mock fixture failed validation: {e}") from e


async def _call_anthropic_with_retry(system: str, text: str):
    """Call the Anthropic API with a single 3-second retry on transient errors.

    Per spec §7: auto-retry once after a 3s delay, then surface as LLMAPIError.
    """
    for attempt in (1, 2):
        try:
            return await _get_client().messages.create(
                model=_MODEL,
                max_tokens=1024,
                system=system,
                messages=[{"role": "user", "content": text}],
            )
        except anthropic.APIError as e:
            log.warning(
                "llm_parser.api_error",
                attempt=attempt,
                error_type=type(e).__name__,
                status=getattr(e, "status_code", None),
            )
            if attempt == 1:
                await asyncio.sleep(_RETRY_DELAY_SECONDS)
                continue
            raise LLMAPIError(str(e)) from e


async def parse_invoice_text(
    text: str,
    previous_data: dict | None = None,
    contacts: list | None = None,
    session_call_count: int = 0,
) -> LLMOutput:
    """Parse invoice text via Claude API (initial or correction mode).

    Raises DailyCapExceededError, SessionCapExceededError, LLMParseError, LLMValidationError.
    """
    today = date.today()

    if session_call_count >= config.SESSION_LLM_CALL_CAP:
        raise SessionCapExceededError(
            f"Session LLM cap of {config.SESSION_LLM_CALL_CAP} reached"
        )

    await _check_and_increment_daily(today)

    if config.MOCK_MODE:
        log.info("llm_parser.mock_mode", text_preview=text[:60])
        return _load_mock_response(text, contacts)

    contacts = contacts or []
    client_list = _build_client_list(contacts)
    today_str = today.strftime("%d/%m/%Y")

    if previous_data is None:
        system = (
            f"You are an invoice data extractor. Given a transcribed voice command, extract structured invoice data.\n\n"
            f"Today's date: {today_str} (timezone: HKT, Asia/Hong_Kong)\n\n"
            f"Known clients:\n{client_list}\n\n"
            f"Rules:\n"
            f"- Output ONLY valid JSON matching the schema below. No explanation, no markdown.\n"
            f"- Match the spoken client name to a known client_id. If unsure, set client_id to null.\n"
            f"- Convert all times to 24-hour format (HH:MM).\n"
            f"- Convert all dates to DD/MM/YYYY format. If no year is stated, use the current year.\n"
            f"- If the user mentions \"per hour\" or \"an hour\", set rate_type to \"hourly\".\n"
            f"- If the user mentions \"flat fee\" or just states a total, set rate_type to \"flat\".\n"
            f"- Set total to null — the backend will compute it.\n"
            f"- List any fields you could not extract in missing_fields.\n"
            f"- Do NOT guess or hallucinate values. If unsure, add the field to missing_fields.\n\n"
            f"Output schema:\n{_JSON_SCHEMA}"
        )
    else:
        system = (
            f"You are an invoice data corrector. The user is editing a previously parsed invoice.\n\n"
            f"Previous parsed data:\n{json.dumps(previous_data, indent=2)}\n\n"
            f"The user wants to make a correction. Apply their change to the previous data and output the "
            f"complete updated JSON. Do not discard unchanged fields.\n\n"
            f"Rules:\n"
            f"- Output ONLY the complete updated JSON. No explanation.\n"
            f"- Only change the fields the user explicitly mentions.\n"
            f"- If the user's correction is ambiguous, keep the previous value and add the ambiguous field to missing_fields.\n"
            f"- Set total to null — the backend will recompute it.\n\n"
            f"Output schema:\n{_JSON_SCHEMA}"
        )

    response = await _call_anthropic_with_retry(system, text)

    raw_text = response.content[0].text
    log.info("llm_parser.response", preview=raw_text[:120])

    try:
        data = json.loads(_strip_code_fence(raw_text))
    except json.JSONDecodeError as e:
        raise LLMParseError(f"LLM returned invalid JSON: {e}") from e

    try:
        return LLMOutput.model_validate(data)
    except Exception as e:
        raise LLMValidationError(f"LLM output failed schema validation: {e}") from e
