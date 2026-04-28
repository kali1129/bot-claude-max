"""Tests for the strategies + filter + feature_pipeline ports.

Smoke + correctness for ema_rsi_trend and breakout_volatility on synthetic
OHLCV. Validates: pipeline produces a fresh snapshot for sufficient bars,
strategies emit the expected direction on monotonic synthetic series, and
the session filter blocks weekends/late hours correctly.
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path

import pytest

# Make analysis-mcp/lib and the parent _shared importable
_HERE = Path(__file__).resolve().parent
_MCP_ROOT = _HERE.parent  # analysis-mcp/
_SCAFFOLDS = _MCP_ROOT.parent  # mcp-scaffolds/
sys.path.insert(0, str(_MCP_ROOT))
sys.path.insert(0, str(_SCAFFOLDS))

from lib.feature_pipeline import build_snapshot, evaluate_strategy_on_ohlcv
from lib.filters import FilterSettings, SessionFilter, apply_session_filter
from lib.strategies import (
    EMARSITrendStrategy,
    BreakoutVolatilityStrategy,
    StrategyDirection,
    list_strategies,
)
from lib.strategies.base import FeatureSnapshot


def _bars_from_closes(
    closes: list[float],
    *,
    start: datetime | None = None,
    minutes: int = 1,
    spread: float = 1.0,
) -> list[dict]:
    """Build synthetic OHLCV from a list of closes.

    open = previous close (or first close), high/low = close ± 0.0005*close,
    timestamp progresses by `minutes` per bar.
    """
    if start is None:
        # Tuesday 09:00 UTC = LONDON session
        start = datetime(2026, 4, 28, 9, 0, tzinfo=UTC)
    bars: list[dict] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        h = max(o, c) * (1.0 + 0.0008)
        l = min(o, c) * (1.0 - 0.0008)
        ts = (start + timedelta(minutes=i * minutes)).isoformat().replace("+00:00", "Z")
        bars.append({
            "time": ts,
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "spread": spread,
        })
        prev = c
    return bars


# ----- pipeline -----

def test_build_snapshot_short_input_is_not_fresh():
    bars = _bars_from_closes([100.0, 100.5, 101.0])
    snap = build_snapshot(bars)
    assert isinstance(snap, FeatureSnapshot)
    assert not snap.is_fresh


def test_build_snapshot_uptrend_produces_finite_features():
    closes = [100.0 + i * 0.2 for i in range(60)]
    bars = _bars_from_closes(closes)
    snap = build_snapshot(bars)
    assert snap.is_fresh
    assert math.isfinite(snap.values["fast_ema"])
    assert math.isfinite(snap.values["slow_ema"])
    assert math.isfinite(snap.values["rsi"])
    assert math.isfinite(snap.values["atr"])
    assert math.isfinite(snap.values["atr_pct"])
    assert snap.values["fast_ema"] > snap.values["slow_ema"]  # uptrend
    assert snap.labels["session"] == "LONDON"


def test_build_snapshot_downtrend_fast_ema_below_slow():
    closes = [100.0 - i * 0.15 for i in range(60)]
    bars = _bars_from_closes(closes)
    snap = build_snapshot(bars)
    assert snap.is_fresh
    assert snap.values["fast_ema"] < snap.values["slow_ema"]


# ----- strategies / registry -----

def test_list_strategies_contains_both():
    names = list_strategies()
    assert "ema_rsi_trend" in names
    assert "breakout_volatility" in names


def test_ema_rsi_trend_long_on_uptrend():
    # Strong uptrend: closes rise consistently, RSI above 55, ATR present.
    closes = [100.0 + i * 0.5 for i in range(80)]
    bars = _bars_from_closes(closes)
    out = evaluate_strategy_on_ohlcv(
        bars,
        "ema_rsi_trend",
        config={"min_atr_pct": 0.0001},  # let the synthetic series pass the ATR gate
    )
    assert out["ok"] is True
    assert out["direction"] == StrategyDirection.LONG.value, out


def test_ema_rsi_trend_short_on_downtrend():
    closes = [200.0 - i * 0.5 for i in range(80)]
    bars = _bars_from_closes(closes)
    out = evaluate_strategy_on_ohlcv(
        bars,
        "ema_rsi_trend",
        config={"min_atr_pct": 0.0001},
    )
    assert out["ok"] is True
    assert out["direction"] == StrategyDirection.SHORT.value, out


def test_ema_rsi_trend_session_block_on_weekend():
    closes = [100.0 + i * 0.5 for i in range(80)]
    # Saturday at 12:00 UTC
    bars = _bars_from_closes(closes, start=datetime(2026, 4, 25, 12, 0, tzinfo=UTC))
    out = evaluate_strategy_on_ohlcv(bars, "ema_rsi_trend")
    assert out["direction"] == StrategyDirection.FLAT.value
    assert "SESSION_BLOCKED" in out["rationale_codes"]


def test_ema_rsi_trend_unknown_strategy():
    bars = _bars_from_closes([100.0 + i * 0.5 for i in range(40)])
    out = evaluate_strategy_on_ohlcv(bars, "does_not_exist")
    assert out["ok"] is False
    assert out["reason"] == "UNKNOWN_STRATEGY"


def test_breakout_volatility_returns_decision_shape():
    # Doesn't matter if FLAT — verifies the dict shape and that the strategy
    # doesn't crash on a benign input.
    closes = [100.0 + (i % 5) * 0.05 for i in range(80)]
    bars = _bars_from_closes(closes)
    out = evaluate_strategy_on_ohlcv(bars, "breakout_volatility")
    assert out["ok"] is True
    assert out["strategy"] == "breakout_volatility"
    assert out["direction"] in {"LONG", "SHORT", "FLAT"}
    assert isinstance(out["rationale_codes"], list)
    assert 0.0 <= out["score"] <= 1.0


# ----- session filter -----

def test_session_filter_pass_in_window():
    bar = {
        "time": "2026-04-28T10:00:00Z",  # Tue, LONDON session
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "spread": 5.0,
    }
    out = apply_session_filter(bar)
    assert out["passed"] is True
    assert out["reason"] == "OK"


def test_session_filter_blocks_weekend():
    bar = {
        "time": "2026-04-25T12:00:00Z",  # Saturday
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "spread": 5.0,
    }
    out = apply_session_filter(bar)
    assert out["passed"] is False
    assert out["reason"] == "WEEKDAY_BLOCKED"


def test_session_filter_blocks_off_hours():
    bar = {
        "time": "2026-04-28T03:00:00Z",  # Tue 03:00 UTC, before LONDON
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "spread": 5.0,
    }
    out = apply_session_filter(bar)
    assert out["passed"] is False
    assert out["reason"] == "HOUR_OUTSIDE_WINDOW"


def test_session_filter_blocks_wide_spread():
    bar = {
        "time": "2026-04-28T10:00:00Z",
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2,
        "spread": 99.0,  # > max_spread_points default 25
    }
    out = apply_session_filter(bar)
    assert out["passed"] is False
    assert out["reason"] == "SPREAD_TOO_HIGH"


def test_session_filter_custom_settings():
    bar = {
        "time": "2026-04-28T22:30:00Z",  # late
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2, "spread": 1.0,
    }
    # Custom: extend window to 24h
    out = apply_session_filter(bar, settings={"start_hour_utc": 0, "end_hour_utc": 24})
    assert out["passed"] is True


# ----- direct strategy snapshot interface -----

def test_strategy_handles_unfresh_snapshot():
    snap = FeatureSnapshot(values={}, labels={"session": "LONDON"}, is_fresh=False)
    decision = EMARSITrendStrategy().evaluate(snap)
    assert decision.direction is StrategyDirection.FLAT
    assert "SNAPSHOT_INVALID" in decision.rationale_codes


def test_strategy_handles_missing_features():
    snap = FeatureSnapshot(
        values={"fast_ema": 1.0},  # missing other required features
        labels={"session": "LONDON"},
        is_fresh=True,
    )
    decision = EMARSITrendStrategy().evaluate(snap)
    assert decision.direction is StrategyDirection.FLAT
    assert "FEATURES_INVALID" in decision.rationale_codes


def test_breakout_strategy_handles_unfresh_snapshot():
    snap = FeatureSnapshot(values={}, labels={"session": "LONDON"}, is_fresh=False)
    decision = BreakoutVolatilityStrategy().evaluate(snap)
    assert decision.direction is StrategyDirection.FLAT
    assert "SNAPSHOT_INVALID" in decision.rationale_codes
