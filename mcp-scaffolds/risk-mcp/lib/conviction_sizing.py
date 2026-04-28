"""Dynamic conviction-based position sizing multiplier.

Port of xm-mt5-trading-platform/src/risk/conviction_sizing.py.

Pure function (no state, no IO). Returns a multiplier in [0.0, 1.25] that
the caller should multiply against the **base risk_pct** before sending
to `calc_position_size`. The hard rules in `_shared/rules.py`
(MAX_RISK_PER_TRADE_PCT, MAX_DAILY_LOSS_PCT, MAX_OPEN_POSITIONS, MIN_RR)
remain the true ceiling — this can only nudge sizing inside that envelope.

Tiers:
  HIGH conviction  (signal >= 0.65, opp >= 0.60, clean history)   → 1.10 – 1.25x
  MEDIUM conviction (middle range)                                  → 0.70 – 1.00x
  LOW conviction    (weak signal, bad context)                      → 0.25 – 0.50x
  BLOCKED           (4+ consecutive losses on symbol)               → 0.0x

Additional caps (most restrictive wins):
  - spread_ratio ≥ 1.0 (at the spread block threshold)            → cap 0.50x
  - spread_ratio ≥ 0.80                                            → cap 0.75x
  - spread_ratio ≥ 0.55                                            → cap 0.90x
  - session_quality below 1.0 linearly reduces toward 0.75x at 0
  - consecutive_symbol_losses >= 2                                 → hard cap 0.50x
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class ConvictionSizingResult:
    """Outcome of `compute_conviction_multiplier`."""

    multiplier: float          # applied to base risk_pct; range 0.0 – 1.25
    conviction_label: str      # LOW | MEDIUM | HIGH | BLOCKED
    size_label: str            # mínimo | estándar | alto | bloqueado
    reason: str                # one-line human-readable summary
    audit_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "multiplier": self.multiplier,
            "conviction_label": self.conviction_label,
            "size_label": self.size_label,
            "reason": self.reason,
            "audit": dict(self.audit_payload),
        }


def compute_conviction_multiplier(
    *,
    signal_strength: float,
    opportunity_score: float = 0.5,
    setup_score: float = 0.0,
    spread_ratio: float = 0.0,
    session_quality: float = 1.0,
    consecutive_symbol_losses: int = 0,
) -> ConvictionSizingResult:
    """Return a bounded sizing multiplier and conviction metadata."""
    s = max(0.0, min(float(signal_strength), 1.0))
    opp = max(0.0, min(float(opportunity_score), 1.0))
    setup = max(-0.25, min(float(setup_score), 0.15))
    spread = max(0.0, float(spread_ratio))
    session = max(0.0, min(float(session_quality), 1.0))
    consec = int(consecutive_symbol_losses)

    if consec >= 4:
        return ConvictionSizingResult(
            multiplier=0.0,
            conviction_label="BLOCKED",
            size_label="bloqueado",
            reason=f"símbolo bloqueado: {consec} pérdidas consecutivas",
            audit_payload=_audit(s, opp, setup, spread, session, consec, 0.0, "BLOCKED"),
        )

    base = s * 0.60 + opp * 0.40
    adjusted = base + setup

    if spread >= 1.0:
        spread_cap = 0.50
    elif spread >= 0.80:
        spread_cap = 0.75
    elif spread >= 0.55:
        spread_cap = 0.90
    else:
        spread_cap = 1.25

    session_cap = 0.75 + session * 0.50  # 0.75 dead → 1.25 active
    loss_cap = 0.50 if consec >= 2 else 1.25

    raw = _score_to_multiplier(adjusted)
    multiplier = max(0.0, min(raw, spread_cap, session_cap, loss_cap, 1.25))

    if multiplier >= 1.05:
        conviction_label = "HIGH"
        size_label = "alto"
        reason = f"alta convicción: señal={s:.2f} opp={opp:.2f}"
    elif multiplier >= 0.65:
        conviction_label = "MEDIUM"
        size_label = "estándar"
        reason = f"convicción media: señal={s:.2f} opp={opp:.2f}"
    else:
        conviction_label = "LOW"
        size_label = "mínimo"
        if consec >= 2:
            reason = f"tamaño reducido: {consec} pérdidas consecutivas"
        elif spread >= 0.80:
            reason = f"baja convicción: spread alto ({spread:.0%} del límite)"
        elif s < 0.30:
            reason = f"baja convicción: señal débil ({s:.2f})"
        else:
            reason = f"baja convicción: señal={s:.2f} opp={opp:.2f}"

    return ConvictionSizingResult(
        multiplier=multiplier,
        conviction_label=conviction_label,
        size_label=size_label,
        reason=reason,
        audit_payload=_audit(s, opp, setup, spread, session, consec, multiplier, conviction_label),
    )


def _score_to_multiplier(score: float) -> float:
    """Map a quality score to discrete multiplier tiers."""
    if score >= 0.72:
        return 1.25
    if score >= 0.60:
        return 1.10
    if score >= 0.48:
        return 0.90
    if score >= 0.35:
        return 0.70
    if score >= 0.22:
        return 0.50
    return 0.25


def _audit(
    s: float,
    opp: float,
    setup: float,
    spread: float,
    session: float,
    consec: int,
    multiplier: float,
    label: str,
) -> dict[str, Any]:
    return {
        "signal_strength": s,
        "opportunity_score": opp,
        "setup_score": setup,
        "spread_ratio": spread,
        "session_quality": session,
        "consecutive_symbol_losses": consec,
        "multiplier": multiplier,
        "conviction_label": label,
    }


__all__ = ["ConvictionSizingResult", "compute_conviction_multiplier"]
