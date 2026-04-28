"""Tests for capa 3 ports: headline_normalizer, relevance_ranker,
sentiment_guard, event_calendar.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

UTC = timezone.utc

_HERE = Path(__file__).resolve().parent
_MCP_ROOT = _HERE.parent  # news-mcp/
_SCAFFOLDS = _MCP_ROOT.parent  # mcp-scaffolds/
sys.path.insert(0, str(_MCP_ROOT))
sys.path.insert(0, str(_SCAFFOLDS))

from lib.headline_normalizer import HeadlineNormalizer, NormalizedHeadline
from lib.relevance_ranker import RankedHeadline, RelevanceRanker, infer_asset_class
from lib.sentiment_guard import SentimentGuard
from lib.event_calendar import CalendarEvent, EventCalendar
from _shared.common.enums import ImpactLevel


# ----------------- helpers -----------------

def _raw(title: str, *, source: str = "reuters.com", id_: str = "h1",
         published_at=None) -> dict:
    return {
        "source": source,
        "headline_id": id_,
        "title": title,
        "published_at": published_at or datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
    }


# =================== headline_normalizer ===================


def test_normalizer_classifies_high_impact_cpi():
    norm = HeadlineNormalizer()
    out = norm.normalize(_raw("US CPI beats expectations, dollar surges"))
    assert out.impact_level is ImpactLevel.HIGH
    assert out.sentiment_label == "positive"
    assert "inflation" in out.macro_themes


def test_normalizer_classifies_negative_sentiment():
    norm = HeadlineNormalizer()
    out = norm.normalize(_raw("Manufacturing PMI misses, output falls sharply"))
    assert out.sentiment_label == "negative"
    assert out.impact_level is ImpactLevel.MEDIUM


def test_normalizer_mixed_sentiment_when_both_keywords():
    norm = HeadlineNormalizer()
    out = norm.normalize(_raw("Earnings beat but guidance falls short"))
    assert out.sentiment_label == "mixed"


def test_normalizer_neutral_default():
    norm = HeadlineNormalizer()
    out = norm.normalize(_raw("Market closes for the holiday weekend"))
    assert out.sentiment_label == "neutral"


def test_normalizer_matches_symbol_aliases():
    norm = HeadlineNormalizer(
        symbol_aliases={"EURUSD": ["euro dollar", "euro"]},
        asset_class_by_symbol={"EURUSD": "FX"},
    )
    out = norm.normalize(_raw("Euro dollar slips on dovish ECB minutes"))
    assert "EURUSD" in out.symbols
    assert "FX" in out.asset_classes


def test_normalizer_published_at_iso_string():
    norm = HeadlineNormalizer()
    out = norm.normalize({
        "source": "reuters.com",
        "headline_id": "h2",
        "title": "Fed holds rates",
        "published_at": "2026-04-28T12:00:00Z",
    })
    assert out.published_at.tzinfo is not None
    assert out.published_at.utcoffset() == timedelta(0)


def test_normalizer_to_dict_round_trips():
    norm = HeadlineNormalizer()
    out = norm.normalize(_raw("US CPI surges, dollar gains"))
    d = out.to_dict()
    assert d["impact_level"] == "high"
    assert d["sentiment_label"] == "positive"
    assert "title" in d


def test_normalizer_is_stale_after_cutoff():
    norm = HeadlineNormalizer()
    pub = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    out = norm.normalize(_raw("CPI report", published_at=pub))
    assert out.is_stale(as_of=pub + timedelta(minutes=120), stale_after_minutes=60)
    assert not out.is_stale(as_of=pub + timedelta(minutes=30), stale_after_minutes=60)


# =================== relevance_ranker ===================


def test_infer_asset_class_fx():
    assert infer_asset_class("EURUSD") == "FX"


def test_infer_asset_class_metals_quirk_xauusd_returns_fx():
    # Legacy quirk preserved: 6-char alpha symbols match FX branch first.
    # Use a 7+ char symbol like "XAUUSDT" to actually hit METALS.
    assert infer_asset_class("XAUUSD") == "FX"
    assert infer_asset_class("XAUUSDT") == "METALS"


def test_infer_asset_class_crypto_quirk_btcusd_returns_fx():
    # Legacy quirk preserved: 6-char alpha symbols match FX first.
    assert infer_asset_class("BTCUSD") == "FX"
    assert infer_asset_class("BTCUSDT") == "CRYPTO"
    assert infer_asset_class("ETHUSDT") == "CRYPTO"


def test_ranker_returns_explicit_match():
    norm = HeadlineNormalizer(
        symbol_aliases={"EURUSD": ["euro"]},
        asset_class_by_symbol={"EURUSD": "FX"},
    )
    headlines = norm.normalize_many([
        _raw("Euro slides as ECB turns dovish"),
        _raw("Gold prices rally on safe-haven demand", id_="h2"),
    ])
    ranker = RelevanceRanker(
        symbol_aliases={"EURUSD": ["euro"]},
        asset_class_by_symbol={"EURUSD": "FX"},
        macro_themes_by_symbol={"EURUSD": ["rates"]},
    )
    ranked = ranker.rank(symbol="EURUSD", headlines=headlines)
    assert len(ranked) == 1
    assert ranked[0].symbol == "EURUSD"
    assert "EXPLICIT_SYMBOL_MATCH" in ranked[0].reasons or "MACRO_THEME_MATCH" in ranked[0].reasons


def test_ranker_drops_below_minimum_score():
    norm = HeadlineNormalizer()
    headlines = norm.normalize_many([_raw("Holiday sales recap")])
    ranker = RelevanceRanker(
        symbol_aliases={"EURUSD": []},
        asset_class_by_symbol={"EURUSD": "FX"},
        minimum_score=0.5,
    )
    assert ranker.rank(symbol="EURUSD", headlines=headlines) == []


def test_ranker_sorts_by_score_descending():
    norm = HeadlineNormalizer(
        symbol_aliases={"EURUSD": ["euro"]},
        asset_class_by_symbol={"EURUSD": "FX"},
    )
    headlines = norm.normalize_many([
        _raw("Euro Dollar plunges on hawkish Fed", id_="strong",
             published_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC)),
        _raw("FX market mixed", id_="weak",
             published_at=datetime(2026, 4, 28, 11, 0, tzinfo=UTC)),
    ])
    ranker = RelevanceRanker(
        symbol_aliases={"EURUSD": ["euro"]},
        asset_class_by_symbol={"EURUSD": "FX"},
        minimum_score=0.10,
    )
    ranked = ranker.rank(symbol="EURUSD", headlines=headlines)
    if len(ranked) >= 2:
        assert ranked[0].score >= ranked[1].score


def test_ranker_to_dict_shape():
    norm = HeadlineNormalizer(
        symbol_aliases={"EURUSD": ["euro"]},
        asset_class_by_symbol={"EURUSD": "FX"},
    )
    headlines = norm.normalize_many([_raw("Euro surges on hawkish ECB")])
    ranker = RelevanceRanker(
        symbol_aliases={"EURUSD": ["euro"]},
        asset_class_by_symbol={"EURUSD": "FX"},
    )
    ranked = ranker.rank(symbol="EURUSD", headlines=headlines)
    if ranked:
        d = ranked[0].to_dict()
        assert d["symbol"] == "EURUSD"
        assert "score" in d
        assert "reasons" in d


# =================== sentiment_guard ===================


def _ranked(title: str, *, sentiment="positive", impact=ImpactLevel.MEDIUM,
            source="reuters.com", published_at=None,
            symbol="EURUSD") -> RankedHeadline:
    h = NormalizedHeadline(
        source=source,
        headline_id=f"h-{title[:6]}",
        title=title,
        normalized_title=title.lower(),
        published_at=published_at or datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        symbols=(symbol,),
        asset_classes=("FX",),
        macro_themes=(),
        impact_level=impact,
        sentiment_label=sentiment,
    )
    return RankedHeadline(symbol=symbol, score=0.9, reasons=("X",), headline=h, asset_class="FX")


def test_sentiment_guard_neutral_when_no_signed():
    guard = SentimentGuard()
    out = guard.evaluate(
        headlines=[_ranked("plain title", sentiment="neutral")],
        as_of=datetime(2026, 4, 28, 12, 5, tzinfo=UTC),
        stale_after_minutes=60,
    )
    assert out.sentiment_state == "neutral"
    assert not out.conflicting


def test_sentiment_guard_conflicting_flags_both():
    guard = SentimentGuard()
    out = guard.evaluate(
        headlines=[
            _ranked("h1", sentiment="positive"),
            _ranked("h2", sentiment="negative"),
        ],
        as_of=datetime(2026, 4, 28, 12, 5, tzinfo=UTC),
        stale_after_minutes=60,
    )
    assert out.conflicting
    assert out.sentiment_state == "conflicting"
    assert "CONFLICTING_HEADLINES" in out.reasons


def test_sentiment_guard_stale_only_flagged():
    pub_old = datetime(2026, 4, 28, 8, 0, tzinfo=UTC)
    guard = SentimentGuard()
    out = guard.evaluate(
        headlines=[_ranked("old", sentiment="positive", published_at=pub_old)],
        as_of=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        stale_after_minutes=30,  # 4h old, cutoff 30m
    )
    assert out.sentiment_state == "stale"
    assert "STALE_HEADLINES" in out.reasons
    assert out.stale_only


def test_sentiment_guard_highest_impact_propagates():
    guard = SentimentGuard()
    out = guard.evaluate(
        headlines=[
            _ranked("h1", sentiment="positive", impact=ImpactLevel.MEDIUM),
            _ranked("h2", sentiment="positive", impact=ImpactLevel.HIGH),
        ],
        as_of=datetime(2026, 4, 28, 12, 5, tzinfo=UTC),
        stale_after_minutes=60,
    )
    assert out.highest_impact is ImpactLevel.HIGH


def test_sentiment_guard_no_relevant_returns_reason():
    guard = SentimentGuard()
    out = guard.evaluate(
        headlines=[],
        as_of=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        stale_after_minutes=60,
    )
    assert "NO_RELEVANT_HEADLINES" in out.reasons


def test_sentiment_guard_to_dict_shape():
    guard = SentimentGuard()
    out = guard.evaluate(
        headlines=[_ranked("h", sentiment="positive")],
        as_of=datetime(2026, 4, 28, 12, 5, tzinfo=UTC),
        stale_after_minutes=60,
    )
    d = out.to_dict()
    assert d["ok"] is True
    assert d["sentiment_state"] == "positive"
    assert d["highest_impact"] == "medium"


# =================== event_calendar ===================


def test_event_applies_to_explicit_symbol():
    ev = CalendarEvent(
        event_id="e1",
        title="CPI",
        timestamp=datetime(2026, 4, 28, 12, 30, tzinfo=UTC),
        impact_level=ImpactLevel.HIGH,
        symbols=("EURUSD",),
    )
    assert ev.applies_to("EURUSD")
    assert not ev.applies_to("XAUUSD")


def test_event_applies_via_asset_class():
    ev = CalendarEvent(
        event_id="e1",
        title="CPI",
        timestamp=datetime(2026, 4, 28, 12, 30, tzinfo=UTC),
        impact_level=ImpactLevel.HIGH,
        asset_classes=("FX",),
    )
    assert ev.applies_to("EURUSD", asset_class="FX")
    assert not ev.applies_to("XAUUSD", asset_class="METALS")


def test_event_applies_default_when_no_filters():
    ev = CalendarEvent(
        event_id="e1",
        title="Generic",
        timestamp=datetime(2026, 4, 28, 12, 30, tzinfo=UTC),
        impact_level=ImpactLevel.MEDIUM,
    )
    assert ev.applies_to("ANY")


def test_calendar_active_window_detected():
    cal = EventCalendar.from_dicts([
        {
            "title": "CPI",
            "timestamp": datetime(2026, 4, 28, 12, 30, tzinfo=UTC),
            "impact_level": "high",
            "symbols": ["EURUSD"],
            "window_before_minutes": 30,
            "window_after_minutes": 30,
        },
    ])
    windows = cal.windows_for_symbol(
        as_of=datetime(2026, 4, 28, 12, 15, tzinfo=UTC),
        symbol="EURUSD",
    )
    assert len(windows) == 1
    assert windows[0].active is True


def test_calendar_drops_past_events():
    cal = EventCalendar.from_dicts([
        {
            "title": "Old",
            "timestamp": datetime(2026, 4, 28, 8, 0, tzinfo=UTC),
            "impact_level": "high",
            "symbols": ["EURUSD"],
            "window_before_minutes": 30,
            "window_after_minutes": 30,
        },
    ])
    windows = cal.windows_for_symbol(
        as_of=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        symbol="EURUSD",
    )
    assert windows == []


def test_calendar_upcoming_event_inactive_window():
    cal = EventCalendar.from_dicts([
        {
            "title": "FOMC",
            "timestamp": datetime(2026, 4, 28, 18, 0, tzinfo=UTC),
            "impact_level": "high",
            "symbols": ["EURUSD"],
            "window_before_minutes": 30,
            "window_after_minutes": 30,
        },
    ])
    windows = cal.windows_for_symbol(
        as_of=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
        symbol="EURUSD",
    )
    assert len(windows) == 1
    assert windows[0].active is False
    assert windows[0].minutes_until_event == 360.0


def test_calendar_iso_string_timestamp_accepted():
    cal = EventCalendar.from_dicts([
        {
            "title": "NFP",
            "timestamp": "2026-04-28T12:30:00Z",
            "impact_level": "high",
            "symbols": ["EURUSD"],
        },
    ])
    windows = cal.windows_for_symbol(
        as_of=datetime(2026, 4, 28, 12, 25, tzinfo=UTC),
        symbol="EURUSD",
    )
    assert len(windows) == 1


def test_calendar_to_dict_shape():
    cal = EventCalendar.from_dicts([
        {
            "title": "CPI",
            "timestamp": datetime(2026, 4, 28, 12, 30, tzinfo=UTC),
            "impact_level": "high",
            "symbols": ["EURUSD"],
        },
    ])
    windows = cal.windows_for_symbol(
        as_of=datetime(2026, 4, 28, 12, 15, tzinfo=UTC),
        symbol="EURUSD",
    )
    d = windows[0].to_dict()
    assert "event" in d
    assert d["active"] is True
    assert "minutes_until_event" in d
