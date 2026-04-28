"""Bidirectional Telegram control — minimal command registry + dispatch.

Replaces the legacy xm-mt5-trading-platform/src/control/local_command_*.py
which together totalled ~3630 LOC of command parsing, multi-runtime
plumbing, and an extensive command surface. The bot nuevo ALREADY HAS:
  - backend/telegram_notifier.py for one-way notifications
  - _shared/halt.py for the kill-switch
  - risk-mcp tools for daily status / lockout / reset
  - trading-mt5-mcp for positions / account / order placement

All this module needs to do is map a small set of operator slash-commands
to safe handler functions, gate dispatch with a policy check, and return
a dict the API endpoint can serialize.

CRITICAL: handlers that mutate state (HALT, RESUME, RESET_DAY, FORCE_CLOSE)
require an explicit `confirm=True` arg from the caller. The endpoint
should NEVER auto-confirm.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping


# -- Command registry ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Definition of one operator command."""

    name: str                      # e.g. "/status"
    description: str
    requires_confirm: bool = False  # state-mutating commands set this True
    args: tuple[str, ...] = ()      # named args expected (validated by handler)


# Conservative default registry. Extend per deployment by passing a custom
# registry to `dispatch`. Never silently grant new commands — always go
# through `register_command`.
DEFAULT_COMMANDS: dict[str, CommandSpec] = {
    "/status":        CommandSpec("/status", "current daily PnL + open positions"),
    "/health":        CommandSpec("/health", "service health snapshot"),
    "/positions":     CommandSpec("/positions", "list open positions"),
    "/expectancy":    CommandSpec("/expectancy", "rolling expectancy over last N trades", args=("last_n",)),
    "/halt":          CommandSpec("/halt", "engage kill-switch (blocks all new orders)", requires_confirm=True),
    "/resume":        CommandSpec("/resume", "release kill-switch", requires_confirm=True),
    "/reset_day":     CommandSpec("/reset_day", "reset risk-mcp daily counters (admin)", requires_confirm=True),
    "/force_close":   CommandSpec("/force_close", "close one position by ticket", requires_confirm=True, args=("ticket",)),
}


# -- Policy gate --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Outcome of a policy check before dispatch."""

    allowed: bool
    reason: str
    audit: dict[str, Any] = field(default_factory=dict)


def default_policy(
    *,
    command: CommandSpec,
    user_id: str | None,
    allowed_user_ids: tuple[str, ...],
    confirm: bool,
) -> PolicyDecision:
    """Conservative default policy.

    Rules:
      - user_id MUST be in allowed_user_ids
      - state-mutating commands (requires_confirm) reject without confirm=True
    """
    if user_id is None or user_id not in allowed_user_ids:
        return PolicyDecision(
            allowed=False,
            reason="USER_NOT_ALLOWED",
            audit={"user_id": user_id, "allowed_user_ids": list(allowed_user_ids)},
        )
    if command.requires_confirm and not confirm:
        return PolicyDecision(
            allowed=False,
            reason="CONFIRM_REQUIRED",
            audit={"command": command.name, "requires_confirm": True},
        )
    return PolicyDecision(allowed=True, reason="OK", audit={})


# -- Dispatch -----------------------------------------------------------------


@dataclass(slots=True)
class CommandRequest:
    """Operator command request, as parsed by the API endpoint."""

    name: str
    user_id: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    confirm: bool = False
    received_at_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "CommandRequest":
        return cls(
            name=str(payload.get("name", "")).strip(),
            user_id=payload.get("user_id"),
            args=dict(payload.get("args", {})),
            confirm=bool(payload.get("confirm", False)),
        )

    def to_audit(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "user_id": self.user_id,
            "args": dict(self.args),
            "confirm": self.confirm,
            "received_at_utc": self.received_at_utc.isoformat(),
        }


HandlerFn = Callable[[CommandRequest], dict[str, Any]]


def dispatch(
    request: CommandRequest,
    *,
    handlers: Mapping[str, HandlerFn],
    allowed_user_ids: tuple[str, ...],
    registry: Mapping[str, CommandSpec] | None = None,
) -> dict[str, Any]:
    """Dispatch one command request through the policy gate to a handler.

    Returns a JSON-safe dict.
    """
    reg = dict(registry) if registry is not None else dict(DEFAULT_COMMANDS)

    if request.name not in reg:
        return {
            "ok": False,
            "reason": "UNKNOWN_COMMAND",
            "detail": f"'{request.name}' not in registry. Available: {sorted(reg.keys())}",
            "audit": request.to_audit(),
        }
    cmd = reg[request.name]

    decision = default_policy(
        command=cmd,
        user_id=request.user_id,
        allowed_user_ids=allowed_user_ids,
        confirm=request.confirm,
    )
    if not decision.allowed:
        return {
            "ok": False,
            "reason": decision.reason,
            "detail": f"Policy denied '{request.name}'",
            "audit": {**request.to_audit(), **decision.audit},
        }

    handler = handlers.get(request.name)
    if handler is None:
        return {
            "ok": False,
            "reason": "NO_HANDLER",
            "detail": f"Command '{request.name}' has no registered handler.",
            "audit": request.to_audit(),
        }

    try:
        result = handler(request)
    except Exception as exc:  # pragma: no cover - defensive
        return {
            "ok": False,
            "reason": "HANDLER_RAISED",
            "detail": str(exc),
            "audit": request.to_audit(),
        }

    return {
        "ok": True,
        "command": request.name,
        "result": result,
        "audit": request.to_audit(),
    }


# -- Built-in stub handlers ---------------------------------------------------


def make_stub_handlers() -> dict[str, HandlerFn]:
    """Returns trivial handlers that just echo the command.

    Replace these in production with real wiring to risk-mcp, trading-mt5-mcp,
    backend journal, etc. They exist so unit tests can verify the dispatch
    pipeline without those services.
    """
    def _echo(req: CommandRequest) -> dict[str, Any]:
        return {"echo": True, "name": req.name, "args": dict(req.args)}

    return {name: _echo for name in DEFAULT_COMMANDS}


__all__ = [
    "CommandSpec",
    "DEFAULT_COMMANDS",
    "PolicyDecision",
    "default_policy",
    "CommandRequest",
    "HandlerFn",
    "dispatch",
    "make_stub_handlers",
]
