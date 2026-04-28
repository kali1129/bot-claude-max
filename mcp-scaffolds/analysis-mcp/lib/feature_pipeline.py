"""Feature pipeline — builds a FeatureSnapshot from raw OHLCV.

Bridges the bot nuevo's `List[Dict]` OHLCV format to the FeatureSnapshot
shape that the ported strategies (ema_rsi_trend, breakout_volatility) expect.

Reuses the existing numpy indicators (`lib.indicators`) to avoid duplicating
math. Adds the legacy-shaped derived features (atr_pct, normalized_trend_gap,
breakout_position, rolling_volatility, candle_body_fraction, etc.).

OHLCV input shape (per the analysis-mcp convention):
    [{"time": "2026-04-27T12:00:00Z", "open": ..., "high": ..., "low": ...,
      "close": ..., "volume": ..., "spread": ...}, ...]

`spread` (in points) is optional; if missing, `spread_points` is set to 0.0
which still passes the ema_rsi_trend SPREAD_OK gate (max_spread_points=25.0
default).
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from statistics import pstdev
from typing import Any, Dict, List, Mapping

import numpy as np

from lib import indicators as ind  # numpy-based, already in analysis-mcp
from lib.strategies.base import FeatureSnapshot

# Local import: _shared lives one folder up from analysis-mcp/lib/
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED = _HERE.parent.parent / "_shared"
if str(_SHARED.parent) not in sys.path:
    sys.path.insert(0, str(_SHARED.parent))

from _shared.common.sessions import session_label  # noqa: E402


def _parse_ts(value: Any) -> datetime:
    """Parse an ISO-ish string or return UTC now if missing."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            cleaned = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(cleaned)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _tail_returns(closes: np.ndarray, lookback: int) -> list[float]:
    """Return the last `lookback` close-to-close simple returns."""
    if len(closes) <= 1:
        return []
    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = float(closes[i - 1])
        cur = float(closes[i])
        if prev == 0.0:
            continue
        rets.append((cur / prev) - 1.0)
    return rets[-lookback:] if len(rets) >= lookback else rets


