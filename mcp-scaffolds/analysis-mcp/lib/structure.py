"""Market structure (HH/HL/LH/LL), support/resistance, candle patterns."""
from __future__ import annotations

from typing import List, Dict

import numpy as np


def _ohlc_arrays(ohlcv: List[Dict]):
    return (
        np.array([float(b["open"]) for b in ohlcv]),
        np.array([float(b["high"]) for b in ohlcv]),
        np.array([float(b["low"]) for b in ohlcv]),
        np.array([float(b["close"]) for b in ohlcv]),
    )


def find_swings(high: np.ndarray, low: np.ndarray, n: int = 5):
    """Pivot highs/lows: a bar is a swing high if it's the max of n bars on
    each side. Returns list of (index, type, price) sorted by index.
    """
    swings = []
    for i in range(n, len(high) - n):
        window_h = high[i - n:i + n + 1]
        window_l = low[i - n:i + n + 1]
        if high[i] == np.max(window_h) and high[i] > 0:
            swings.append((i, "high", float(high[i])))
        elif low[i] == np.min(window_l) and low[i] > 0:
            swings.append((i, "low", float(low[i])))
    return swings


def market_structure(ohlcv: List[Dict], swing_n: int = 5) -> dict:
    if len(ohlcv) < 4 * swing_n + 1:
        return {"trend": "UNKNOWN", "reason": "NOT_ENOUGH_BARS", "swings": []}
    _, high, low, _ = _ohlc_arrays(ohlcv)
    swings = find_swings(high, low, swing_n)
    if len(swings) < 4:
        return {"trend": "UNKNOWN", "reason": "TOO_FEW_SWINGS", "swings": swings}

    last4 = swings[-4:]
    highs = [s for s in last4 if s[1] == "high"]
    lows = [s for s in last4 if s[1] == "low"]

    if len(highs) >= 2 and len(lows) >= 2:
        hh = highs[-1][2] > highs[-2][2]
        hl = lows[-1][2] > lows[-2][2]
        ll = lows[-1][2] < lows[-2][2]
        lh = highs[-1][2] < highs[-2][2]
        if hh and hl:
            trend = "UPTREND"
        elif ll and lh:
            trend = "DOWNTREND"
        else:
            trend = "RANGE"
    else:
        trend = "RANGE"

    return {
        "trend": trend,
        "swings": [{"index": s[0], "type": s[1], "price": s[2]} for s in last4],
    }


def support_resistance(ohlcv: List[Dict], min_touches: int = 2,
                       tolerance_pct: float = 0.15, max_levels: int = 8) -> dict:
    """Cluster recent swing highs/lows; report levels with ≥min_touches."""
    if len(ohlcv) < 30:
        return {"levels": [], "reason": "NOT_ENOUGH_BARS"}
    _, high, low, _ = _ohlc_arrays(ohlcv)
    swings = find_swings(high, low, n=3)
    pts = [(s[2], s[1]) for s in swings]
    if not pts:
        return {"levels": []}

    last_close = float(ohlcv[-1]["close"])
    tol = last_close * tolerance_pct / 100.0
    pts_sorted = sorted(pts, key=lambda x: x[0])

    clusters = []
    cluster_prices = []
    cluster_types = []
    for price, kind in pts_sorted:
        if cluster_prices and price - cluster_prices[-1] <= tol:
            cluster_prices.append(price)
            cluster_types.append(kind)
        else:
            if cluster_prices:
                clusters.append((cluster_prices, cluster_types))
            cluster_prices = [price]
            cluster_types = [kind]
    if cluster_prices:
        clusters.append((cluster_prices, cluster_types))

    levels = []
    for prices, kinds in clusters:
        if len(prices) < min_touches:
            continue
        avg = sum(prices) / len(prices)
        kind = "resistance" if avg > last_close else "support"
        levels.append({
            "level": round(avg, 5),
            "touches": len(prices),
            "type": kind,
            "distance_pct": round((avg - last_close) / last_close * 100, 3),
        })

    levels.sort(key=lambda l: abs(l["distance_pct"]))
    return {"levels": levels[:max_levels], "from_close": last_close}


def candlestick_patterns(ohlcv: List[Dict]) -> dict:
    """Detects last-bar patterns. Returns the strongest match or none."""
    if len(ohlcv) < 3:
        return {"pattern": None, "reason": "NOT_ENOUGH_BARS"}
    o, h, l, c = _ohlc_arrays(ohlcv)
    last = -1
    body = abs(c[last] - o[last])
    full = h[last] - l[last]
    if full == 0:
        return {"pattern": None, "reason": "ZERO_RANGE"}
    upper_wick = h[last] - max(c[last], o[last])
    lower_wick = min(c[last], o[last]) - l[last]
    bullish = c[last] > o[last]

    # Doji
    if body < full * 0.1:
        return {"pattern": "doji", "bias": "neutral", "confidence": 60}
    # Pin bar (rejection)
    if lower_wick >= 2 * body and upper_wick < body:
        return {"pattern": "bullish_pin_bar", "bias": "bullish", "confidence": 75}
    if upper_wick >= 2 * body and lower_wick < body:
        return {"pattern": "bearish_pin_bar", "bias": "bearish", "confidence": 75}
    # Engulfing
    prev_body = abs(c[last - 1] - o[last - 1])
    if (
        bullish
        and c[last - 1] < o[last - 1]
        and c[last] > o[last - 1]
        and o[last] < c[last - 1]
        and body > prev_body
    ):
        return {"pattern": "bullish_engulfing", "bias": "bullish", "confidence": 80}
    if (
        not bullish
        and c[last - 1] > o[last - 1]
        and c[last] < o[last - 1]
        and o[last] > c[last - 1]
        and body > prev_body
    ):
        return {"pattern": "bearish_engulfing", "bias": "bearish", "confidence": 80}
    # Inside bar
    if h[last] < h[last - 1] and l[last] > l[last - 1]:
        return {"pattern": "inside_bar", "bias": "neutral", "confidence": 50}
    return {"pattern": None, "bias": "neutral", "confidence": 0}
