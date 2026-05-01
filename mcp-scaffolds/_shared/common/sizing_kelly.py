"""Kelly fraction sizing escalado por score y win rate reciente.

Reemplaza el risk_pct fijo (1.0) por un valor dinámico:

  - Trades sobre combos PROVEN (expectancy positiva, n suficiente) → más risk
  - Trades sobre combos UNCERTAIN → risk base reducido
  - Trades sobre combos NEGATIVE → risk = 0 (no se ejecuta)
  - Score 90+ con WR alto → multiplier amplio (1.5x base)
  - Score 50 con WR bajo → multiplier mínimo (0.2x)

Fórmula:
  ``kelly_quarter = (WR × avg_win_R - (1-WR) × |avg_loss_R|) / |avg_loss_R|  × 0.25``
  ``score_mult = clamp((score/100)^1.5, 0.2, 1.5)``
  ``final_risk_pct = base_risk_pct × kelly_quarter × score_mult``
  clampeado a [0.0, MAX_RISK_PER_TRADE_PCT].

Uso desde auto_trader: reemplazar la línea
  ``risk_pct=args.risk_pct``
con
  ``risk_pct=sizing_kelly.compute(args.risk_pct, score, expectancy_stats)``

Si la combo no tiene historia suficiente, usa el ``base_risk_pct`` reducido
por score (defaults seguros).
"""
from __future__ import annotations


def compute(*, base_risk_pct: float, score: float,
            expectancy_stats: dict | None = None,
            max_risk_pct: float = 5.0) -> dict:
    """Calcula risk_pct dinámico para un trade dado.

    Args:
      base_risk_pct: risk pct configurado (típicamente 1.0)
      score: score 0..100 del setup (analysis-mcp)
      expectancy_stats: dict con keys n, wr, avg_win_r, avg_loss_r, expectancy_r
        — del expectancy_tracker. None si no hay historia.
      max_risk_pct: límite duro

    Retorna ``{"risk_pct": float, "components": {...}}`` para audit.
    """
    base = max(0.0, float(base_risk_pct))
    sc = max(0.0, min(100.0, float(score)))

    # Score multiplier: ^1.5 favorece scores altos
    score_mult = (sc / 100.0) ** 1.5
    score_mult = max(0.2, min(1.5, score_mult)) if sc > 0 else 0.0

    # Kelly multiplier
    kelly_mult = 1.0  # default si no hay datos
    kelly_reason = "NO_HISTORY"
    n = 0
    if expectancy_stats:
        n = int(expectancy_stats.get("n", 0))
        wr = float(expectancy_stats.get("wr", 0.0))
        avg_win = float(expectancy_stats.get("avg_win_r", 0.0))
        avg_loss = abs(float(expectancy_stats.get("avg_loss_r", 0.0)))
        expectancy = float(expectancy_stats.get("expectancy_r", 0.0))

        # Edge: expectancy negativo → 0 risk (no abrir)
        if n >= 15 and expectancy <= -0.05:
            return {
                "risk_pct": 0.0,
                "components": {
                    "base": base, "score_mult": round(score_mult, 3),
                    "kelly_mult": 0.0, "n": n,
                    "expectancy_r": round(expectancy, 3),
                    "reason": "NEGATIVE_EXPECTANCY",
                },
            }

        if n >= 15 and avg_loss > 0:
            # Full Kelly: f = (WR × avg_win - (1-WR) × avg_loss) / avg_loss / avg_win
            # Quarter Kelly conservador (recommended in literature): full × 0.25
            full = ((wr * avg_win) - ((1 - wr) * avg_loss)) / avg_loss
            kelly_mult = max(0.25, min(1.5, full * 0.25))
            kelly_reason = "PROVEN" if expectancy > 0.10 else "UNCERTAIN"
        else:
            kelly_mult = 0.5  # poca data → riesgo a la mitad
            kelly_reason = "INSUFFICIENT_N"

    final = base * score_mult * kelly_mult
    final = max(0.0, min(max_risk_pct, final))

    return {
        "risk_pct": round(final, 4),
        "components": {
            "base": base,
            "score": sc,
            "score_mult": round(score_mult, 3),
            "kelly_mult": round(kelly_mult, 3),
            "n": n,
            "expectancy_r": round(float((expectancy_stats or {}).get("expectancy_r", 0)), 3),
            "reason": kelly_reason,
        },
    }


def notional_max_lots(*, balance: float, current_price: float,
                      contract_size: float = 100_000.0,
                      max_notional_pct: float = 50.0) -> float:
    """Calcula los lots máximos basado en NOCIONAL (precio × contrato), no en
    un cap absoluto.

    Usar para que ETHUSD/BTCUSD/XAUUSD no exploten la cuenta:
      EURUSD 1 lot = 100_000 EUR ≈ $108k → max_notional 50% de $200 = $100 →
        max_lots = 100 / 108_000 = 0.00092 → debajo del min_lot = 0 (no operar)
      BTCUSD 1 lot = 1 BTC ≈ $77k → 100 / 77000 = 0.00130

    Args:
      balance: balance USD
      current_price: precio del símbolo
      contract_size: tamaño del contrato (FX = 100k, BTCUSD = 1, XAUUSD = 100, etc.)
      max_notional_pct: % del balance que el nocional puede ocupar
    """
    if balance <= 0 or current_price <= 0 or contract_size <= 0:
        return 0.0
    max_notional = balance * (max_notional_pct / 100.0)
    notional_per_lot = current_price * contract_size
    if notional_per_lot <= 0:
        return 0.0
    return round(max_notional / notional_per_lot, 4)


# Contract sizes conocidos (override por símbolo). Para FX standard = 100k.
KNOWN_CONTRACT_SIZES = {
    "BTCUSD": 1.0,
    "ETHUSD": 1.0,
    "BTCUSDT": 1.0,
    "ETHUSDT": 1.0,
    "XAUUSD": 100.0,   # 1 lot = 100 oz
    "XAGUSD": 5000.0,  # 1 lot = 5000 oz silver
    # FX standard
    "EURUSD": 100_000.0,
    "GBPUSD": 100_000.0,
    "USDJPY": 100_000.0,
    "AUDUSD": 100_000.0,
    "NZDUSD": 100_000.0,
    "USDCAD": 100_000.0,
    "USDCHF": 100_000.0,
    "EURJPY": 100_000.0,
    "GBPJPY": 100_000.0,
}


def contract_size_for(symbol: str) -> float:
    return KNOWN_CONTRACT_SIZES.get((symbol or "").upper(), 100_000.0)