def build_snapshot(
    ohlcv: List[Dict[str, Any]],
    *,
    fast_period: int = 5,
    slow_period: int = 20,
    rsi_period: int = 14,
    atr_period: int = 14,
    momentum_lookback: int = 10,
    vol_period: int = 20,
    breakout_lookback: int = 20,
) -> FeatureSnapshot:
    """Build a FeatureSnapshot from a `List[Dict]` OHLCV array.

    Returns an empty (`is_fresh=False`) snapshot when the input is too short
    for the configured lookbacks.
    """
    if not ohlcv or len(ohlcv) < max(slow_period, rsi_period, atr_period, breakout_lookback) + 2:
        return FeatureSnapshot(values={}, labels={"session": "UNKNOWN"}, is_fresh=False)

    closes = np.array([float(b.get("close", float("nan"))) for b in ohlcv], dtype=float)
    highs = np.array([float(b.get("high", float("nan"))) for b in ohlcv], dtype=float)
    lows = np.array([float(b.get("low", float("nan"))) for b in ohlcv], dtype=float)
    opens = np.array([float(b.get("open", float("nan"))) for b in ohlcv], dtype=float)

    # Indicators
    fast_ema_arr = ind.ema(closes, fast_period)
    slow_ema_arr = ind.ema(closes, slow_period)
    fast_sma_arr = ind.sma(closes, fast_period)
    slow_sma_arr = ind.sma(closes, slow_period)
    rsi_arr = ind.rsi(closes, rsi_period) if hasattr(ind, "rsi") else None
    atr_arr = ind.atr(highs, lows, closes, atr_period) if hasattr(ind, "atr") else None

    fast_ema = float(fast_ema_arr[-1]) if len(fast_ema_arr) else float("nan")
    slow_ema = float(slow_ema_arr[-1]) if len(slow_ema_arr) else float("nan")
    fast_sma = float(fast_sma_arr[-1]) if len(fast_sma_arr) else float("nan")
    slow_sma = float(slow_sma_arr[-1]) if len(slow_sma_arr) else float("nan")
    last_close = float(closes[-1]) if len(closes) else float("nan")

    rsi_value = float(rsi_arr[-1]) if rsi_arr is not None and len(rsi_arr) else float("nan")
    atr_value = float(atr_arr[-1]) if atr_arr is not None and len(atr_arr) else float("nan")
    atr_pct = atr_value / last_close if (math.isfinite(atr_value) and last_close > 0) else float("nan")

    # Trend gaps
    sma_gap = (
        fast_sma - slow_sma
        if math.isfinite(fast_sma) and math.isfinite(slow_sma)
        else float("nan")
    )
    ema_gap = (
        fast_ema - slow_ema
        if math.isfinite(fast_ema) and math.isfinite(slow_ema)
        else float("nan")
    )
    normalized_trend_gap = (
        ema_gap / last_close if math.isfinite(ema_gap) and last_close != 0.0 else float("nan")
    )

    # Momentum
    return_1 = (
        float(closes[-1] / closes[-2] - 1.0)
        if len(closes) >= 2 and closes[-2] != 0.0
        else float("nan")
    )
    return_n = (
        float(closes[-1] / closes[-momentum_lookback - 1] - 1.0)
        if len(closes) > momentum_lookback and closes[-momentum_lookback - 1] != 0.0
        else float("nan")
    )

    # Rolling volatility (population stdev of last `vol_period` returns)
    tail = _tail_returns(closes, vol_period)
    rolling_volatility = float(pstdev(tail)) if len(tail) >= 2 else float("nan")

    # Breakout features over the last `breakout_lookback` bars
    if len(highs) >= breakout_lookback:
        window_high = float(np.max(highs[-breakout_lookback:]))
        window_low = float(np.min(lows[-breakout_lookback:]))
        rng = window_high - window_low
        breakout_position = (
            (last_close - window_low) / rng if rng > 0.0 else 0.5
        )
        breakout_range = rng
    else:
        window_high = float("nan")
        window_low = float("nan")
        breakout_position = float("nan")
        breakout_range = float("nan")

    # Candle structure (last bar)
    o, h, l, c = float(opens[-1]), float(highs[-1]), float(lows[-1]), float(closes[-1])
    full_range = max(h - l, 0.0)
    candle_body = c - o
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    if full_range > 0.0:
        close_location = (c - l) / full_range
        body_fraction = abs(candle_body) / full_range
    else:
        close_location = 0.5
        body_fraction = 0.0

    # Spread features (point-based; default 0 if not present in bars)
    spread_series = [float(b.get("spread", 0.0)) for b in ohlcv]
    spread_points = float(spread_series[-1])
    if len(spread_series) >= 5:
        s_mean = sum(spread_series) / len(spread_series)
        s_std = pstdev(spread_series) if len(set(spread_series)) > 1 else 0.0
        spread_zscore = (spread_points - s_mean) / s_std if s_std > 0 else 0.0
    else:
        spread_zscore = 0.0

    # Session label from last bar's timestamp
    last_ts = _parse_ts(ohlcv[-1].get("time"))
    session = session_label(last_ts)

    values: Dict[str, float] = {
        "fast_ema": fast_ema,
        "slow_ema": slow_ema,
        "fast_sma": fast_sma,
        "slow_sma": slow_sma,
        "trend_gap": sma_gap,
        "ema_gap": ema_gap,
        "normalized_trend_gap": normalized_trend_gap,
        "close_vs_fast_ema": last_close - fast_ema if math.isfinite(fast_ema) else float("nan"),
        "close_vs_slow_ema": last_close - slow_ema if math.isfinite(slow_ema) else float("nan"),
        "rsi": rsi_value,
        "atr": atr_value,
        "atr_pct": atr_pct,
        "rolling_volatility": rolling_volatility,
        "return_1": return_1,
        f"return_{momentum_lookback}": return_n,
        "momentum_acceleration": (
            return_1 - return_n
            if math.isfinite(return_1) and math.isfinite(return_n)
            else float("nan")
        ),
        "breakout_high": window_high,
        "breakout_low": window_low,
        "breakout_range": breakout_range,
        "breakout_position": breakout_position,
        "candle_range": full_range,
        "candle_body": candle_body,
        "candle_body_fraction": body_fraction,
        "candle_upper_wick": upper_wick,
        "candle_lower_wick": lower_wick,
        "candle_close_location": close_location,
        "candle_is_bullish": 1.0 if c > o else 0.0,
        "spread_points": spread_points,
        "spread_zscore": spread_zscore,
    }

    labels = {"session": session}

    return FeatureSnapshot(values=values, labels=labels, is_fresh=True)


def evaluate_strategy_on_ohlcv(
    ohlcv: List[Dict[str, Any]],
    strategy_name: str,
    config: Mapping[str, object] | None = None,
) -> dict:
    """Convenience: pipeline + strategy in one call. Returns dict for MCP tool."""
    from lib.strategies import evaluate as _evaluate, list_strategies

    if strategy_name not in list_strategies():
        return {
            "ok": False,
            "reason": "UNKNOWN_STRATEGY",
            "detail": f"Strategy '{strategy_name}' not registered. Available: {list_strategies()}",
        }
    snapshot = build_snapshot(ohlcv)
    decision = _evaluate(strategy_name, snapshot, config)
    return decision.to_dict()


__all__ = ["build_snapshot", "evaluate_strategy_on_ohlcv"]
