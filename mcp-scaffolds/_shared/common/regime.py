"""Regime detector — clasifica el estado del mercado por símbolo.

Cada estrategia declara qué regímenes le sirven, y el scanner filtra antes
de proponer signals. Mean_reverter solo en RANGE; trend_rider solo en
STRONG_TREND_*; breakout_hunter solo en EXPANSION_FROM_COMPRESSION.

Este módulo es PURO (no toca MT5 ni filesystem) — recibe OHLCV y retorna
veredict. La obtención de OHLCV vive en el caller (auto_trader vía
trading.get_rates).

Inputs esperados:
  - ``bars_d1``: lista de dicts con high/low/close — al menos 50 barras D1
  - ``bars_h4``: lista de dicts con high/low/close — al menos 50 barras H4
  - ``current_price``: precio actual

Output: dict con régimen y métricas.

Regímenes:
  - STRONG_TREND_UP / STRONG_TREND_DOWN: ADX > 25 + price vs EMA200 alineado
  - WEAK_TREND_UP / WEAK_TREND_DOWN: ADX 15-25 + EMA50 alineada
  - RANGE: ADX < 15 + BB width baja-media + price oscila
  - COMPRESSION: BB width en percentil bottom 25% (squeeze)
  - EXPANSION_FROM_COMPRESSION: BB width acaba de salir de bottom 25% en últimas 5 barras
  - UNKNOWN: datos insuficientes
"""
from __future__ import annotations

import math
from typing import Iterable

# Constantes de clasificación (tunables vía env si quieren)
_ADX_STRONG = 25.0
_ADX_WEAK = 15.0
_BB_PERIOD = 20
_BB_STD = 2.0
_BB_HISTORY = 50  # mirar últimas 50 barras para percentile de width


def _ema(values: list, period: int) -> list:
    """EMA simple. Seed = SMA(period). Devuelve list del mismo largo;
    los primeros period-1 valores son ``None``."""
    n = len(values)
    if n < period:
        return [None] * n
    out = [None] * (period - 1)
    seed = sum(values[:period]) / period
    out.append(seed)
    k = 2.0 / (period + 1)
    prev = seed
    for v in values[period:]:
        cur = v * k + prev * (1 - k)
        out.append(cur)
        prev = cur
    return out


def _adx(highs: list, lows: list, closes: list, period: int = 14) -> float | None:
    """ADX clásico de Wilder. Retorna el último valor o None si insuficiente data."""
    n = len(closes)
    if n < period * 2 + 1:
        return None
    # True Range, +DM, -DM
    tr_list = []
    pdm_list = []
    ndm_list = []
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i - 1]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        pdm = up if (up > dn and up > 0) else 0.0
        ndm = dn if (dn > up and dn > 0) else 0.0
        tr_list.append(tr)
        pdm_list.append(pdm)
        ndm_list.append(ndm)
    if len(tr_list) < period:
        return None
    # Wilder smoothing
    atr = sum(tr_list[:period])
    pdm = sum(pdm_list[:period])
    ndm = sum(ndm_list[:period])
    dx_list = []
    for i in range(period, len(tr_list)):
        atr = atr - (atr / period) + tr_list[i]
        pdm = pdm - (pdm / period) + pdm_list[i]
        ndm = ndm - (ndm / period) + ndm_list[i]
        if atr == 0:
            continue
        pdi = 100 * pdm / atr
        ndi = 100 * ndm / atr
        denom = (pdi + ndi)
        dx = (100 * abs(pdi - ndi) / denom) if denom > 0 else 0
        dx_list.append(dx)
    if len(dx_list) < period:
        return None
    adx = sum(dx_list[:period]) / period
    for d in dx_list[period:]:
        adx = (adx * (period - 1) + d) / period
    return adx


def _bb_width(closes: list, period: int = _BB_PERIOD, k: float = _BB_STD) -> list:
    """Bollinger Band width (upper - lower) / mid, lista del mismo largo
    que ``closes``. Primeros period-1 son None."""
    out = [None] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1:i + 1]
        m = sum(window) / period
        var = sum((x - m) ** 2 for x in window) / period
        sd = math.sqrt(var)
        if m > 0:
            out[i] = (2 * k * sd) / m
    return out


def _percentile_rank(value: float, history: list) -> float:
    """Qué percentil ocupa ``value`` dentro de ``history`` (no-None values).
    Retorna en [0, 100]."""
    vals = [v for v in history if v is not None]
    if not vals:
        return 50.0
    below = sum(1 for v in vals if v < value)
    return below / len(vals) * 100.0


