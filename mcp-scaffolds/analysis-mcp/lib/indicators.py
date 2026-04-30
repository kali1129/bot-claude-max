"""Pure-numpy technical indicators. No state, no network.

Each function takes a list of OHLCV dicts and returns a dict (or list) of
numbers. The MCP tools wrap these.
"""
from __future__ import annotations

from typing import List, Dict

import numpy as np


def _close(ohlcv: List[Dict]) -> np.ndarray:
    return np.array([float(b["close"]) for b in ohlcv], dtype=float)


def _high(ohlcv: List[Dict]) -> np.ndarray:
    return np.array([float(b["high"]) for b in ohlcv], dtype=float)


def _low(ohlcv: List[Dict]) -> np.ndarray:
    return np.array([float(b["low"]) for b in ohlcv], dtype=float)


def ema(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) == 0:
        return np.array([])
    alpha = 2.0 / (period + 1)
    out = np.empty_like(values)
    out[0] = values[0]
    for i in range(1, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def sma(values: np.ndarray, period: int) -> np.ndarray:
    if len(values) < period:
        return np.full(len(values), np.nan)
    cumsum = np.cumsum(values, dtype=float)
    out = np.full(len(values), np.nan)
    out[period - 1:] = (cumsum[period - 1:] - np.concatenate([[0], cumsum[:-period]])) / period
    return out


def rsi(values: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's RSI."""
    if len(values) < period + 1:
        return np.full(len(values), np.nan)
    deltas = np.diff(values)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    out = np.full(len(values), np.nan)
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - 100.0 / (1.0 + rs)
    for i in range(period + 1, len(values)):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        if avg_loss == 0:
            out[i] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i] = 100.0 - 100.0 / (1.0 + rs)
    return out


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    if len(close) < 2:
        return np.full(len(close), np.nan)
    prev_close = np.concatenate([[close[0]], close[:-1]])
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    out = np.full(len(close), np.nan)
    if len(tr) >= period:
        out[period - 1] = np.mean(tr[:period])
        for i in range(period, len(tr)):
            out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def macd(values: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9):
    e_fast = ema(values, fast)
    e_slow = ema(values, slow)
    line = e_fast - e_slow
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def bollinger(values: np.ndarray, period: int = 20, mult: float = 2.0):
    mid = sma(values, period)
    out_upper = np.full(len(values), np.nan)
    out_lower = np.full(len(values), np.nan)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1:i + 1]
        std = np.std(window, ddof=0)
        out_upper[i] = mid[i] + mult * std
        out_lower[i] = mid[i] - mult * std
    return out_upper, mid, out_lower




def adx(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average Directional Index (ADX). Measures trend strength (0-100).
    ADX > 25 = trending, ADX < 20 = ranging."""
    if len(close) < period + 2:
        return np.full(len(close), np.nan)

    # +DM / -DM
    high_diff = np.diff(high)
    low_diff = -np.diff(low)
    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0.0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0.0)

    # True Range
    prev_close = close[:-1]
    tr = np.maximum(high[1:] - low[1:],
                    np.maximum(np.abs(high[1:] - prev_close),
                               np.abs(low[1:] - prev_close)))

    # Smooth with Wilder's method (same as EMA with alpha = 1/period)
    def _wilder_smooth(arr, p):
        out = np.full(len(arr), np.nan)
        out[p - 1] = np.sum(arr[:p])
        for i in range(p, len(arr)):
            out[i] = out[i - 1] - out[i - 1] / p + arr[i]
        return out

    smooth_tr = _wilder_smooth(tr, period)
    smooth_plus = _wilder_smooth(plus_dm, period)
    smooth_minus = _wilder_smooth(minus_dm, period)

    # +DI / -DI
    plus_di = 100.0 * smooth_plus / np.where(smooth_tr > 0, smooth_tr, 1.0)
    minus_di = 100.0 * smooth_minus / np.where(smooth_tr > 0, smooth_tr, 1.0)

    # DX
    di_sum = plus_di + minus_di
    dx = 100.0 * np.abs(plus_di - minus_di) / np.where(di_sum > 0, di_sum, 1.0)

    # ADX = Wilder smooth of DX
    adx_out = np.full(len(close), np.nan)
    # First ADX value: average of first 'period' DX values
    dx_start = period - 1  # first valid DX index in the diff array
    if dx_start + period <= len(dx):
        first_valid = [dx[i] for i in range(dx_start, dx_start + period) if np.isfinite(dx[i])]
        if first_valid:
            adx_out[dx_start + period] = np.mean(first_valid)
            for i in range(dx_start + period + 1, len(dx) + 1):
                if i < len(adx_out) and i - 1 < len(dx) and np.isfinite(dx[i - 1]):
                    adx_out[i] = (adx_out[i - 1] * (period - 1) + dx[i - 1]) / period

    return adx_out


def donchian(high: np.ndarray, low: np.ndarray, period: int = 20):
    """Donchian Channel: highest high and lowest low over N periods.
    Returns (upper, lower, middle) arrays."""
    n = len(high)
    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    for i in range(period, n):
        upper[i] = float(np.max(high[i - period:i]))
        lower[i] = float(np.min(low[i - period:i]))
    middle = (upper + lower) / 2.0
    return upper, lower, middle


def indicators_snapshot(ohlcv: List[Dict]) -> dict:
    """Returns the latest value (and previous) of every indicator."""
    if len(ohlcv) < 2:
        return {"error": "NOT_ENOUGH_BARS", "n": len(ohlcv)}
    close = _close(ohlcv)
    high = _high(ohlcv)
    low = _low(ohlcv)

    e20 = ema(close, 20)
    e50 = ema(close, 50)
    e200 = ema(close, 200) if len(close) >= 200 else np.full(len(close), np.nan)
    rsi14 = rsi(close, 14)
    atr14 = atr(high, low, close, 14)
    macd_line, macd_sig, macd_hist = macd(close)
    bb_u, bb_m, bb_l = bollinger(close)

    def last2(arr):
        if len(arr) == 0:
            return None, None
        return (
            float(arr[-1]) if not np.isnan(arr[-1]) else None,
            float(arr[-2]) if len(arr) > 1 and not np.isnan(arr[-2]) else None,
        )

    return {
        "n_bars": len(ohlcv),
        "close": last2(close),
        "ema20": last2(e20),
        "ema50": last2(e50),
        "ema200": last2(e200),
        "rsi14": last2(rsi14),
        "atr14": last2(atr14),
        "macd": {
            "line": last2(macd_line),
            "signal": last2(macd_sig),
            "histogram": last2(macd_hist),
        },
        "bollinger": {
            "upper": last2(bb_u),
            "middle": last2(bb_m),
            "lower": last2(bb_l),
        },
    }
