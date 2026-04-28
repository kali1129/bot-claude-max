"""news-mcp v1.1.0 — Economic calendar + news + capa-3 ports.

Original (v1.0): ForexFactory calendar + Finnhub/NewsAPI news. Always
returns deterministic dicts; degrades gracefully when API keys are
missing.

Capa 3 additions (legacy ports from xm-mt5-trading-platform/src/news/):
- normalize_headlines: deterministic structuring (symbols, asset_classes,
  macro_themes, impact, sentiment).
- rank_headlines: per-symbol relevance scoring.
- sentiment_guard_check: stale/conflicting sentiment detection.
- event_windows_for_symbol: pre-/post-event gating windows.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List

import httpx
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

load_dotenv(HERE / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("news-mcp")

from mcp.server.fastmcp import FastMCP  # noqa: E402

from lib.ff_calendar import fetch_calendar  # noqa: E402
from lib.symbol_map import currencies_for  # noqa: E402
from lib.relevance import score_headline  # noqa: E402
from lib.decision import is_tradeable_now as _decide  # noqa: E402

# Capa 3 ports
from lib.headline_normalizer import HeadlineNormalizer  # noqa: E402
from lib.relevance_ranker import RelevanceRanker  # noqa: E402
from lib.sentiment_guard import SentimentGuard  # noqa: E402
from lib.event_calendar import EventCalendar  # noqa: E402

__version__ = "1.1.0"

ALLOWED_SOURCES = {
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com",
    "cnbc.com", "marketwatch.com", "investing.com", "forexlive.com",
}

mcp = FastMCP("news")


def _has(key: str) -> bool:
    val = os.environ.get(key, "").strip()
    return bool(val) and val not in {"none", "null", "<your-key>"}


def _domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).hostname or ""
    except Exception:
        return ""


# --------------------------- core tools (original) ---------------------------


@mcp.tool()
def health() -> dict:
    return {
        "version": __version__,
        "finnhub": _has("FINNHUB_API_KEY"),
        "newsapi": _has("NEWSAPI_KEY"),
        "calendar_source": "forexfactory.com",
    }


@mcp.tool()
async def get_economic_calendar(date: str = "today", impact: str = "high") -> dict:
    """Calendar events from ForexFactory. impact in {high, medium, low, all}."""
    return await fetch_calendar(date, impact)


@mcp.tool()
async def get_news(query: str, since_minutes: int = 60, max_items: int = 10) -> dict:
    """News from Finnhub (preferred) -> NewsAPI (fallback). Whitelisted sources only."""
    items = []
    err = None

    if _has("FINNHUB_API_KEY"):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.get(
                    "https://finnhub.io/api/v1/news",
                    params={
                        "category": "general",
                        "token": os.environ["FINNHUB_API_KEY"],
                    },
                )
                resp.raise_for_status()
                for n in resp.json():
                    url = n.get("url", "")
                    src = _domain(url)
                    if src not in ALLOWED_SOURCES:
                        continue
                    items.append({
                        "title": n.get("headline", ""),
                        "source": src,
                        "url": url,
                        "summary": n.get("summary", "")[:300],
                        "published_at_utc": datetime.fromtimestamp(
                            int(n.get("datetime", 0)), tz=timezone.utc
                        ).isoformat() if n.get("datetime") else None,
                    })
        except (httpx.HTTPError, ValueError) as e:
            err = f"finnhub: {e}"

    if not items and _has("NEWSAPI_KEY"):
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                resp = await c.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": query,
                        "sortBy": "publishedAt",
                        "language": "en",
                        "apiKey": os.environ["NEWSAPI_KEY"],
                    },
                )
                resp.raise_for_status()
                for n in resp.json().get("articles", []):
                    src = _domain(n.get("url", ""))
                    if src not in ALLOWED_SOURCES:
                        continue
                    items.append({
                        "title": n.get("title", ""),
                        "source": src,
                        "url": n.get("url", ""),
                        "summary": (n.get("description") or "")[:300],
                        "published_at_utc": n.get("publishedAt"),
                    })
        except (httpx.HTTPError, ValueError) as e:
            err = (err + " | " if err else "") + f"newsapi: {e}"

    if not items and not _has("FINNHUB_API_KEY") and not _has("NEWSAPI_KEY"):
        return {
            "ok": False, "reason": "NO_API_KEY",
            "detail": "Set FINNHUB_API_KEY or NEWSAPI_KEY in .env to enable news.",
            "news": [],
        }

    now = datetime.now(timezone.utc)
    out = []
    for it in items[:max_items]:
        score = score_headline(it["title"], query)["score"]
        age = None
        if it.get("published_at_utc"):
            try:
                pub = datetime.fromisoformat(it["published_at_utc"].replace("Z", "+00:00"))
                age = int((now - pub).total_seconds() / 60.0)
            except ValueError:
                pass
        if age is not None and age > since_minutes:
            continue
        out.append({**it, "relevance_score": score, "age_minutes": age})

    return {"news": out, "count": len(out), "error": err}


@mcp.tool()
async def is_tradeable_now(symbol: str) -> dict:
    """Verdict: tradeable / blackout / caution. Pulls calendar + recent news."""
    cur_list = currencies_for(symbol)
    if not cur_list:
        return {
            "symbol": symbol,
            "tradeable": True,
            "reason": "UNKNOWN_SYMBOL - defaulting to tradeable",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    calendar = await fetch_calendar("today", "high")
    news_payload = await get_news(symbol, since_minutes=120, max_items=20)
    news_items = news_payload.get("news", []) if isinstance(news_payload, dict) else []

    return _decide(
        symbol=symbol,
        currencies=cur_list,
        calendar_events=calendar.get("events", []),
        fresh_news=news_items,
    )


@mcp.tool()
def news_relevance_score(headline: str, symbol: str) -> dict:
    return score_headline(headline, symbol)


# ============================================================================
# Capa 3 (legacy ports)
# ============================================================================


@mcp.tool()
def normalize_headlines(
    headlines: List[dict],
    symbol_aliases: dict | None = None,
    asset_class_by_symbol: dict | None = None,
) -> dict:
    """Structure raw headlines into deterministic records.

    Each input headline needs at least: title, source, published_at, and
    either headline_id or id. Returns NormalizedHeadline dicts with detected
    symbols, asset_classes, macro_themes, impact_level, and sentiment_label.
    """
    norm = HeadlineNormalizer(
        symbol_aliases=symbol_aliases,
        asset_class_by_symbol=asset_class_by_symbol,
    )
    out = norm.normalize_many(headlines)
    return {"ok": True, "count": len(out), "headlines": [h.to_dict() for h in out]}


@mcp.tool()
def rank_headlines(
    symbol: str,
    headlines: List[dict],
    symbol_aliases: dict | None = None,
    asset_class_by_symbol: dict | None = None,
    macro_themes_by_symbol: dict | None = None,
    minimum_score: float = 0.35,
) -> dict:
    """Normalize + rank headlines by relevance for one symbol."""
    norm = HeadlineNormalizer(
        symbol_aliases=symbol_aliases,
        asset_class_by_symbol=asset_class_by_symbol,
    )
    normalized = norm.normalize_many(headlines)
    ranker = RelevanceRanker(
        symbol_aliases=symbol_aliases,
        asset_class_by_symbol=asset_class_by_symbol,
        macro_themes_by_symbol=macro_themes_by_symbol,
        minimum_score=minimum_score,
    )
    ranked = ranker.rank(symbol=symbol, headlines=normalized)
    return {
        "ok": True,
        "symbol": symbol.upper(),
        "count": len(ranked),
        "ranked": [r.to_dict() for r in ranked],
    }


@mcp.tool()
def sentiment_guard_check(
    symbol: str,
    headlines: List[dict],
    symbol_aliases: dict | None = None,
    asset_class_by_symbol: dict | None = None,
    macro_themes_by_symbol: dict | None = None,
    stale_after_minutes: int = 60,
    minimum_score: float = 0.35,
    as_of: str | None = None,
) -> dict:
    """Detect stale or conflicting sentiment for a symbol."""
    norm = HeadlineNormalizer(
        symbol_aliases=symbol_aliases,
        asset_class_by_symbol=asset_class_by_symbol,
    )
    normalized = norm.normalize_many(headlines)
    ranker = RelevanceRanker(
        symbol_aliases=symbol_aliases,
        asset_class_by_symbol=asset_class_by_symbol,
        macro_themes_by_symbol=macro_themes_by_symbol,
        minimum_score=minimum_score,
    )
    ranked = ranker.rank(symbol=symbol, headlines=normalized)

    if as_of is None:
        as_of_dt = datetime.now(timezone.utc)
    else:
        try:
            as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            if as_of_dt.tzinfo is None:
                as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return {"ok": False, "reason": "INVALID_AS_OF", "detail": as_of}

    guard = SentimentGuard()
    result = guard.evaluate(
        headlines=ranked,
        as_of=as_of_dt,
        stale_after_minutes=stale_after_minutes,
    )
    out = result.to_dict()
    out["symbol"] = symbol.upper()
    return out


@mcp.tool()
def event_windows_for_symbol(
    symbol: str,
    events: List[dict],
    asset_class: str | None = None,
    as_of: str | None = None,
    default_before_minutes: int = 30,
    default_after_minutes: int = 30,
) -> dict:
    """Compute active and upcoming gating windows for a symbol.

    Each event dict needs: title, timestamp, impact_level (or impact).
    """
    if as_of is None:
        as_of_dt = datetime.now(timezone.utc)
    else:
        try:
            as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            if as_of_dt.tzinfo is None:
                as_of_dt = as_of_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return {"ok": False, "reason": "INVALID_AS_OF", "detail": as_of}

    try:
        cal = EventCalendar.from_dicts(
            events,
            default_before_minutes=default_before_minutes,
            default_after_minutes=default_after_minutes,
        )
    except (ValueError, TypeError) as exc:
        return {"ok": False, "reason": "INVALID_EVENT", "detail": str(exc)}

    windows = cal.windows_for_symbol(
        as_of=as_of_dt, symbol=symbol, asset_class=asset_class
    )
    return {
        "ok": True,
        "symbol": symbol.upper(),
        "asset_class": asset_class.upper() if asset_class else None,
        "as_of": as_of_dt.isoformat(),
        "count": len(windows),
        "windows": [w.to_dict() for w in windows],
    }


if __name__ == "__main__":
    log.info(
        "news-mcp v%s starting (finnhub=%s newsapi=%s)",
        __version__, _has("FINNHUB_API_KEY"), _has("NEWSAPI_KEY"),
    )
    mcp.run()
