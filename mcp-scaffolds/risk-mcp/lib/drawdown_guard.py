"""Drawdown / loss-streak / cooldown guard.

Port of xm-mt5-trading-platform/src/risk/drawdown_guard.py adapted to the
new bot's blueprint:
- Pulls hard limits from `_shared.rules` (no locally duplicated constants).
- Takes account snapshot as a Pydantic-style dataclass (no legacy
  `common.models` import).
- Emits result dicts (not raises) so MCP tools can return the payload
  directly.

The new bot's existing `should_stop_trading` checks daily-loss / consec /
overtrading / blocked-hour / lockout. This adds:
- Peak-equity drawdown (vs MAX_DRAWDOWN_PCT, configurable via input).
- Post-loss cooldown (configurable; default 0 = disabled).
- Symbol allow-list & operator daily-stop reasons.

These are complementary; both should be checked before placing an order.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# _shared/rules.py is added to PYTHONPATH by risk-mcp/server.py at boot.
from rules import (  # type: ignore[import-not-found]
    MAX_CONSECUTIVE_LOSSES,
    MAX_DAILY_LOSS_PCT,
)


@dataclass(slots=True)
class AccountSnapshot:
    """Account state needed by the drawdown guard.

    All values in account currency. `last_loss_at` may be None.
    """

    equity: float
    balance: float
    day_start_equity: float
    peak_equity: float
    consecutive_losses: int = 0
    last_loss_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "equity": self.equity,
            "balance": self.balance,
            "day_start_equity": self.day_start_equity,
            "peak_equity": self.peak_equity,
            "consecutive_losses": self.consecutive_losses,
            "last_loss_at": self.last_loss_at.isoformat() if self.last_loss_at else None,
        }


@dataclass(slots=True)
class DrawdownGuardResult:
    """Outcome of equity and loss-streak checks."""

    blocked: bool
    reason_codes: list[str] = field(default_factory=list)
    audit_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "blocked": self.blocked,
            "reason_codes": list(self.reason_codes),
            "audit": dict(self.audit_payload),
        }


@dataclass(slots=True)
class DailyPnLStatus:
    """Operator-configurable daily stop state.

    Mirrors xm-mt5-trading-platform/data/daily_pnl_state.json shape so the
    legacy file can be re-used as a seed.
    """

    daily_trading_enabled: bool = True
    trading_stopped_for_day: bool = False
    close_only_mode: bool = False
    allowed_symbols_today: tuple[str, ...] = ()
    stop_reason_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily_trading_enabled": self.daily_trading_enabled,
            "trading_stopped_for_day": self.trading_stopped_for_day,
            "close_only_mode": self.close_only_mode,
            "allowed_symbols_today": list(self.allowed_symbols_today),
            "stop_reason_code": self.stop_reason_code,
        }


@dataclass(slots=True)
class DailyPnLGuardResult:
    """Outcome of operator-configurable daily target/loss stop checks."""

    blocked: bool
    close_only_mode: bool
    reason_codes: list[str] = field(default_factory=list)
    audit_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "blocked": self.blocked,
            "close_only_mode": self.close_only_mode,
            "reason_codes": list(self.reason_codes),
            "audit": dict(self.audit_payload),
        }


def evaluate_drawdown_guard(
    *,
    account: AccountSnapshot,
    as_of: datetime | None = None,
    max_drawdown_pct: float | None = None,
    cooldown_after_loss_minutes: int = 0,
) -> DrawdownGuardResult:
    """Block entries when drawdown or loss-streak rules are breached.

    `max_daily_loss_pct` and `max_consecutive_losses` come from
    `_shared.rules`. `max_drawdown_pct` and `cooldown_after_loss_minutes`
    are configurable per call (legacy-compatible behaviour).
    """
    when = as_of or datetime.now(timezone.utc)
    reason_codes: list[str] = []
    audit_payload: dict[str, Any] = {
        "equity": account.equity,
        "balance": account.balance,
        "day_start_equity": account.day_start_equity,
        "peak_equity": account.peak_equity,
        "consecutive_losses": account.consecutive_losses,
        "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
        "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
    }

    if account.day_start_equity <= 0.0:
        return DrawdownGuardResult(
            blocked=True,
            reason_codes=["INVALID_DAY_START_EQUITY"],
            audit_payload=audit_payload,
        )

    daily_loss_pct = (
        max(0.0, account.day_start_equity - account.equity) / account.day_start_equity
    )
    audit_payload["daily_loss_pct"] = daily_loss_pct
    # MAX_DAILY_LOSS_PCT is expressed as a percent value (e.g. 3.0 = 3%);
    # daily_loss_pct is a fraction (e.g. 0.03). Convert to compare.
    if daily_loss_pct >= MAX_DAILY_LOSS_PCT / 100.0:
        reason_codes.append("MAX_DAILY_LOSS_REACHED")

    reference_peak = account.peak_equity or max(account.day_start_equity, account.equity)
    if reference_peak <= 0.0:
        reason_codes.append("INVALID_PEAK_EQUITY")
    elif max_drawdown_pct is not None and max_drawdown_pct > 0:
        drawdown_pct = max(0.0, reference_peak - account.equity) / reference_peak
        audit_payload["drawdown_pct"] = drawdown_pct
        audit_payload["max_drawdown_pct"] = max_drawdown_pct
        if drawdown_pct >= max_drawdown_pct / 100.0:
            reason_codes.append("MAX_DRAWDOWN_REACHED")

    if (
        MAX_CONSECUTIVE_LOSSES > 0
        and account.consecutive_losses >= MAX_CONSECUTIVE_LOSSES
    ):
        reason_codes.append("MAX_CONSECUTIVE_LOSSES_REACHED")

    if account.last_loss_at is not None and cooldown_after_loss_minutes > 0:
        cooldown_until = account.last_loss_at + timedelta(minutes=cooldown_after_loss_minutes)
        audit_payload["cooldown_until"] = cooldown_until.isoformat()
        if when < cooldown_until:
            reason_codes.append("LOSS_COOLDOWN_ACTIVE")

    return DrawdownGuardResult(
        blocked=bool(reason_codes),
        reason_codes=reason_codes,
        audit_payload=audit_payload,
    )


def evaluate_daily_pnl_guard(
    *,
    status: DailyPnLStatus | None,
    symbol: str | None = None,
) -> DailyPnLGuardResult:
    """Block new entries when the operator-configured daily stop is active."""
    if status is None:
        return DailyPnLGuardResult(
            blocked=False,
            close_only_mode=False,
            reason_codes=[],
            audit_payload={},
        )

    audit_payload = status.to_dict()
    current_symbol = str(symbol or "").strip().upper()
    if current_symbol:
        audit_payload["current_symbol"] = current_symbol

    reason_codes: list[str] = []
    if not status.daily_trading_enabled:
        reason_codes.append("DAILY_TRADING_DISABLED")
    if (
        current_symbol
        and status.allowed_symbols_today
        and current_symbol not in status.allowed_symbols_today
    ):
        reason_codes.append("SYMBOL_NOT_ALLOWED_TODAY")
    if status.trading_stopped_for_day:
        reason_codes.append(str(status.stop_reason_code or "DAILY_TRADING_STOPPED"))

    return DailyPnLGuardResult(
        blocked=bool(reason_codes),
        close_only_mode=bool(status.close_only_mode),
        reason_codes=reason_codes,
        audit_payload=audit_payload,
    )


__all__ = [
    "AccountSnapshot",
    "DrawdownGuardResult",
    "DailyPnLStatus",
    "DailyPnLGuardResult",
    "evaluate_drawdown_guard",
    "evaluate_daily_pnl_guard",
]
