"""Stop-loss / take-profit validation.

Port of xm-mt5-trading-platform/src/execution/sl_tp_manager.py adapted to
the new bot's blueprint:
- Takes plain primitives (side as "buy"/"sell", floats) instead of legacy
  `ApprovedExecutionDecision`.
- Pure function, no IO. Returns a dict so MCP tools can pass it through
  unchanged.

Rules (unchanged from legacy):
- BUY  : stop_loss < entry < take_profit
- SELL : take_profit < entry < stop_loss
- entry resolves to ask for BUY (when present), bid for SELL (when present).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class SLTPValidationResult:
    """Validated execution levels resolved against the latest quote."""

    allowed: bool
    entry_price: float
    stop_loss: float
    take_profit: float
    reason_codes: list[str] = field(default_factory=list)
    audit_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "allowed": self.allowed,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "reason_codes": list(self.reason_codes),
            "audit": dict(self.audit_payload),
        }


def validate_sl_tp(
    *,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    bid: float | None = None,
    ask: float | None = None,
) -> SLTPValidationResult:
    """Validate SL/TP against the side and (optional) latest quote."""
    side_norm = side.lower()
    resolved_entry = entry_price

    if side_norm == "buy" and ask is not None and ask > 0.0:
        resolved_entry = ask
    elif side_norm == "sell" and bid is not None and bid > 0.0:
        resolved_entry = bid

    valid = False
    reason_codes: list[str] = []

    if side_norm == "buy":
        valid = stop_loss < resolved_entry < take_profit
    elif side_norm == "sell":
        valid = take_profit < resolved_entry < stop_loss
    else:
        valid = False
        reason_codes.append("UNSUPPORTED_SIDE")

    if not valid and "UNSUPPORTED_SIDE" not in reason_codes:
        reason_codes.append("SLTP_INVALID")

    return SLTPValidationResult(
        allowed=valid,
        entry_price=resolved_entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        reason_codes=reason_codes,
        audit_payload={
            "side": side_norm,
            "decision_entry_price": entry_price,
            "resolved_entry_price": resolved_entry,
            "bid": bid,
            "ask": ask,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        },
    )


__all__ = ["SLTPValidationResult", "validate_sl_tp"]
