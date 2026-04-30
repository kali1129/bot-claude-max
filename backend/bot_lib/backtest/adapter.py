"""Backtest adapter — wraps the 4 concrete strategies into signal_fn callbacks
for the generic backtest engine.

Each strategy's propose() method is adapted to the BacktestEngine's
signal_fn(ohlcv_so_far) -> {"direction": str, "atr": float, "score": float}
interface.

Usage:
    from bot_lib.backtest.adapter import strategy_signal_fn
    from bot_lib.backtest.engine import run_backtest

    fn = strategy_signal_fn("trend_rider")
    result = run_backtest(ohlcv=bars, signal_fn=fn, config={...})
"""
from __future__ import annotations

import math
import sys
from typing import Any, Mapping

# Add strategy path
_STRAT_DIR = "/opt/trading-bot/app/mcp-scaffolds/trading-mt5-mcp"
if _STRAT_DIR not in sys.path:
    sys.path.insert(0, _STRAT_DIR)
_SHARED_DIR = "/opt/trading-bot/app/mcp-scaffolds/_shared"
if _SHARED_DIR not in sys.path:
    sys.path.insert(0, _SHARED_DIR)


def _compute_ema(closes: list[float], period: int) -> list[float]:
    """Compute EMA from a list of closes."""
    if len(closes) < period:
        return [float("nan")] * len(closes)
    k = 2 / (period + 1)
    ema = [float("nan")] * (period - 1)
    ema.append(sum(closes[:period]) / period)
    for i in range(period, len(closes)):
        ema.append(closes[i] * k + ema[-1] * (1 - k))
    return ema


def _compute_rsi(closes: list[float], period: int = 14) -> list[float]:
    """Compute RSI."""
    if len(closes) < period + 1:
        return [float("nan")] * len(closes)
    rsi = [float("nan")] * period
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    if avg_loss == 0:
        rsi.append(100.0)
    else:
        rs = avg_gain / avg_loss
        rsi.append(100 - 100 / (1 + rs))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi.append(100 - 100 / (1 + rs))
    return rsi


