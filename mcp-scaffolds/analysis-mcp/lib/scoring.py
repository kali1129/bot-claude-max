"""Aggregate setup scoring v2 (0..100). Drives the TAKE/SKIP/WAIT recommendation.

Changes vs v1:
  - Trend split into 3 timeframes: M15 (15) + H4 (15) + D1 (15) for 45 pts of
    pure trend-alignment.
  - RSI gate becomes momentum-aligned (not just non-extreme): bullish setups
    want RSI > 50 AND < 70.
  - +volume confirmation (10): tick-volume > 1.5× MA20.
  - +swing strength (10): the last 5 bars made a new local extreme in the
    trade direction.
  - +room (5): no major S/R within 1× ATR in the trade direction (don't
    enter directly into a wall).

Backwards-compatible: the function signature keeps the same positional args
and the optional ``ohlcv_h4``; ``ohlcv_d1`` is new and optional. Returns
the same shape — ``{score, recommendation, rr, breakdown}``.
"""
from __future__ import annotations

from typing import List, Dict, Optional

import numpy as np

from . import indicators, structure


# -------------------- helpers --------------------

def _close(ohlcv):
    return np.array([float(b["close"]) for b in ohlcv], dtype=float)


def _high(ohlcv):
    return np.array([float(b["high"]) for b in ohlcv], dtype=float)


def _low(ohlcv):
    return np.array([float(b["low"]) for b in ohlcv], dtype=float)


def _vol(ohlcv):
    """Tick-volume series. Falls back to real_volume / volume / 0 depending
    on what the broker provides."""
    out = []
    for b in ohlcv:
        v = b.get("tick_volume")
        if v is None:
            v = b.get("real_volume")
        if v is None:
            v = b.get("volume", 0)
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return np.array(out, dtype=float)


def _last_finite(arr):
    """Last non-nan finite element, or None."""
    if arr is None or len(arr) == 0:
        return None
    for v in reversed(arr):
        if np.isfinite(v):
            return float(v)
    return None


# -------------------- per-timeframe scoring --------------------

def _trend_score_m15(close: np.ndarray, side: str) -> int:
    """+15 if EMA50 > EMA200 AND close > EMA50 (for buy) and inverse for sell."""
    if len(close) < 200:
        return 0
    e50 = indicators.ema(close, 50)
    e200 = indicators.ema(close, 200)
    e50_last = _last_finite(e50)
    e200_last = _last_finite(e200)
    last = float(close[-1])
    if e50_last is None or e200_last is None:
        return 0
    if side == "buy":
        return 15 if (last > e50_last and e50_last > e200_last) else 0
    else:
        return 15 if (last < e50_last and e50_last < e200_last) else 0


def _trend_score_higher(ohlcv, side: str, ema_period: int) -> int:
    """+15 if higher TF close > EMA(period) (or below for sell)."""
    if not ohlcv or len(ohlcv) < ema_period:
        return 0
    close = _close(ohlcv)
    e = indicators.ema(close, ema_period)
    e_last = _last_finite(e)
    last = float(close[-1])
    if e_last is None:
        return 0
    if side == "buy":
        return 15 if last > e_last else 0
    else:
        return 15 if last < e_last else 0


def _momentum_rsi(close: np.ndarray, side: str) -> int:
    """+10 if RSI is on the right side of 50 AND not yet overbought/oversold.
       buy: 50 < rsi < 70    sell: 30 < rsi < 50"""
    rsi14 = indicators.rsi(close, 14)
    rsi_last = _last_finite(rsi14)
    if rsi_last is None:
        return 0
    if side == "buy":
        return 10 if 50 < rsi_last < 70 else 0
    else:
        return 10 if 30 < rsi_last < 50 else 0


def _volume_score(ohlcv) -> int:
    """+10 if last bar's volume > 1.5× MA20."""
    vol = _vol(ohlcv)
    if len(vol) < 21 or float(vol[-1]) <= 0:
        return 0
    ma20 = float(np.mean(vol[-21:-1]))
    if ma20 <= 0:
        return 0
    return 10 if float(vol[-1]) >= 1.5 * ma20 else 0


def _swing_score(ohlcv, side: str) -> int:
    """+10 if the last 5 bars made a new 20-bar high (buy) or low (sell)."""
    if len(ohlcv) < 25:
        return 0
    high = _high(ohlcv)
    low = _low(ohlcv)
    recent_window = 5
    long_window = 20
    if side == "buy":
        recent_max = float(np.max(high[-recent_window:]))
        prior_max = float(np.max(high[-long_window:-recent_window]))
        return 10 if recent_max > prior_max else 0
    else:
        recent_min = float(np.min(low[-recent_window:]))
        prior_min = float(np.min(low[-long_window:-recent_window]))
        return 10 if recent_min < prior_min else 0


def _rr_score(entry: float, sl: float, tp: float) -> tuple[int, float]:
    risk = abs(entry - sl)
    reward = abs(tp - entry)
    rr = reward / risk if risk > 0 else 0.0
    if rr >= 2.5:
        return 10, rr
    if rr >= 2.0:
        return 5, rr
    return 0, rr


