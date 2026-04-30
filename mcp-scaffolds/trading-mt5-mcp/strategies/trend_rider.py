"""Trend Rider — EMA crossover trend-following strategy.

Entry: EMA20 > EMA50 (buy) with multi-timeframe trend confirmation.
Filters: RSI momentum aligned, ADX > 20, ATR alive.
SL: 1.5 x ATR(14).  TP: 3.0 x ATR(14).  R:R = 2.0:1.

Theoretical performance (based on published EMA crossover + RSI filter
backtests on forex majors):
  - Win rate: 35-45%
  - R:R: 2.0:1
  - Expectancy: +0.10R to +0.30R

Sources:
  - FMZQuant: Dynamic EMA Crossover with RSI Filter + ATR Stop Management
  - LuxAlgo: Moving Average Crossover with trend filters
  - QuantVPS: Top 20 Trading Bot Strategies 2026
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .base import Signal, Strategy

# Lazy import to avoid circular — these are loaded at runtime by auto_trader
_indicators = None
_structure = None


def _get_libs():
    global _indicators, _structure
    if _indicators is None:
        import sys
        _indicators = sys.modules.get("analysis_lib.indicators")
        _structure = sys.modules.get("analysis_lib.structure")
    return _indicators, _structure


def _close(bars):
    return np.array([float(b["close"]) for b in bars], dtype=float)


def _high(bars):
    return np.array([float(b["high"]) for b in bars], dtype=float)


def _low(bars):
    return np.array([float(b["low"]) for b in bars], dtype=float)


def _last(arr):
    if arr is None or len(arr) == 0:
        return None
    for v in reversed(arr):
        if np.isfinite(v):
            return float(v)
    return None


class TrendRider(Strategy):
    id = "trend_rider"
    name = "Trend Rider"
    description = "EMA 20/50 crossover + RSI filter + ADX trend confirmation. Sigue tendencias fuertes con SL amplio y trailing."
    strategy_type = "trend"
    color = "green"

    theoretical_wr = 40.0
    theoretical_rr = 2.0
    theoretical_expectancy = 0.20

    min_score = 70
    sl_atr_mult = 1.5
    tp_atr_mult = 3.0
    # Market & schedule: trends develop during London + NY overlap
    preferred_symbols = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD", "BTCUSD", "ETHUSD"}
    blocked_symbols = frozenset()
    trading_hours = [(8, 17)]  # London open through NY afternoon
    schedule_desc = "08-17 UTC (London + NY overlap)"


    def propose(self, symbol, tick, bars_m15, bars_h4, bars_d1) -> List[Signal]:
        ind, struct = _get_libs()
        if ind is None or not bars_m15 or len(bars_m15) < 200:
            return []
        if not tick or tick.get("ok") is False:
            return []

        close = _close(bars_m15)
        high = _high(bars_m15)
        low = _low(bars_m15)

        # Core indicators
        ema20 = ind.ema(close, 20)
        ema50 = ind.ema(close, 50)
        ema200 = ind.ema(close, 200)
        rsi14 = ind.rsi(close, 14)
        atr14 = ind.atr(high, low, close, 14)
        adx14 = ind.adx(high, low, close, 14) if hasattr(ind, 'adx') else None

        e20 = _last(ema20)
        e50 = _last(ema50)
        e200 = _last(ema200)
        rsi_val = _last(rsi14)
        atr_val = _last(atr14)
        adx_val = _last(adx14) if adx14 is not None else None

        if any(v is None for v in [e20, e50, e200, rsi_val, atr_val]):
            return []
        if atr_val <= 0:
            return []

        # ATR quality: must be above median of last 50 bars
        atr_recent = atr14[-50:]
        atr_clean = atr_recent[~np.isnan(atr_recent)]
        atr_median = float(np.median(atr_clean)) if len(atr_clean) > 5 else 0
        atr_alive = atr_val >= atr_median

        # Higher TF checks
        h4_bullish = h4_bearish = False
        if bars_h4 and len(bars_h4) >= 200:
            h4_close = _close(bars_h4)
            h4_ema200 = ind.ema(h4_close, 200)
            h4_last = _last(h4_ema200)
            if h4_last:
                h4_bullish = float(h4_close[-1]) > h4_last
                h4_bearish = float(h4_close[-1]) < h4_last

        d1_bullish = d1_bearish = False
        if bars_d1 and len(bars_d1) >= 50:
            d1_close = _close(bars_d1)
            d1_ema50 = ind.ema(d1_close, 50)
            d1_last = _last(d1_ema50)
            if d1_last:
                d1_bullish = float(d1_close[-1]) > d1_last
                d1_bearish = float(d1_close[-1]) < d1_last

        # Spread
        spread = abs(float(tick.get("ask", 0)) - float(tick.get("bid", 0)))

        signals = []
        for side in ("buy", "sell"):
            entry = float(tick["ask"]) if side == "buy" else float(tick["bid"])
            sl = entry - self.sl_atr_mult * atr_val if side == "buy" else entry + self.sl_atr_mult * atr_val
            tp = entry + self.tp_atr_mult * atr_val if side == "buy" else entry - self.tp_atr_mult * atr_val

            score = 0
            bd = {}

            # 1. EMA crossover (20): EMA20 on correct side of EMA50
            if side == "buy":
                bd["ema_cross"] = 20 if e20 > e50 else 0
            else:
                bd["ema_cross"] = 20 if e20 < e50 else 0
            score += bd["ema_cross"]

            # 2. M15 trend (10): price vs EMA200
            if side == "buy":
                bd["trend_m15"] = 10 if float(close[-1]) > e200 else 0
            else:
                bd["trend_m15"] = 10 if float(close[-1]) < e200 else 0
            score += bd["trend_m15"]

            # 3. H4 trend (10)
            if side == "buy":
                bd["trend_h4"] = 10 if h4_bullish else 0
            else:
                bd["trend_h4"] = 10 if h4_bearish else 0
            score += bd["trend_h4"]

            # 4. D1 trend (10)
            if side == "buy":
                bd["trend_d1"] = 10 if d1_bullish else 0
            else:
                bd["trend_d1"] = 10 if d1_bearish else 0
            score += bd["trend_d1"]

            # 5. RSI momentum (15): aligned with direction, not extreme
            if side == "buy":
                bd["rsi"] = 15 if 40 < rsi_val < 70 else (5 if 30 < rsi_val < 80 else 0)
            else:
                bd["rsi"] = 15 if 30 < rsi_val < 60 else (5 if 20 < rsi_val < 70 else 0)
            score += bd["rsi"]

            # 6. ADX trend strength (10)
            if adx_val is not None:
                bd["adx"] = 10 if adx_val > 20 else (5 if adx_val > 15 else 0)
            else:
                bd["adx"] = 5  # neutral if ADX unavailable
            score += bd["adx"]

            # 7. ATR alive (10)
            bd["atr_alive"] = 10 if atr_alive else 0
            score += bd["atr_alive"]

            # 8. Spread quality (5)
            sl_dist = abs(entry - sl)
            spread_pct = (spread / sl_dist * 100) if sl_dist > 0 else 999
            bd["spread_q"] = 5 if spread_pct < 20 else (3 if spread_pct < 30 else 0)
            score += bd["spread_q"]

            # 9. Structure (10): recent price action confirms
            if struct and bars_m15 and len(bars_m15) >= 25:
                try:
                    ms = struct.market_structure(bars_m15, swing_n=5)
                    trend = ms.get("trend", "UNKNOWN")
                    if side == "buy" and trend == "UPTREND":
                        bd["structure"] = 10
                    elif side == "sell" and trend == "DOWNTREND":
                        bd["structure"] = 10
                    elif trend == "RANGE":
                        bd["structure"] = 0
                    else:
                        bd["structure"] = 0
                except Exception:
                    bd["structure"] = 0
            else:
                bd["structure"] = 0
            score += bd["structure"]

            score = min(score, 100)
            rec = "TAKE" if score >= self.min_score else ("WAIT" if score >= 50 else "SKIP")

            signals.append(Signal(
                symbol=symbol, side=side,
                entry=round(entry, 5), sl=round(sl, 5), tp=round(tp, 5),
                atr=round(atr_val, 5), score=score, rec=rec,
                breakdown=bd, strategy_id=self.id,
                extra={"rsi": round(rsi_val, 1), "adx": round(adx_val, 1) if adx_val else None,
                       "spread_pct": round(spread_pct, 1)},
            ))

        return signals

    def hard_filter(self, signal, tick):
        # Base checks: symbol allowlist + trading hours
        ok, reason = super().hard_filter(signal, tick)
        if not ok:
            return False, reason
        # Trend rider requires ADX > 15 minimum
        adx = signal.extra.get("adx")
        if adx is not None and adx < 15:
            return False, f"ADX_TOO_LOW ({adx:.0f})"
        return True, "OK"