def _compute_atr(bars: list[dict], period: int = 14) -> list[float]:
    """Compute ATR from OHLCV bars."""
    if len(bars) < period + 1:
        return [float("nan")] * len(bars)
    trs = [float("nan")]
    for i in range(1, len(bars)):
        h = bars[i]["high"]
        l = bars[i]["low"]
        pc = bars[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    atr = [float("nan")] * period
    atr.append(sum(trs[1:period + 1]) / period)
    for i in range(period + 1, len(trs)):
        atr.append((atr[-1] * (period - 1) + trs[i]) / period)
    return atr


def _compute_adx(bars: list[dict], period: int = 14) -> list[float]:
    """Simplified ADX computation."""
    if len(bars) < 2 * period + 1:
        return [float("nan")] * len(bars)
    plus_dm = []
    minus_dm = []
    tr_list = []
    for i in range(1, len(bars)):
        h = bars[i]["high"]
        l = bars[i]["low"]
        ph = bars[i - 1]["high"]
        pl = bars[i - 1]["low"]
        pc = bars[i - 1]["close"]
        up = h - ph
        down = pl - l
        plus_dm.append(up if up > down and up > 0 else 0)
        minus_dm.append(down if down > up and down > 0 else 0)
        tr_list.append(max(h - l, abs(h - pc), abs(l - pc)))

    # Smoothed values
    sm_tr = sum(tr_list[:period])
    sm_plus = sum(plus_dm[:period])
    sm_minus = sum(minus_dm[:period])

    dx_values = []
    for i in range(period, len(tr_list)):
        if i > period:
            sm_tr = sm_tr - sm_tr / period + tr_list[i]
            sm_plus = sm_plus - sm_plus / period + plus_dm[i]
            sm_minus = sm_minus - sm_minus / period + minus_dm[i]

        di_plus = (sm_plus / sm_tr * 100) if sm_tr > 0 else 0
        di_minus = (sm_minus / sm_tr * 100) if sm_tr > 0 else 0
        di_sum = di_plus + di_minus
        dx = abs(di_plus - di_minus) / di_sum * 100 if di_sum > 0 else 0
        dx_values.append(dx)

    # ADX = smoothed DX
    adx = [float("nan")] * (period + 1)  # offset for the first TR calc
    if len(dx_values) >= period:
        adx_val = sum(dx_values[:period]) / period
        adx.extend([float("nan")] * (period - 1))
        adx.append(adx_val)
        for i in range(period, len(dx_values)):
            adx_val = (adx_val * (period - 1) + dx_values[i]) / period
            adx.append(adx_val)
    else:
        adx.extend([float("nan")] * len(dx_values))

    # Pad to match bars length
    while len(adx) < len(bars):
        adx.append(adx[-1] if adx and not math.isnan(adx[-1]) else float("nan"))
    return adx[:len(bars)]


def _compute_bb(closes: list[float], period: int = 20, std_mult: float = 2.0):
    """Compute Bollinger Bands: (upper, middle, lower) lists."""
    upper, middle, lower = [], [], []
    for i in range(len(closes)):
        if i < period - 1:
            upper.append(float("nan"))
            middle.append(float("nan"))
            lower.append(float("nan"))
            continue
        window = closes[i - period + 1: i + 1]
        mean = sum(window) / period
        std = (sum((x - mean) ** 2 for x in window) / period) ** 0.5
        middle.append(mean)
        upper.append(mean + std_mult * std)
        lower.append(mean - std_mult * std)
    return upper, middle, lower


def _compute_donchian(bars: list[dict], period: int = 20):
    """Compute Donchian channel: (upper, lower) lists."""
    upper, lower = [], []
    for i in range(len(bars)):
        if i < period:
            upper.append(float("nan"))
            lower.append(float("nan"))
            continue
        window = bars[i - period: i]
        upper.append(max(b["high"] for b in window))
        lower.append(min(b["low"] for b in window))
    return upper, lower


def strategy_signal_fn(strategy_id: str) -> callable:
    """Create a signal_fn callback for the backtest engine from a strategy ID."""

    if strategy_id == "trend_rider":
        return _trend_rider_signal
    elif strategy_id == "mean_reverter":
        return _mean_reverter_signal
    elif strategy_id == "breakout_hunter":
        return _breakout_hunter_signal
    elif strategy_id == "score_v3":
        return _score_v3_signal
    else:
        raise ValueError(f"Unknown strategy: {strategy_id}")


def _trend_rider_signal(ohlcv: list[Mapping[str, Any]]) -> dict:
    """EMA 20/50 crossover + RSI + ADX filter."""
    if len(ohlcv) < 51:
        return {"direction": "FLAT", "atr": 0.0}

    closes = [float(b["close"]) for b in ohlcv]
    ema20 = _compute_ema(closes, 20)
    ema50 = _compute_ema(closes, 50)
    rsi = _compute_rsi(closes, 14)
    atr = _compute_atr(ohlcv, 14)
    adx = _compute_adx(ohlcv, 14)

    i = len(ohlcv) - 1
    if any(math.isnan(x) for x in [ema20[i], ema50[i], rsi[i], atr[i]]):
        return {"direction": "FLAT", "atr": 0.0}

    adx_val = adx[i] if i < len(adx) and not math.isnan(adx[i]) else 0

    # ADX filter: need trend strength >= 15
    if adx_val < 15:
        return {"direction": "FLAT", "atr": 0.0}

    # EMA crossover
    if ema20[i] > ema50[i] and ema20[i - 1] <= ema50[i - 1]:
        if 40 <= rsi[i] <= 70:  # Not overbought
            return {"direction": "LONG", "atr": atr[i], "score": min(adx_val / 40, 1.0)}
    elif ema20[i] < ema50[i] and ema20[i - 1] >= ema50[i - 1]:
        if 30 <= rsi[i] <= 60:  # Not oversold
            return {"direction": "SHORT", "atr": atr[i], "score": min(adx_val / 40, 1.0)}

    return {"direction": "FLAT", "atr": 0.0}


def _mean_reverter_signal(ohlcv: list[Mapping[str, Any]]) -> dict:
    """Bollinger Band touch + RSI extreme + low ADX."""
    if len(ohlcv) < 30:
        return {"direction": "FLAT", "atr": 0.0}

    closes = [float(b["close"]) for b in ohlcv]
    upper, middle, lower = _compute_bb(closes, 20, 2.0)
    rsi = _compute_rsi(closes, 14)
    atr = _compute_atr(ohlcv, 14)
    adx = _compute_adx(ohlcv, 14)

    i = len(ohlcv) - 1
    if any(math.isnan(x) for x in [upper[i], lower[i], rsi[i], atr[i]]):
        return {"direction": "FLAT", "atr": 0.0}

    adx_val = adx[i] if i < len(adx) and not math.isnan(adx[i]) else 50

    # Need ranging market: ADX < 30
    if adx_val >= 30:
        return {"direction": "FLAT", "atr": 0.0}

    c = closes[i]
    # Buy at lower band with oversold RSI
    if c <= lower[i] and rsi[i] < 35:
        return {"direction": "LONG", "atr": atr[i], "score": 0.7}
    # Sell at upper band with overbought RSI
    elif c >= upper[i] and rsi[i] > 65:
        return {"direction": "SHORT", "atr": atr[i], "score": 0.7}

    return {"direction": "FLAT", "atr": 0.0}


def _breakout_hunter_signal(ohlcv: list[Mapping[str, Any]]) -> dict:
    """Donchian channel breakout."""
    if len(ohlcv) < 25:
        return {"direction": "FLAT", "atr": 0.0}

    closes = [float(b["close"]) for b in ohlcv]
    don_upper, don_lower = _compute_donchian(ohlcv, 20)
    atr = _compute_atr(ohlcv, 14)

    i = len(ohlcv) - 1
    if any(math.isnan(x) for x in [don_upper[i], don_lower[i], atr[i]]):
        return {"direction": "FLAT", "atr": 0.0}

    c = closes[i]
    prev_c = closes[i - 1] if i > 0 else c

    # Breakout above upper channel
    if c > don_upper[i] and prev_c <= don_upper[i - 1]:
        return {"direction": "LONG", "atr": atr[i], "score": 0.8}
    # Breakout below lower channel
    elif c < don_lower[i] and prev_c >= don_lower[i - 1]:
        return {"direction": "SHORT", "atr": atr[i], "score": 0.8}

    return {"direction": "FLAT", "atr": 0.0}


def _score_v3_signal(ohlcv: list[Mapping[str, Any]]) -> dict:
    """Multi-factor scoring — simplified version for backtesting."""
    if len(ohlcv) < 51:
        return {"direction": "FLAT", "atr": 0.0}

    closes = [float(b["close"]) for b in ohlcv]
    ema20 = _compute_ema(closes, 20)
    ema50 = _compute_ema(closes, 50)
    rsi = _compute_rsi(closes, 14)
    atr = _compute_atr(ohlcv, 14)
    adx = _compute_adx(ohlcv, 14)

    i = len(ohlcv) - 1
    if any(math.isnan(x) for x in [ema20[i], ema50[i], rsi[i], atr[i]]):
        return {"direction": "FLAT", "atr": 0.0}

    adx_val = adx[i] if i < len(adx) and not math.isnan(adx[i]) else 20

    # Multi-factor score
    score = 0.0
    direction = "FLAT"

    # Trend alignment (EMA)
    if ema20[i] > ema50[i]:
        score += 0.3
        direction = "LONG"
    elif ema20[i] < ema50[i]:
        score += 0.3
        direction = "SHORT"

    # RSI confirmation
    if direction == "LONG" and 40 <= rsi[i] <= 65:
        score += 0.2
    elif direction == "SHORT" and 35 <= rsi[i] <= 60:
        score += 0.2

    # ADX strength
    if adx_val >= 20:
        score += min(adx_val / 50, 0.3)

    # Momentum
    if len(closes) >= 5:
        mom = (closes[i] - closes[i - 5]) / closes[i - 5] * 100
        if abs(mom) > 0.1:
            score += 0.2

    if score >= 0.6:
        return {"direction": direction, "atr": atr[i], "score": score}

    return {"direction": "FLAT", "atr": 0.0}


# Available strategies for the backtest UI
BACKTEST_STRATEGIES = {
    "trend_rider": {
        "name": "Trend Rider",
        "default_config": {"sl_atr_mult": 1.5, "tp_atr_mult": 3.0, "min_score": 0.5},
    },
    "mean_reverter": {
        "name": "Mean Reverter",
        "default_config": {"sl_atr_mult": 1.0, "tp_atr_mult": 2.0, "min_score": 0.5},
    },
    "breakout_hunter": {
        "name": "Breakout Hunter",
        "default_config": {"sl_atr_mult": 2.0, "tp_atr_mult": 4.0, "min_score": 0.5},
    },
    "score_v3": {
        "name": "Score v3",
        "default_config": {"sl_atr_mult": 1.5, "tp_atr_mult": 2.5, "min_score": 0.6},
    },
}


__all__ = ["strategy_signal_fn", "BACKTEST_STRATEGIES"]
