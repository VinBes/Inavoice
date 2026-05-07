import asyncio
from datetime import date

from db.client import get_client


async def increment_claude_daily_calls(today: date) -> int:
    """Atomically increment today's Claude API call counter and return the new value."""

    def _sync() -> int:
        return get_client().rpc(
            "increment_claude_daily_calls", {"p_date": today.isoformat()}
        ).execute().data

    return await asyncio.to_thread(_sync)
