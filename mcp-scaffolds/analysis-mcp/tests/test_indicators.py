"""Property-style tests for the indicators."""
import math

import numpy as np
import pytest

from lib.indicators import ema, sma, rsi, atr, macd, bollinger, indicators_snapshot


def _bars(closes):
    """Synthesise OHLCV from a list of closes (high=close+0.001, low=close-0.001)."""
    return [
        {"time": f"t{i}", "open": c, "high": c + 0.001, "low": c - 0.001,
         "close": c, "volume": 100}
        for i, c in enumerate(closes)
    ]


def test_ema_monotonic_on_monotonic_input():
    vals = np.arange(50, dtype=float)
    e = ema(vals, 20)
    assert all(e[i] <= e[i + 1] for i in range(len(e) - 1))


def test_sma_basic():
    vals = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    s = sma(vals, 3)
    assert math.isnan(s[0])
    assert math.isnan(s[1])
    assert s[2] == 2.0
    assert s[4] == 4.0


def test_rsi_bounded_0_100():
    np.random.seed(0)
    vals = np.cumsum(np.random.randn(200))
    r = rsi(vals, 14)
    r_clean = r[~np.isnan(r)]
    assert all(0.0 <= v <= 100.0 for v in r_clean)


def test_rsi_extreme_uptrend_high():
    vals = np.arange(50, dtype=float)
    r = rsi(vals, 14)
    # Pure uptrend → no losses → RSI 100.
    assert r[-1] == pytest.approx(100.0, abs=1e-6)


def test_atr_positive():
    np.random.seed(1)
    n = 100
    high = np.cumsum(np.random.rand(n)) + 100
    low = high - np.random.rand(n)
    close = (high + low) / 2
    a = atr(high, low, close, 14)
    a_clean = a[~np.isnan(a)]
    assert all(v >= 0 for v in a_clean)


def test_macd_returns_three_arrays():
    vals = np.cumsum(np.random.randn(80))
    line, sig, hist = macd(vals)
    assert len(line) == len(vals)
    assert len(sig) == len(vals)
    assert len(hist) == len(vals)


def test_bollinger_upper_above_lower():
    vals = np.cumsum(np.random.randn(100)) + 50
    u, m, l = bollinger(vals, 20, 2.0)
    valid = ~(np.isnan(u) | np.isnan(l))
    assert all(u[valid] >= l[valid])


def test_snapshot_short_input():
    res = indicators_snapshot([{"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}])
    assert "error" in res


def test_snapshot_full():
    closes = [1.0850 + 0.0001 * i for i in range(60)]
    bars = _bars(closes)
    snap = indicators_snapshot(bars)
    assert snap["n_bars"] == 60
    assert snap["close"][0] is not None
    assert snap["ema20"][0] is not None
    assert snap["rsi14"][0] is not None
