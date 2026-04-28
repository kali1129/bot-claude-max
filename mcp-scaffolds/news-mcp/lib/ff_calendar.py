"""ForexFactory weekly calendar scraper.

ForexFactory exposes a simple HTML calendar at /calendar?week=this. We parse
it best-effort; on any failure we return an empty list with the error so
the caller can degrade gracefully.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timezone, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

IMPACT_FROM_TITLE = {
    "High Impact Expected": "high",
    "Medium Impact Expected": "medium",
    "Low Impact Expected": "low",
    "Non-Economic": "low",
}


def _parse_target_date(s: str) -> date:
    s = (s or "today").lower().strip()
    today = datetime.now(timezone.utc).date()
    if s in ("today", ""):
        return today
    if s == "tomorrow":
        return today + timedelta(days=1)
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return today


async def fetch_calendar(target: str = "today", impact: str = "high") -> dict:
    """Returns {events, count, source, error?}."""
    target_date = _parse_target_date(target)
    url = "https://www.forexfactory.com/calendar?week=this"
    headers = {"User-Agent": os.environ.get("FF_USER_AGENT", DEFAULT_UA)}
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
            r = await c.get(url, headers=headers)
            r.raise_for_status()
    except (httpx.HTTPError, httpx.HTTPStatusError) as e:
        return {"events": [], "count": 0, "source": "forexfactory.com",
                "error": f"FETCH_FAILED: {e}"}

    soup = BeautifulSoup(r.text, "html.parser")
    rows = soup.select("tr.calendar__row, tr.calendar_row")
    events = []
    current_date = target_date

    for row in rows:
        date_cell = row.select_one(".calendar__date, .calendar-date")
        if date_cell and date_cell.get_text(strip=True):
            txt = date_cell.get_text(" ", strip=True)
            m = re.search(r"(\w{3})\s+(\d{1,2})", txt)
            if m:
                month_str, day = m.group(1), int(m.group(2))
                try:
                    parsed = datetime.strptime(
                        f"{month_str} {day} {target_date.year}", "%b %d %Y"
                    ).date()
                    current_date = parsed
                except ValueError:
                    pass

        impact_cell = row.select_one(".calendar__impact span, .impact span")
        if not impact_cell:
            continue
        title = impact_cell.get("title", "")
        ev_impact = None
        for k, v in IMPACT_FROM_TITLE.items():
            if k in title:
                ev_impact = v
                break
        if ev_impact is None:
            continue

        currency = (row.select_one(".calendar__currency") or row.select_one(".currency"))
        currency = currency.get_text(strip=True) if currency else ""

        time_cell = (row.select_one(".calendar__time") or row.select_one(".time"))
        time_str = time_cell.get_text(" ", strip=True) if time_cell else ""

        event_cell = (row.select_one(".calendar__event") or row.select_one(".event"))
        event_name = event_cell.get_text(" ", strip=True) if event_cell else ""

        actual = (row.select_one(".calendar__actual") or row.select_one(".actual"))
        forecast = (row.select_one(".calendar__forecast") or row.select_one(".forecast"))
        previous = (row.select_one(".calendar__previous") or row.select_one(".previous"))

        events.append({
            "date": current_date.isoformat(),
            "time_local": time_str,
            "currency": currency,
            "event": event_name,
            "impact": ev_impact,
            "actual":   actual.get_text(strip=True) if actual else None,
            "forecast": forecast.get_text(strip=True) if forecast else None,
            "previous": previous.get_text(strip=True) if previous else None,
        })

    if impact != "all":
        events = [e for e in events if e["impact"] == impact]
    events = [e for e in events if e["date"] == target_date.isoformat()]

    return {"events": events, "count": len(events), "source": "forexfactory.com"}
