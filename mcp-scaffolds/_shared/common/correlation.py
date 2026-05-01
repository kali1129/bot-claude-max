"""Correlation matrix entre símbolos del watchlist.

Para evitar que el bot abra 5 trades correlacionados creyendo que está
diversificado (ej. 4 BUYs USDxxx = una sola apuesta direccional con 4x leverage).

Implementación pragmática: una matrix HARDCODED basada en correlaciones
empíricas conocidas del mercado (D1 returns, últimos 12 meses). Se puede
recalcular offline con un script y reemplazar el dict.

Uso:
  ``would_concentrate(new_symbol, new_side, open_positions, threshold=0.65)``
  → True si abrir esta posición duplica exposición ya existente.
"""
from __future__ import annotations

# Correlación 1.0 = movimientos idénticos. -1.0 = opuestos. 0 = independientes.
# Source: empírico D1 returns 2024-2025; redondeado a 0.05.
# Cuando NO está la pareja en la matrix, se asume corr=0 (símbolos no relacionados).
CORRELATION_MATRIX: dict[tuple[str, str], float] = {
    # USD majors (entre sí)
    ("EURUSD", "GBPUSD"):  0.75,
    ("EURUSD", "AUDUSD"):  0.65,
    ("EURUSD", "NZDUSD"):  0.60,
    ("GBPUSD", "AUDUSD"):  0.60,
    ("AUDUSD", "NZDUSD"):  0.85,
    # USD majors anti-corr con USDxxx
    ("EURUSD", "USDJPY"): -0.55,
    ("EURUSD", "USDCHF"): -0.90,
    ("EURUSD", "USDCAD"): -0.50,
    ("GBPUSD", "USDJPY"): -0.45,
    ("GBPUSD", "USDCHF"): -0.65,
    ("AUDUSD", "USDJPY"): -0.40,
    # JPY crosses
    ("EURJPY", "GBPJPY"):  0.70,
    ("EURJPY", "USDJPY"):  0.65,
    ("GBPJPY", "USDJPY"):  0.60,
    # XAUUSD (gold) vs USD: anti
    ("XAUUSD", "USDJPY"): -0.50,
    ("XAUUSD", "EURUSD"):  0.45,
    ("XAUUSD", "GBPUSD"):  0.30,
    # Crypto
    ("BTCUSD", "ETHUSD"):  0.85,
    # Cross commodities
    ("XAUUSD", "BTCUSD"):  0.20,  # variable según régimen macro
}


def correlation(sym_a: str, sym_b: str) -> float:
    """Retorna la correlación entre dos símbolos. 0 si no está mapeada."""
    a = (sym_a or "").upper()
    b = (sym_b or "").upper()
    if a == b:
        return 1.0
    if (a, b) in CORRELATION_MATRIX:
        return CORRELATION_MATRIX[(a, b)]
    if (b, a) in CORRELATION_MATRIX:
        return CORRELATION_MATRIX[(b, a)]
    return 0.0


def effective_direction(sym_a: str, side_a: str, sym_b: str, side_b: str) -> int:
    """Si A y B están altamente correlacionados, qué dirección efectiva
    representa A respecto a B?

      - 1 si ambos generan exposición en la misma dirección (concentración)
      - -1 si se cancelan (hedging)
      - 0 si no están relacionados

    Se usa: ``effective_direction("EURUSD","buy","USDJPY","sell")``
      EURUSD buy + USDJPY sell ambos son "USD bearish" → corr -0.55, side opuesta
      → 0.55 × -1 × ... la lógica es:

        eff_dir = corr × dir_a × dir_b
      EURUSD(buy=+1) USDJPY(sell=-1): corr -0.55 × 1 × -1 = +0.55 → mismo lado
    """
    corr = correlation(sym_a, sym_b)
    if corr == 0:
        return 0
    da = 1 if side_a == "buy" else -1
    db = 1 if side_b == "buy" else -1
    eff = corr * da * db
    return 1 if eff > 0 else (-1 if eff < 0 else 0)


def would_concentrate(*, new_symbol: str, new_side: str,
                      open_positions: list,
                      threshold: float = 0.65) -> dict | None:
    """¿Abrir esta posición duplica exposición ya tomada?

    Retorna ``None`` si NO concentra. Si sí, retorna dict con info
    para audit + rejection.
    """
    new_sym = (new_symbol or "").upper()
    new_dir = 1 if new_side == "buy" else -1
    for p in open_positions or []:
        sym = (p.get("symbol") or "").upper()
        side = (p.get("side") or "").lower()
        if sym == new_sym:
            return {"reason": "DUPLICATE_SYMBOL", "with": sym}
        corr = correlation(new_sym, sym)
        if abs(corr) < threshold:
            continue
        existing_dir = 1 if side == "buy" else -1
        # Misma dirección efectiva si corr × signs > 0
        if corr * new_dir * existing_dir > 0:
            return {
                "reason": "CORRELATED_CONCENTRATION",
                "with": sym, "with_side": side,
                "corr": round(corr, 2),
                "detail": (
                    f"{new_sym} {new_side} concentra exposición con "
                    f"{sym} {side} (corr={corr:+.2f}, threshold={threshold})"
                ),
            }
    return None
