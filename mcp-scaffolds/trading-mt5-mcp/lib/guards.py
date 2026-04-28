"""Pre-trade guards. Each guard takes a context dict and returns either None
(pass) or a dict ``{"reason": "...", "detail": "..."}`` to reject.

The guards run in a fixed order in ``server.place_order``. The kill-switch is
checked separately (and first). Constants come from ``_shared.rules`` only —
never duplicated locally.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

from rules import (
    MAX_RISK_PER_TRADE_PCT,
    MAX_DAILY_LOSS_PCT,
    MAX_OPEN_POSITIONS,
    MAX_CONSECUTIVE_LOSSES,
    MAX_TRADES_PER_DAY,
    MIN_RR,
    PRE_BLACKOUT_BUFFER_MIN,
    is_blocked_hour,
    is_pre_blackout,
    minutes_until_blackout,
    rr,
)


def _max_lots() -> float:
    raw = os.environ.get("MAX_LOTS_PER_TRADE", "0.5")
    try:
        return float(raw)
    except ValueError:
        return 0.5


def guard_sl_tp_required(ctx: dict) -> Optional[dict]:
    if ctx.get("sl") is None or ctx.get("tp") is None:
        return {"reason": "SL_TP_REQUIRED", "detail": "SL y TP obligatorios"}
    return None


# 24/7 markets are exempt from the blackout (no liquidity gap at night).
ALWAYS_TRADEABLE_SYMBOLS = {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT", "BTCEUR"}


def guard_blocked_hour(ctx: dict) -> Optional[dict]:
    symbol = (ctx.get("symbol") or "").upper()
    if symbol in ALWAYS_TRADEABLE_SYMBOLS:
        return None
    hour = ctx.get("utc_hour")
    minute = ctx.get("utc_minute")
    if hour is None or minute is None:
        now = datetime.now(timezone.utc)
        if hour is None:
            hour = now.hour
        if minute is None:
            minute = now.minute
    if is_blocked_hour(hour):
        return {"reason": "BLOCKED_HOUR", "detail": f"Hora {hour:02d} UTC en blackout"}
    # Reject new entries within PRE_BLACKOUT_BUFFER_MIN of blackout start.
    # The bot can't manage SL/TP during the blackout, so opening minutes
    # before is asking to be left holding overnight.
    if is_pre_blackout(hour, minute):
        mins = minutes_until_blackout(hour, minute)
        return {"reason": "PRE_BLACKOUT",
                "detail": f"{mins} min para blackout (buffer={PRE_BLACKOUT_BUFFER_MIN})"}
    return None


def guard_max_positions(ctx: dict) -> Optional[dict]:
    open_count = ctx.get("open_positions_count", 0)
    if open_count >= MAX_OPEN_POSITIONS:
        return {"reason": "MAX_POSITIONS",
                "detail": f"{open_count} posiciones abiertas (cap {MAX_OPEN_POSITIONS})"}
    # Anti-pyramid: refuse to stack on the same symbol.
    open_symbols = {s.upper() for s in (ctx.get("open_symbols") or [])}
    sym = (ctx.get("symbol") or "").upper()
    if sym and sym in open_symbols:
        return {"reason": "DUPLICATE_SYMBOL",
                "detail": f"ya hay una posición abierta en {sym}"}
    return None


def guard_daily_dd(ctx: dict) -> Optional[dict]:
    daily_pl_pct = ctx.get("daily_pl_pct", 0.0)
    if daily_pl_pct <= -MAX_DAILY_LOSS_PCT:
        return {"reason": "DAILY_LOSS_LIMIT", "detail": f"DD día {daily_pl_pct:.2f}%"}
    return None


def guard_lots_cap(ctx: dict) -> Optional[dict]:
    lots = ctx.get("lots", 0.0)
    cap = _max_lots()
    if lots > cap:
        return {"reason": "LOTS_CAP", "detail": f"Lotaje {lots} > cap {cap}"}
    return None


def guard_rr(ctx: dict) -> Optional[dict]:
    entry = ctx.get("entry")
    sl = ctx.get("sl")
    tp = ctx.get("tp")
    if entry is None or sl is None or tp is None:
        return {"reason": "SL_INVALID", "detail": "entry/sl/tp incompletos"}
    if abs(entry - sl) == 0:
        return {"reason": "SL_INVALID", "detail": "SL == entry"}
    rr_val = rr(entry, sl, tp)
    if rr_val < MIN_RR:
        return {"reason": "RR_TOO_LOW", "detail": f"R:R {rr_val:.2f} < {MIN_RR}"}
    return None


def guard_sl_tp_side(ctx: dict) -> Optional[dict]:
    side = ctx.get("side")
    entry = ctx.get("entry")
    sl = ctx.get("sl")
    tp = ctx.get("tp")
    if side == "buy" and (sl >= entry or tp <= entry):
        return {"reason": "SL_TP_SIDE", "detail": "buy → SL<entry, TP>entry"}
    if side == "sell" and (sl <= entry or tp >= entry):
        return {"reason": "SL_TP_SIDE", "detail": "sell → SL>entry, TP<entry"}
    return None


def guard_consecutive_losses(ctx: dict) -> Optional[dict]:
    """Block re-entry after MAX_CONSECUTIVE_LOSSES today. Anti-tilt."""
    streak = ctx.get("consecutive_losses_today", 0)
    if streak >= MAX_CONSECUTIVE_LOSSES:
        return {"reason": "CONSECUTIVE_LOSSES",
                "detail": f"{streak} pérdidas seguidas hoy (cap {MAX_CONSECUTIVE_LOSSES}) — pausa hasta mañana UTC"}
    return None


def guard_trades_per_day(ctx: dict) -> Optional[dict]:
    """Cap on trades opened in the current UTC day. Anti-overtrading."""
    count = ctx.get("trades_today", 0)
    if count >= MAX_TRADES_PER_DAY:
        return {"reason": "MAX_TRADES_PER_DAY",
                "detail": f"{count} trades hoy (cap {MAX_TRADES_PER_DAY})"}
    return None


def guard_risk_dollars(ctx: dict) -> Optional[dict]:
    """Risk in USD must not exceed MAX_RISK_PER_TRADE_PCT of balance.

    Tolerance:
      - 10% slack on accounts < $500 (lot granularity makes 1% impossible
        to hit precisely with a 0.01 minimum lot — without slack the bot
        rejects every trade on micro accounts).
      - 5% slack on accounts ≥ $500 (the original blueprint margin).
    """
    risk_usd = ctx.get("risk_usd")
    balance = ctx.get("balance")
    if risk_usd is None or balance is None:
        return None
    cap = balance * MAX_RISK_PER_TRADE_PCT / 100.0
    slack = 1.10 if balance < 500 else 1.05
    if risk_usd > cap * slack:
        return {"reason": "RISK_EXCEEDED",
                "detail": f"${risk_usd:.2f} > ${cap:.2f} (cap+{int((slack-1)*100)}%)"}
    return None


# Order matters: cheapest checks first, then geometry, then dollar math.
GUARDS = [
    guard_sl_tp_required,
    guard_blocked_hour,
    guard_max_positions,
    guard_consecutive_losses,
    guard_trades_per_day,
    guard_daily_dd,
    guard_lots_cap,
    guard_rr,
    guard_sl_tp_side,
    guard_risk_dollars,
]


def run_guards(ctx: dict):
    """Returns the first failing guard, or None if all pass."""
    for g in GUARDS:
        res = g(ctx)
        if res is not None:
            return res
    return None
