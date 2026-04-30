"""Mean Reverter — Bollinger Band + RSI mean-reversion strategy.

Entry: Price touches lower/upper BB(20,2) with RSI confirmation.
Market regime: ADX < 30 (ranging, not trending).
SL: 2.0 x ATR(14).  TP: Middle BB (dynamic).

Theoretical performance (from BabyPips, QuantifiedStrategies, FMZQuant):
  - Win rate: 55-65% (higher WR because targeting the mean is a shorter move)
  - R:R: 1.0-1.5:1 (smaller reward, higher probability)
  - Expectancy: +0.15R to +0.30R

Works BEST in ranging/consolidating markets.  Gets destroyed in trends.
The ADX filter is the key — only trade when ADX says "no trend."
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

def _last(arr):
    if arr is None or len(arr) == 0:
        return None
    for v in reversed(arr):
        if np.isfinite(v):
            return float(v)
    return None


class MeanReverter(Strategy):
    id = "mean_reverter"
    name = "Mean Reverter"
    description = "Bollinger Bands (20,2) + RSI(14) para detectar sobrecompra/sobreventa en mercados laterales. ADX < 30 confirma rango."
    strategy_type = "reversion"
    color = "blue"

    theoretical_wr = 60.0
    theoretical_rr = 1.5
    theoretical_expectancy = 0.25

    min_score = 65
    sl_atr_mult = 2.0
    tp_atr_mult = 0.0  # TP is dynamic (middle BB), not ATR-based

    # BB params
    bb_period = 20
    bb_std = 2.0
    # Market & schedule: mean reversion works in ranging sessions
    # Asian session (00-07 UTC) + late NY/quiet period (17-22 UTC)
    preferred_symbols = {"EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "XAUUSD", "BTCUSD", "ETHUSD"}
    blocked_symbols = frozenset()
    trading_hours = [(0, 7), (17, 22)]  # Asian + late NY
    schedule_desc = "00-07 + 17-22 UTC (Asian + late NY)"


    def propose(self, symbol, tick, bars_m15, bars_h4, bars_d1) -> List[Signal]:
        ind = _get_ind()
        if ind is None or not bars_m15 or len(bars_m15) < 50:
            return []
        if not tick or tick.get("ok") is False:
            return []

        close = _close(bars_m15)
        high = _high(bars_m15)
        low = _low(bars_m15)

        # Bollinger Bands
        bb_upper, bb_mid, bb_lower = ind.bollinger(close, self.bb_period, self.bb_std)
        bb_u = _last(bb_upper)
        bb_m = _last(bb_mid)
        bb_l = _last(bb_lower)

        # RSI
        rsi14 = ind.rsi(close, 14)
        rsi_val = _last(rsi14)

        # ATR
        atr14 = ind.atr(high, low, close, 14)
        atr_val = _last(atr14)

        # ADX (regime filter)
        adx_val = None
        if hasattr(ind, 'adx'):
            adx14 = ind.adx(high, low, close, 14)
            adx_val = _last(adx14)

        if any(v is None for v in [bb_u, bb_m, bb_l, rsi_val, atr_val]):
            return []
        if atr_val <= 0:
            return []

        last_close = float(close[-1])
        spread = abs(float(tick.get("ask", 0)) - float(tick.get("bid", 0)))

        signals = []
        for side in ("buy", "sell"):
            entry = float(tick["ask"]) if side == "buy" else float(tick["bid"])
            sl = entry - self.sl_atr_mult * atr_val if side == "buy" else entry + self.sl_atr_mult * atr_val

            # TP = middle Bollinger Band (the "mean" we're reverting to)
            # Calculate R:R to decide if it's worth it
            if side == "buy":
                tp = bb_m
                # TP must be above entry
                if tp <= entry:
                    tp = entry + 1.5 * atr_val  # fallback
            else:
                tp = bb_m
                if tp >= entry:
                    tp = entry - 1.5 * atr_val

            sl_dist = abs(entry - sl)
            tp_dist = abs(tp - entry)
            rr = tp_dist / sl_dist if sl_dist > 0 else 0

            score = 0
            bd = {}

            # 1. BB touch (25): price at or beyond the band
            if side == "buy":
                if last_close <= bb_l:
                    bd["bb_touch"] = 25
                elif last_close <= bb_l + 0.3 * (bb_m - bb_l):
                    bd["bb_touch"] = 15
                else:
                    bd["bb_touch"] = 0
            else:
                if last_close >= bb_u:
                    bd["bb_touch"] = 25
                elif last_close >= bb_u - 0.3 * (bb_u - bb_m):
                    bd["bb_touch"] = 15
                else:
                    bd["bb_touch"] = 0
            score += bd["bb_touch"]

            # 2. RSI extreme (20): confirms oversold/overbought
            if side == "buy":
                if rsi_val < 25:
                    bd["rsi"] = 20
                elif rsi_val < 30:
                    bd["rsi"] = 15
                elif rsi_val < 40:
                    bd["rsi"] = 5
                else:
                    bd["rsi"] = 0
            else:
                if rsi_val > 75:
                    bd["rsi"] = 20
                elif rsi_val > 70:
                    bd["rsi"] = 15
                elif rsi_val > 60:
                    bd["rsi"] = 5
                else:
                    bd["rsi"] = 0
            score += bd["rsi"]

            # 3. ADX regime (20): low ADX = ranging = good for mean reversion
            if adx_val is not None:
                if adx_val < 20:
                    bd["adx_range"] = 20
                elif adx_val < 25:
                    bd["adx_range"] = 15
                elif adx_val < 30:
                    bd["adx_range"] = 10
                else:
                    bd["adx_range"] = 0  # trending = BAD for MR
            else:
                bd["adx_range"] = 10
            score += bd["adx_range"]

            # 4. R:R quality (15)
            if rr >= 2.0:
                bd["rr"] = 15
            elif rr >= 1.5:
                bd["rr"] = 10
            elif rr >= 1.0:
                bd["rr"] = 5
            else:
                bd["rr"] = 0
            score += bd["rr"]

            # 5. BB width (10): narrower bands = tighter range = better for MR
            bb_width_pct = (bb_u - bb_l) / bb_m * 100 if bb_m > 0 else 999
            if bb_width_pct < 2.0:
                bd["bb_width"] = 10
            elif bb_width_pct < 3.5:
                bd["bb_width"] = 5
            else:
                bd["bb_width"] = 0
            score += bd["bb_width"]

            # 6. Spread quality (10)
            spread_pct = (spread / sl_dist * 100) if sl_dist > 0 else 999
            bd["spread_q"] = 10 if spread_pct < 15 else (5 if spread_pct < 25 else 0)
            score += bd["spread_q"]

            score = min(score, 100)
            rec = "TAKE" if score >= self.min_score else ("WAIT" if score >= 45 else "SKIP")

            signals.append(Signal(
                symbol=symbol, side=side,
                entry=round(entry, 5), sl=round(sl, 5), tp=round(tp, 5),
                atr=round(atr_val, 5), score=score, rec=rec,
                breakdown=bd, strategy_id=self.id,
                extra={"rsi": round(rsi_val, 1),
                       "adx": round(adx_val, 1) if adx_val else None,
                       "bb_pos": "lower" if side == "buy" else "upper",
                       "rr": round(rr, 2),
                       "spread_pct": round(spread_pct, 1)},
            ))

        return signals

    def hard_filter(self, signal, tick):
        # Base checks: symbol allowlist + trading hours
        ok, reason = super().hard_filter(signal, tick)
        if not ok:
            return False, reason
        # Mean reversion requires ADX < 35 (not in strong trend)
        adx = signal.extra.get("adx")
        if adx is not None and adx > 35:
            return False, f"ADX_TOO_HIGH_FOR_MR ({adx:.0f})"
        # Require BB touch score > 0
        if signal.breakdown.get("bb_touch", 0) == 0:
            return False, "NO_BB_TOUCH"
        # Require RSI confirmation
        if signal.breakdown.get("rsi", 0) == 0:
            return False, "NO_RSI_EXTREME"
        return True, "OK"
