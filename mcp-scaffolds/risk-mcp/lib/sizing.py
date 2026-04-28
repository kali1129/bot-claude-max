"""Position sizing — how many lots fit a given $ risk budget."""
from __future__ import annotations

import math

from rules import MAX_RISK_PER_TRADE_PCT


def calc_position_size(
    balance: float,
    risk_pct: float,
    entry: float,
    sl: float,
    tick_value: float,
    tick_size: float,
    lot_step: float = 0.01,
    min_lot: float = 0.01,
    max_lot: float = 0.5,
) -> dict:
    if entry == sl:
        return {"error": "ENTRY_EQ_SL", "lots": 0.0,
                "warnings": ["entry == sl — invalid setup"]}
    if balance <= 0 or risk_pct <= 0 or tick_value <= 0 or tick_size <= 0:
        return {"error": "BAD_INPUT", "lots": 0.0,
                "warnings": ["balance/risk_pct/tick_value/tick_size must be > 0"]}

    risk_dollars = balance * (risk_pct / 100.0)
    sl_distance = abs(entry - sl)
    sl_ticks = sl_distance / tick_size
    dollars_per_lot = sl_ticks * tick_value
    if dollars_per_lot <= 0:
        return {"error": "ZERO_TICK_VALUE", "lots": 0.0, "warnings": []}

    raw_lots = risk_dollars / dollars_per_lot

    warnings = []
    if raw_lots < min_lot:
        # Don't silently floor to min_lot — that breaks the 1% rule.
        cost_at_min = min_lot * sl_ticks * tick_value
        warnings.append(
            f"Riesgo solicitado (${risk_dollars:.2f}) < lotaje mínimo "
            f"({min_lot} = ${cost_at_min:.2f}). Aleja el SL o salta el trade."
        )
        return {
            "lots": 0.0,
            "raw_lots": round(raw_lots, 6),
            "risk_dollars": 0.0,
            "risk_pct_actual": 0.0,
            "sl_distance": round(sl_distance, 5),
            "sl_ticks": round(sl_ticks, 2),
            "warnings": warnings,
        }

    # FLOOR (not round) so lots never go above the risk budget. round()
    # uses banker's rounding which can push 0.0349 lots up to 0.04, blowing
    # past the 1% cap by 14% on a $200 account. Always round DOWN.
    snapped = round(math.floor(raw_lots / lot_step) * lot_step, 4)
    capped = round(min(snapped, max_lot), 4)
    actual_risk = capped * sl_ticks * tick_value
    actual_risk_pct = actual_risk / balance * 100

    if capped < snapped:
        warnings.append(f"Lotaje recortado de {snapped} a {capped} (cap {max_lot})")
    if risk_pct > MAX_RISK_PER_TRADE_PCT:
        warnings.append(f"⚠ Riesgo {risk_pct}% excede regla del {MAX_RISK_PER_TRADE_PCT}%")
    if sl_distance < entry * 0.0005:
        warnings.append("SL muy cerca, riesgo de stop hunt")

    return {
        "lots": capped,
        "raw_lots": round(raw_lots, 6),
        "risk_dollars": round(actual_risk, 2),
        "risk_pct_actual": round(actual_risk_pct, 3),
        "sl_distance": round(sl_distance, 5),
        "sl_ticks": round(sl_ticks, 2),
        "warnings": warnings,
    }
