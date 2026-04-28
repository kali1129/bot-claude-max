"""Decision engine tests — pure function, no network."""
from datetime import datetime, timedelta, timezone

from lib.decision import is_tradeable_now


def _at(minutes_from_now: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes_from_now)).isoformat()


def test_blackout_30min_before_high_event():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[{
            "currency": "USD", "impact": "high",
            "event": "Core CPI", "time_utc": _at(20),
        }],
        fresh_news=[],
    )
    assert res["tradeable"] is False
    assert res["reason"] == "BLACKOUT"


def test_blackout_15min_after_high_event():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[{
            "currency": "USD", "impact": "high",
            "event": "Core CPI", "time_utc": _at(-15),
        }],
        fresh_news=[],
    )
    assert res["tradeable"] is False


def test_far_event_does_not_block():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[{
            "currency": "USD", "impact": "high",
            "event": "Core CPI", "time_utc": _at(120),
        }],
        fresh_news=[],
    )
    assert res["tradeable"] is True
    assert res.get("normal") is True


def test_other_currency_does_not_block():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[{
            "currency": "JPY", "impact": "high",
            "event": "BoJ", "time_utc": _at(10),
        }],
        fresh_news=[],
    )
    assert res["tradeable"] is True


def test_low_impact_event_ignored():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[{
            "currency": "USD", "impact": "low",
            "event": "minor", "time_utc": _at(5),
        }],
        fresh_news=[],
    )
    assert res["tradeable"] is True


def test_fresh_news_under_5min_blocks():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[],
        fresh_news=[{"age_minutes": 2, "relevance_score": 80,
                     "title": "Fed surprise"}],
    )
    assert res["tradeable"] is False
    assert res["reason"] == "FRESH_NEWS"


def test_recent_news_5to30_caution():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[],
        fresh_news=[{"age_minutes": 15, "relevance_score": 80,
                     "title": "ECB"}],
    )
    assert res["tradeable"] is True
    assert res.get("caution") == "fresh-news"


def test_old_news_30to90_fade_only():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[],
        fresh_news=[{"age_minutes": 50, "relevance_score": 80,
                     "title": "ECB"}],
    )
    assert res["tradeable"] is True
    assert res.get("caution") == "fade-only"


def test_low_relevance_news_ignored():
    res = is_tradeable_now(
        "EURUSD", ["EUR", "USD"],
        calendar_events=[],
        fresh_news=[{"age_minutes": 2, "relevance_score": 30,
                     "title": "celebrity gossip"}],
    )
    assert res["tradeable"] is True
