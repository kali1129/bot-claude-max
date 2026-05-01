"""Breakout Hunter — Donchian Channel breakout strategy (Turtle-inspired).

Entry: Price breaks above 20-period high (buy) or below 20-period low (sell).
Filters: Volume confirmation, H4 trend alignment, ATR alive.
SL: 2.0 x ATR(14).  TP: 6.0 x ATR(14).  R:R = 3.0:1.

Theoretical performance (Turtle Trading System research, QuantifiedStrategies):
  - Win rate: 30-40% (low WR but large winners)
  - R:R: 3.0:1 (big reward compensates low WR)
  - Expectancy: +0.20R to +0.40R

The original Turtle system: compounded $100K to $3.6M over decades.
Key insight: skip breakouts that follow a recent winner (trends start
after a string of failures, not successes).
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .base import Signal, Strategy

_indicators = None


def _get_ind():
    global _indicators
    if _indicators is None:
        import sys
        _indicators = sys.modules.get("analysis_lib.indicators")
    return _indicators


def _close(bars):
    return np.array([float(b["close"]) for b in bars], dtype=float)

def _high(bars):
    return np.array([float(b["high"]) for b in bars], dtype=float)

def _low(bars):
    return np.array([float(b["low"]) for b in bars], dtype=float)

def _vol(bars):
    out = []
    for b in bars:
        v = b.get("tick_volume", b.get("real_volume", b.get("volume", 0)))
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            out.append(0.0)
    return np.array(out, dtype=float)

def _last(arr):
    if arr is None or len(arr) == 0:
        return None
    for v in reversed(arr):
        if np.isfinite(v):
            return float(v)
    return None


class BreakoutHunter(Strategy):
    id = "breakout_hunter"
    name = "Breakout Hunter"
    description = "Canal Donchian 20 periodos. Compra en ruptura de maximos, vende en ruptura de minimos. Inspirado en el sistema Turtle Trading."
    strategy_type = "breakout"
    color = "amber"

    theoretical_wr = 35.0
    theoretical_rr = 3.0
    theoretical_expectancy = 0.30

    min_score = 65
    sl_atr_mult = 2.0
    tp_atr_mult = 6.0   # 3:1 R:R

    donchian_period = 20
    # Market & schedule: breakouts happen at session opens
    # London open (07-10 UTC) + NY open (13-16 UTC) -- peak volume windows
    preferred_symbols = {"EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "BTCUSD", "ETHUSD"}
    blocked_symbols = frozenset()
    trading_hours = [(7, 10), (13, 16)]  # London open + NY open
    schedule_desc = "07-10 + 13-16 UTC (London + NY opens)"


    def propose(self, symbol, tick, bars_m15, bars_h4, bars_d1) -> List[Signal]:
        ind = _get_ind()
        if ind is None or not bars_m15 or len(bars_m15) < self.donchian_period + 20:
            return []
        if not tick or tick.get("ok") is False:
            return []

        close = _close(bars_m15)
        high = _high(bars_m15)
        low = _low(bars_m15)
        vol = _vol(bars_m15)

        # Donchian Channel (manual calculation)
        n = self.donchian_period
        don_high = float(np.max(high[-n-1:-1]))  # Highest high of last N bars (excluding current)
        don_low = float(np.min(low[-n-1:-1]))     # Lowest low of last N bars (excluding current)
        don_mid = (don_high + don_low) / 2.0

        # ATR
        atr14 = ind.atr(high, low, close, 14)
        atr_val = _last(atr14)
        if atr_val is None or atr_val <= 0:
            return []

        # ATR alive check
        atr_recent = atr14[-50:]
        atr_clean = atr_recent[~np.isnan(atr_recent)]
        atr_median = float(np.median(atr_clean)) if len(atr_clean) > 5 else 0
        atr_alive = atr_val >= atr_median

        # Volume
        vol_ma20 = float(np.mean(vol[-21:-1])) if len(vol) >= 21 else 0
        vol_current = float(vol[-1]) if len(vol) > 0 else 0
        vol_surge = vol_current >= 1.5 * vol_ma20 if vol_ma20 > 0 else False

        # Higher TF trend
        h4_bullish = h4_bearish = False
        if bars_h4 and len(bars_h4) >= 50:
            h4_close = _close(bars_h4)
            h4_ema50 = ind.ema(h4_close, 50)
            h4_last_ema = _last(h4_ema50)
            if h4_last_ema:
                h4_bullish = float(h4_close[-1]) > h4_last_ema
                h4_bearish = float(h4_close[-1]) < h4_last_ema

        last_close = float(close[-1])
        spread = abs(float(tick.get("ask", 0)) - float(tick.get("bid", 0)))

        signals = []
        for side in ("buy", "sell"):
            entry = float(tick["ask"]) if side == "buy" else float(tick["bid"])
            sl = entry - self.sl_atr_mult * atr_val if side == "buy" else entry + self.sl_atr_mult * atr_val
            tp = entry + self.tp_atr_mult * atr_val if side == "buy" else entry - self.tp_atr_mult * atr_val

            score = 0
            bd = {}

            # 1. Breakout signal (30): price above/below Donchian
            if side == "buy":
                if last_close > don_high:
                    bd["breakout"] = 30
                elif last_close > don_high - 0.2 * atr_val:
                    bd["breakout"] = 15  # near breakout
                else:
                    bd["breakout"] = 0
            else:
                if last_close < don_low:
                    bd["breakout"] = 30
                elif last_close < don_low + 0.2 * atr_val:
                    bd["breakout"] = 15
                else:
                    bd["breakout"] = 0
            score += bd["breakout"]

            # 2. Volume confirmation (15)
            bd["volume"] = 15 if vol_surge else 0
            score += bd["volume"]

            # 3. H4 trend alignment (15)
            if side == "buy":
                bd["trend_h4"] = 15 if h4_bullish else 0
            else:
                bd["trend_h4"] = 15 if h4_bearish else 0
            score += bd["trend_h4"]

            # 4. ATR alive (10)
            bd["atr_alive"] = 10 if atr_alive else 0
            score += bd["atr_alive"]

            # 5. Breakout quality (10): how far above the Donchian level
            if side == "buy" and don_high > 0:
                excess = (last_close - don_high) / atr_val if atr_val > 0 else 0
                bd["breakout_q"] = 10 if excess > 0.3 else (5 if excess > 0 else 0)
            elif side == "sell" and don_low > 0:
                excess = (don_low - last_close) / atr_val if atr_val > 0 else 0
                bd["breakout_q"] = 10 if excess > 0.3 else (5 if excess > 0 else 0)
            else:
                bd["breakout_q"] = 0
            score += bd["breakout_q"]

            # 6. Channel width (10): wider channel = stronger breakout
            channel_width_atr = (don_high - don_low) / atr_val if atr_val > 0 else 0
            bd["channel_width"] = 10 if channel_width_atr > 3.0 else (5 if channel_width_atr > 2.0 else 0)
            score += bd["channel_width"]

            # 7. Spread quality (10)
            sl_dist = abs(entry - sl)
            spread_pct = (spread / sl_dist * 100) if sl_dist > 0 else 999
            bd["spread_q"] = 10 if spread_pct < 15 else (5 if spread_pct < 25 else 0)
            score += bd["spread_q"]

            score = min(score, 100)
            rec = "TAKE" if score >= self.min_score else ("WAIT" if score >= 40 else "SKIP")

            signals.append(Signal(
                symbol=symbol, side=side,
                entry=round(entry, 5), sl=round(sl, 5), tp=round(tp, 5),
                atr=round(atr_val, 5), score=score, rec=rec,
                breakdown=bd, strategy_id=self.id,
                extra={"donchian_high": round(don_high, 5),
                       "donchian_low": round(don_low, 5),
                       "vol_ratio": round(vol_current / vol_ma20, 2) if vol_ma20 > 0 else 0,
                       "spread_pct": round(spread_pct, 1)},
            ))

        return signals

    def hard_filter(self, signal, tick):
        # Base checks: symbol allowlist + trading hours
        ok, reason = super().hard_filter(signal, tick)
        if not ok:
            return False, reason
        # Breakout requires actual breakout signal
        if signal.breakdown.get("breakout", 0) == 0:
            return False, "NO_BREAKOUT"
        return True, "OK"
