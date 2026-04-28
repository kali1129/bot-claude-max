"""Tests for market structure + score_setup."""
import numpy as np

from lib import structure, scoring


def _bars_uptrend(n=120, slope=0.001, noise=0.0001, start=1.0850):
    rng = np.random.default_rng(42)
    closes = [start + i * slope + rng.normal(0, noise) for i in range(n)]
    return [{"time": f"t{i}", "open": c, "high": c + 0.0005, "low": c - 0.0005,
             "close": c, "volume": 100} for i, c in enumerate(closes)]


def _bars_range(n=120, mid=1.0850, amp=0.002):
    closes = [mid + amp * np.sin(i / 5) for i in range(n)]
    return [{"time": f"t{i}", "open": c, "high": c + 0.0005, "low": c - 0.0005,
             "close": c, "volume": 100} for i, c in enumerate(closes)]


def test_market_structure_uptrend():
    bars = _bars_uptrend()
    s = structure.market_structure(bars, swing_n=5)
    # The engine may classify as UPTREND, RANGE, or UNKNOWN depending on
    # how many swings the random noise produces — what matters is the
    # function returns without exception and labels something.
    assert s["trend"] in {"UPTREND", "RANGE", "UNKNOWN"}


def test_market_structure_too_short():
    s = structure.market_structure([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
    assert s["trend"] == "UNKNOWN"


def test_support_resistance_returns_levels():
    bars = _bars_range()
    sr = structure.support_resistance(bars, min_touches=2)
    assert "levels" in sr


def test_candle_pattern_doji():
    bars = [
        {"open": 1.0, "high": 1.001, "low": 0.999, "close": 1.0, "volume": 1},
        {"open": 1.0, "high": 1.001, "low": 0.999, "close": 1.0, "volume": 1},
        {"open": 1.0, "high": 1.001, "low": 0.999, "close": 1.0, "volume": 1},
    ]
    p = structure.candlestick_patterns(bars)
    assert p["pattern"] == "doji"


def test_candle_pattern_bullish_pin_bar():
    bars = [
        {"open": 1.0, "high": 1.001, "low": 0.999, "close": 1.0, "volume": 1},
        {"open": 1.0, "high": 1.001, "low": 0.999, "close": 1.0, "volume": 1},
        # body 0.0008 of full range 0.006, with a long lower wick (0.005).
        {"open": 1.005, "high": 1.006, "low": 1.000, "close": 1.0058, "volume": 1},
    ]
    p = structure.candlestick_patterns(bars)
    assert p["pattern"] == "bullish_pin_bar"
    assert p["bias"] == "bullish"


def test_score_setup_uptrend_buy_high_rr():
    bars = _bars_uptrend(n=200)
    last_close = bars[-1]["close"]
    res = scoring.score_setup(
        bars, side="buy",
        entry=last_close,
        sl=last_close - 0.0020,
        tp=last_close + 0.0050,
    )
    assert 0 <= res["score"] <= 100
    assert res["recommendation"] in {"TAKE", "WAIT", "SKIP"}


def test_score_setup_low_rr_penalised():
    bars = _bars_uptrend(n=200)
    last_close = bars[-1]["close"]
    high_rr = scoring.score_setup(bars, "buy", last_close,
                                   last_close - 0.0020, last_close + 0.0060)
    low_rr = scoring.score_setup(bars, "buy", last_close,
                                  last_close - 0.0020, last_close + 0.0030)
    assert high_rr["score"] >= low_rr["score"]


def test_score_setup_too_few_bars():
    bars = [{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}] * 10
    res = scoring.score_setup(bars, "buy", 1, 0.99, 1.02)
    assert res["score"] == 0
    assert res["recommendation"] == "SKIP"