def _atr_score(ohlcv) -> int:
    """+10 if ATR(14) ≥ median(last 50)."""
    if len(ohlcv) < 50:
        return 0
    high = _high(ohlcv)
    low = _low(ohlcv)
    close = _close(ohlcv)
    atr14 = indicators.atr(high, low, close, 14)
    recent = atr14[-50:]
    clean = recent[~np.isnan(recent)]
    if len(clean) <= 5 or not np.isfinite(atr14[-1]):
        return 0
    median = float(np.median(clean))
    return 10 if float(atr14[-1]) >= median else 0


def _room_score(ohlcv, side: str, entry: float) -> int:
    """+5 if there's no S/R level within 1× ATR in the trade direction."""
    if len(ohlcv) < 50:
        return 0
    sr = structure.support_resistance(ohlcv, min_touches=2, max_levels=8)
    levels = sr.get("levels") or []
    if not levels:
        return 5  # no detected wall = clear road
    high = _high(ohlcv)
    low = _low(ohlcv)
    close = _close(ohlcv)
    atr14 = indicators.atr(high, low, close, 14)
    atr_last = _last_finite(atr14)
    if atr_last is None or atr_last <= 0:
        return 0
    threshold = atr_last * 1.0
    for lvl in levels[:5]:
        price = lvl.get("price") if "price" in lvl else lvl.get("level")
        if price is None:
            continue
        try:
            price = float(price)
        except (TypeError, ValueError):
            continue
        if side == "buy" and entry < price <= entry + threshold:
            return 0   # resistance ahead within 1× ATR
        if side == "sell" and entry - threshold <= price < entry:
            return 0   # support ahead within 1× ATR
    return 5


# -------------------- public --------------------

def mtf_bias(ohlcv_h4: List[Dict], ohlcv_m15: List[Dict]) -> dict:
    """Kept for backwards-compat with callers that read this directly."""
    if not ohlcv_h4 or not ohlcv_m15 or len(ohlcv_h4) < 200 or len(ohlcv_m15) < 50:
        return {"aligned": False, "reason": "NOT_ENOUGH_BARS"}
    e200_h4 = indicators.ema(_close(ohlcv_h4), 200)
    h4_close = float(_close(ohlcv_h4)[-1])
    h4_bias = "bullish" if h4_close > e200_h4[-1] else "bearish"

    e50_m15 = indicators.ema(_close(ohlcv_m15), 50)
    m15_close = float(_close(ohlcv_m15)[-1])
    m15_bias = "bullish" if m15_close > e50_m15[-1] else "bearish"

    aligned = h4_bias == m15_bias
    return {
        "aligned": aligned,
        "h4_bias": h4_bias,
        "m15_bias": m15_bias,
        "side": "buy" if aligned and h4_bias == "bullish" else "sell" if aligned else None,
    }


def score_setup(
    ohlcv: List[Dict],
    side: str,
    entry: float,
    sl: float,
    tp: float,
    ohlcv_h4: Optional[List[Dict]] = None,
    ohlcv_d1: Optional[List[Dict]] = None,
) -> dict:
    """Composite score 0..100. ≥70 = TAKE."""
    if len(ohlcv) < 50:
        return {"score": 0, "recommendation": "SKIP", "reason": "NOT_ENOUGH_BARS",
                "breakdown": {}}

    breakdown: Dict[str, int | str] = {}
    score = 0

    close = _close(ohlcv)

    # 1. Trend M15 (15)
    s = _trend_score_m15(close, side)
    breakdown["trend_m15"] = s
    score += s

    # 2. Trend H4 (15) — needs ohlcv_h4 with EMA200
    if ohlcv_h4 is not None and len(ohlcv_h4) >= 200:
        s = _trend_score_higher(ohlcv_h4, side, ema_period=200)
        breakdown["trend_h4"] = s
        score += s
    else:
        breakdown["trend_h4"] = "not_provided"

    # 3. Trend D1 (15) — uses EMA50 since D1 series usually has fewer bars
    if ohlcv_d1 is not None and len(ohlcv_d1) >= 50:
        s = _trend_score_higher(ohlcv_d1, side, ema_period=50)
        breakdown["trend_d1"] = s
        score += s
    else:
        breakdown["trend_d1"] = "not_provided"

    # 4. Momentum (RSI) (10)
    s = _momentum_rsi(close, side)
    breakdown["momentum_rsi"] = s
    score += s

    # 5. Volume (10)
    s = _volume_score(ohlcv)
    breakdown["volume"] = s
    score += s

    # 6. Swing strength (10)
    s = _swing_score(ohlcv, side)
    breakdown["swing"] = s
    score += s

    # 7. R:R (10)
    s, rr_val = _rr_score(entry, sl, tp)
    breakdown["rr"] = s
    score += s

    # 8. ATR alive (10)
    s = _atr_score(ohlcv)
    breakdown["atr"] = s
    score += s

    # 9. Room ahead (5)
    s = _room_score(ohlcv, side, entry)
    breakdown["room"] = s
    score += s

    # Cap at 100 just in case (sums to 105 max with all numeric — acceptable)
    score = min(score, 100)

    if score >= 70:
        recommendation = "TAKE"
    elif score >= 50:
        recommendation = "WAIT"
    else:
        recommendation = "SKIP"

    return {
        "score": score,
        "recommendation": recommendation,
        "rr": round(rr_val, 2),
        "breakdown": breakdown,
    }
