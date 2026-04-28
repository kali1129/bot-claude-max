"""Auto-reset the daily counters at 00:00 UTC."""
from __future__ import annotations

from datetime import datetime, timezone

from . import state_manager as sm


def maybe_reset(state: dict) -> dict:
    today = datetime.now(timezone.utc).date().isoformat()
    if state.get("last_reset_date") == today:
        return state
    # Archive yesterday's deals to deals.jsonl, then reset counters.
    for d in state.get("deals_today", []):
        sm.append_history(d)
    state["starting_balance_today"] = state.get("current_equity", state["starting_balance_today"])
    state["deals_today"] = []
    state["consecutive_losses"] = 0
    state["locked_until_utc"] = None
    state["last_reset_date"] = today
    return state


def next_day_utc_iso() -> str:
    """Returns the next 00:00 UTC as ISO string (used for lockouts)."""
    now = datetime.now(timezone.utc)
    tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = tomorrow.replace(day=now.day) + (datetime.fromtimestamp(86_400, tz=timezone.utc) - datetime.fromtimestamp(0, tz=timezone.utc))
    # Simpler: add one day.
    from datetime import timedelta
    return (now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat()
