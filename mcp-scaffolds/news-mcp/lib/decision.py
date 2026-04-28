"""is_tradeable_now decision engine. Pure function; takes data + clock."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Dict


def is_tradeable_now(
    symbol: str,
    currencies: List[str],
    calendar_events: List[Dict],
    fresh_news: List[Dict],
    now_utc: datetime = None,
) -> dict:
    """Evaluates blackout rules and returns a verdict.

    Rules (in order):
      1. HIGH-impact event for the symbol's currency in ±30 min → BLACKOUT
      2. Fresh news (<5 min, relevance ≥70) → BLACKOUT
      3. Recent news (5..30 min, relevance ≥70) → caution: fresh-news
      4. Older news (30..90 min, relevance ≥70) → caution: fade-only
      5. Otherwise → tradeable + normal
    """
    now = now_utc or datetime.now(timezone.utc)
    cur_set = {c.upper() for c in currencies}

    # Rule 1: HIGH-impact ±30 min
    for ev in calendar_events or []:
        if ev.get("impact") != "high":
            continue
        if ev.get("currency", "").upper() not in cur_set:
            continue
        ev_time = ev.get("time_utc")
        if not ev_time:
            continue
        try:
            evt_dt = datetime.fromisoformat(ev_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        delta_min = abs((evt_dt - now).total_seconds() / 60.0)
        if delta_min <= 30:
            return {
                "symbol": symbol,
                "tradeable": False,
                "reason": "BLACKOUT",
                "blocker_event": ev,
                "checked_at_utc": now.isoformat(),
            }

    # Rules 2..4: news age
    for n in fresh_news or []:
        score = n.get("relevance_score", 0)
        if score < 70:
            continue
        age = n.get("age_minutes", 9999)
        if age < 5:
            return {
                "symbol": symbol,
                "tradeable": False,
                "reason": "FRESH_NEWS",
                "blocker_news": n,
                "checked_at_utc": now.isoformat(),
            }
        if 5 <= age < 30:
            return {
                "symbol": symbol,
                "tradeable": True,
                "caution": "fresh-news",
                "fresh_news": n,
                "checked_at_utc": now.isoformat(),
            }
        if 30 <= age < 90:
            return {
                "symbol": symbol,
                "tradeable": True,
                "caution": "fade-only",
                "recent_news": n,
                "checked_at_utc": now.isoformat(),
            }

    return {
        "symbol": symbol,
        "tradeable": True,
        "normal": True,
        "checked_at_utc": now.isoformat(),
    }