def detect(bars_d1: list, bars_h4: list, current_price: float) -> dict:
    """Detecta el régimen actual del símbolo.

    Lógica:
      1. Trend: ADX(14) D1 + posición vs EMA50/EMA200 D1
      2. Volatility: BB width D1 percentile vs últimos 50 días
      3. Combinar: STRONG_TREND si ADX>25 y aligned. RANGE si ADX<15. etc.

    Retorna ``{"regime": <str>, "details": {...}}``.
    """
    if not bars_d1 or len(bars_d1) < 50:
        return {"regime": "UNKNOWN",
                "details": {"reason": "insufficient_d1_bars",
                            "n": len(bars_d1) if bars_d1 else 0}}

    closes_d1 = [float(b["close"]) for b in bars_d1]
    highs_d1 = [float(b["high"]) for b in bars_d1]
    lows_d1 = [float(b["low"]) for b in bars_d1]

    adx_d1 = _adx(highs_d1, lows_d1, closes_d1, period=14)
    ema50 = _ema(closes_d1, 50)
    # EMA200 needs 200 bars; if no, fallback a EMA50
    ema200 = _ema(closes_d1, 200) if len(closes_d1) >= 200 else ema50
    bb_widths = _bb_width(closes_d1, _BB_PERIOD, _BB_STD)

    last = closes_d1[-1]
    e50 = ema50[-1] if ema50[-1] is not None else last
    e200 = ema200[-1] if ema200[-1] is not None else last
    bbw = bb_widths[-1]
    bbw_history = bb_widths[-_BB_HISTORY - 1:-1]  # excluye current
    bbw_pct = _percentile_rank(bbw, bbw_history) if bbw is not None else 50.0

    # Trend bias
    bias = 0
    if last > e50 and e50 > e200:
        bias = 1  # alcista
    elif last < e50 and e50 < e200:
        bias = -1  # bajista

    # Compresión / expansión
    in_compression = (bbw_pct < 25.0)
    # Expansión reciente: width subió rápido en últimas 5 barras desde compresión
    recent_widths = [w for w in bb_widths[-7:] if w is not None]
    expansion_from_compression = False
    if len(recent_widths) >= 5 and bbw is not None:
        prev_min = min(recent_widths[:-2])
        prev_min_pct = _percentile_rank(prev_min, bbw_history)
        if prev_min_pct < 25.0 and bbw_pct > 35.0:
            expansion_from_compression = True

    # Clasificación
    adx_v = adx_d1 or 0.0
    regime = "RANGE"
    if expansion_from_compression and bias != 0:
        regime = "EXPANSION_FROM_COMPRESSION"
    elif in_compression:
        regime = "COMPRESSION"
    elif adx_v >= _ADX_STRONG:
        regime = "STRONG_TREND_UP" if bias > 0 else \
                 ("STRONG_TREND_DOWN" if bias < 0 else "RANGE")
    elif adx_v >= _ADX_WEAK:
        regime = "WEAK_TREND_UP" if bias > 0 else \
                 ("WEAK_TREND_DOWN" if bias < 0 else "RANGE")

    return {
        "regime": regime,
        "details": {
            "adx_d1": round(adx_v, 2) if adx_d1 is not None else None,
            "ema50_d1": round(e50, 5),
            "ema200_d1": round(e200, 5),
            "bias": bias,
            "bb_width": round(bbw, 5) if bbw is not None else None,
            "bb_width_pct": round(bbw_pct, 1),
            "in_compression": in_compression,
            "expansion_from_compression": expansion_from_compression,
        },
    }


# Mapping per-strategy
STRATEGY_REGIMES: dict = {
    "trend_rider": {"STRONG_TREND_UP", "STRONG_TREND_DOWN",
                    "WEAK_TREND_UP", "WEAK_TREND_DOWN"},
    "breakout_hunter": {"EXPANSION_FROM_COMPRESSION", "COMPRESSION"},
    "mean_reverter": {"RANGE", "COMPRESSION"},
    "score_v3": {"STRONG_TREND_UP", "STRONG_TREND_DOWN",
                 "WEAK_TREND_UP", "WEAK_TREND_DOWN", "RANGE"},
    # UNKNOWN siempre se permite (data insuficiente — no bloqueamos por defecto)
}


def is_strategy_compatible(strategy_id: str, regime: str) -> bool:
    """¿La estrategia debe operar bajo este régimen?"""
    if regime == "UNKNOWN":
        return True  # default: no bloqueamos por falta de data
    valid = STRATEGY_REGIMES.get(strategy_id)
    if valid is None:
        return True  # estrategia no mapeada → no filtramos
    return regime in valid
