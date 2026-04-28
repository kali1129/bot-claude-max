"""Deterministic trailing-stop calculator.

Port of xm-mt5-trading-platform/src/execution/trailing_stop.py.

Pure function. No IO. The caller is responsible for actually mutating the
SL on the broker — this just proposes the new value and explains why.

Conservative by design: `min_step` prevents tiny incremental updates.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TrailingStopRule:
    """Static rule for trailing stop evaluation."""

    trigger_distance: float   # profit needed before trailing kicks in (price units)
    trail_distance: float     # how far behind price the new SL stays
    min_step: float = 0.0     # minimum SL improvement to issue a new update


@dataclass(frozen=True, slots=True)
class TrailingStopUpdate:
    """One proposed stop update."""

    should_update: bool
    new_stop_loss: float | None
    reason_code: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "should_update": self.should_update,
            "new_stop_loss": self.new_stop_loss,
            "reason_code": self.reason_code,
        }


def evaluate_trailing_stop(
    *,
    side: str,
    entry_price: float,
    current_price: float,
    current_stop_loss: float,
    trigger_distance: float,
    trail_distance: float,
    min_step: float = 0.0,
) -> TrailingStopUpdate:
    """Evaluate one deterministic trailing-stop adjustment.

    `side` ∈ {"buy", "sell"}.

    Returns: TrailingStopUpdate with should_update + new_stop_loss + reason.
    Reasons:
      TRAILING_RULE_INVALID    — non-positive distances
      TRAILING_NOT_TRIGGERED   — price not yet far enough into profit
      TRAILING_STEP_TOO_SMALL  — candidate SL doesn't beat the current by min_step
      TRAILING_LONG_UPDATED    — new SL proposed for BUY
      TRAILING_SHORT_UPDATED   — new SL proposed for SELL
      TRAILING_ACTION_UNSUPPORTED — unknown side
    """
    if trigger_distance <= 0.0 or trail_distance <= 0.0:
        return TrailingStopUpdate(False, None, "TRAILING_RULE_INVALID")

    side_norm = side.lower()
    if side_norm == "buy":
        profit_distance = current_price - entry_price
        if profit_distance < trigger_distance:
            return TrailingStopUpdate(False, None, "TRAILING_NOT_TRIGGERED")
        candidate = current_price - trail_distance
        if candidate <= current_stop_loss + min_step:
            return TrailingStopUpdate(False, None, "TRAILING_STEP_TOO_SMALL")
        return TrailingStopUpdate(True, candidate, "TRAILING_LONG_UPDATED")

    if side_norm == "sell":
        profit_distance = entry_price - current_price
        if profit_distance < trigger_distance:
            return TrailingStopUpdate(False, None, "TRAILING_NOT_TRIGGERED")
        candidate = current_price + trail_distance
        if candidate >= current_stop_loss - min_step:
            return TrailingStopUpdate(False, None, "TRAILING_STEP_TOO_SMALL")
        return TrailingStopUpdate(True, candidate, "TRAILING_SHORT_UPDATED")

    return TrailingStopUpdate(False, None, "TRAILING_ACTION_UNSUPPORTED")


__all__ = ["TrailingStopRule", "TrailingStopUpdate", "evaluate_trailing_stop"]
