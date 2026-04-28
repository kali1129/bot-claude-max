"""risk-mcp v1.1.0 — Account guardian + position sizer (with capa-2 ports).

Constants from _shared/rules.py. Capa 2 additions: conviction_multiplier,
drawdown_guard, daily_pnl_guard, setup_memory_score/record (legacy ports).
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "_shared"))

load_dotenv(HERE / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("risk-mcp")

from mcp.server.fastmcp import FastMCP  # noqa: E402

from rules import (  # noqa: E402
    MAX_RISK_PER_TRADE_PCT,
    MAX_DAILY_LOSS_PCT,
    MAX_CONSECUTIVE_LOSSES,
    MAX_TRADES_PER_DAY,
    MIN_RR,
    is_blocked_hour,
)
from lib import state_manager as sm  # noqa: E402
from lib.day_reset import maybe_reset, next_day_utc_iso  # noqa: E402
from lib.sizing import calc_position_size as _calc  # noqa: E402
from lib.stats import expectancy as _expectancy  # noqa: E402

from lib.conviction_sizing import compute_conviction_multiplier  # noqa: E402
from lib.drawdown_guard import (  # noqa: E402
    AccountSnapshot,
    DailyPnLStatus,
    evaluate_drawdown_guard,
    evaluate_daily_pnl_guard,
)
from lib.setup_memory import SetupMemory  # noqa: E402

__version__ = "1.1.0"
mcp = FastMCP("risk")

_setup_mem: SetupMemory | None = None


def _get_setup_memory() -> SetupMemory:
    global _setup_mem
    if _setup_mem is None:
        _setup_mem = SetupMemory()
    return _setup_mem


def _load() -> dict:
    return maybe_reset(sm.load_state())


@mcp.tool()
def health() -> dict:
    s = _load()
    return {
        "version": __version__,
        "schema_version": s.get("_schema_version"),
        "starting_balance_today": s["starting_balance_today"],
        "current_equity": s["current_equity"],
        "trades_today": len(s["deals_today"]),
        "consecutive_losses": s["consecutive_losses"],
        "locked_until_utc": s["locked_until_utc"],
        "rules": {
            "max_risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
            "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
            "max_trades_per_day": MAX_TRADES_PER_DAY,
            "min_rr": MIN_RR,
        },
    }


@mcp.tool()
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
    return _calc(balance, risk_pct, entry, sl, tick_value, tick_size, lot_step, min_lot, max_lot)


@mcp.tool()
def daily_status() -> dict:
    s = _load()
    sm.save_state(s)
    pl = s["current_equity"] - s["starting_balance_today"]
    pl_pct = (pl / s["starting_balance_today"] * 100) if s["starting_balance_today"] else 0.0
    wins = sum(1 for d in s["deals_today"] if d.get("profit", 0) > 0)
    losses = sum(1 for d in s["deals_today"] if d.get("profit", 0) < 0)
    locked = bool(s["locked_until_utc"]) and (
        s["locked_until_utc"] > datetime.now(timezone.utc).isoformat()
    )
    can_trade = (
        pl_pct > -MAX_DAILY_LOSS_PCT
        and s["consecutive_losses"] < MAX_CONSECUTIVE_LOSSES
        and len(s["deals_today"]) < MAX_TRADES_PER_DAY
        and not locked
    )
    return {
        "date": s["last_reset_date"],
        "starting_balance": s["starting_balance_today"],
        "current_equity": s["current_equity"],
        "trades_count": len(s["deals_today"]),
        "wins_today": wins,
        "losses_today": losses,
        "consecutive_losses": s["consecutive_losses"],
        "daily_pl_usd": round(pl, 2),
        "daily_pl_pct": round(pl_pct, 3),
        "can_trade": can_trade,
        "locked": locked,
        "locked_until_utc": s["locked_until_utc"],
    }


@mcp.tool()
def should_stop_trading() -> dict:
    s = _load()
    sm.save_state(s)
    reasons = []
    pl_pct = (
        (s["current_equity"] - s["starting_balance_today"]) / s["starting_balance_today"] * 100
        if s["starting_balance_today"] else 0.0
    )
    if pl_pct <= -MAX_DAILY_LOSS_PCT:
        reasons.append(("DAILY_LOSS_LIMIT", f"DD {pl_pct:.2f}% <= -{MAX_DAILY_LOSS_PCT}%"))
    if s["consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
        reasons.append(("LOSS_STREAK", f"{s['consecutive_losses']} perdidas consecutivas"))
    if len(s["deals_today"]) >= MAX_TRADES_PER_DAY:
        reasons.append(("OVERTRADING", f"{len(s['deals_today'])} trades hoy"))

    hour = datetime.now(timezone.utc).hour
    if is_blocked_hour(hour):
        reasons.append(("BLOCKED_HOUR", f"{hour:02d}:00 UTC en blackout"))

    if s["locked_until_utc"]:
        if s["locked_until_utc"] > datetime.now(timezone.utc).isoformat():
            reasons.append(("LOCKED", f"Lockout activo hasta {s['locked_until_utc']}"))

    stop = len(reasons) > 0
    return {
        "stop": stop,
        "reasons": reasons,
        "resume_at_utc": next_day_utc_iso() if stop else None,
    }


@mcp.tool()
def register_trade(
    profit: float,
    r_multiple: float,
    symbol: str,
    side: str,
    deal_ticket: int = None,
) -> dict:
    s = _load()

    if deal_ticket is not None:
        for d in s["deals_today"]:
            if d.get("deal_ticket") == deal_ticket:
                return {
                    "registered": False,
                    "reason": "DUPLICATE_TICKET",
                    "current_equity": s["current_equity"],
                }

    deal = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol,
        "side": side,
        "profit": float(profit),
        "r_multiple": float(r_multiple),
        "deal_ticket": deal_ticket,
    }
    s["deals_today"].append(deal)
    s["current_equity"] += profit

    if profit < 0:
        s["consecutive_losses"] += 1
    elif profit > 0:
        s["consecutive_losses"] = 0

    pl_pct = (
        (s["current_equity"] - s["starting_balance_today"]) / s["starting_balance_today"] * 100
        if s["starting_balance_today"] else 0.0
    )
    if pl_pct <= -MAX_DAILY_LOSS_PCT:
        s["locked_until_utc"] = next_day_utc_iso()

    sm.save_state(s)
    return {
        "registered": True,
        "current_equity": s["current_equity"],
        "consecutive_losses": s["consecutive_losses"],
        "locked": bool(s["locked_until_utc"]),
        "trades_today": len(s["deals_today"]),
    }


@mcp.tool()
def expectancy(last_n: int = 30) -> dict:
    return _expectancy(last_n)


@mcp.tool()
def reset_day() -> dict:
    """Admin only. Resets today's counters but keeps current_equity."""
    log.warning("reset_day called manually")
    s = _load()
    eq = s["current_equity"]
    new_state = {
        "_schema_version": sm.CURRENT_SCHEMA_VERSION,
        "starting_balance_today": eq,
        "current_equity": eq,
        "deals_today": [],
        "consecutive_losses": 0,
        "locked_until_utc": None,
        "last_reset_date": datetime.now(timezone.utc).date().isoformat(),
    }
    sm.save_state(new_state)
    return {"reset": True, "current_equity": eq}


# Capa 2 (legacy ports) -------------------------------------------------------


@mcp.tool()
def conviction_multiplier(
    signal_strength: float,
    opportunity_score: float = 0.5,
    setup_score: float = 0.0,
    spread_ratio: float = 0.0,
    session_quality: float = 1.0,
    consecutive_symbol_losses: int = 0,
) -> dict:
    return compute_conviction_multiplier(
        signal_strength=signal_strength,
        opportunity_score=opportunity_score,
        setup_score=setup_score,
        spread_ratio=spread_ratio,
        session_quality=session_quality,
        consecutive_symbol_losses=consecutive_symbol_losses,
    ).to_dict()


@mcp.tool()
def drawdown_guard(
    equity: float,
    balance: float,
    day_start_equity: float,
    peak_equity: float,
    consecutive_losses: int = 0,
    last_loss_at: str | None = None,
    max_drawdown_pct: float | None = None,
    cooldown_after_loss_minutes: int = 0,
) -> dict:
    last_loss_dt = None
    if last_loss_at:
        try:
            last_loss_dt = datetime.fromisoformat(last_loss_at.replace("Z", "+00:00"))
            if last_loss_dt.tzinfo is None:
                last_loss_dt = last_loss_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return {"ok": False, "reason": "INVALID_LAST_LOSS_AT", "detail": last_loss_at}
    snap = AccountSnapshot(
        equity=equity,
        balance=balance,
        day_start_equity=day_start_equity,
        peak_equity=peak_equity,
        consecutive_losses=consecutive_losses,
        last_loss_at=last_loss_dt,
    )
    return evaluate_drawdown_guard(
        account=snap,
        max_drawdown_pct=max_drawdown_pct,
        cooldown_after_loss_minutes=cooldown_after_loss_minutes,
    ).to_dict()


@mcp.tool()
def daily_pnl_guard(
    daily_trading_enabled: bool = True,
    trading_stopped_for_day: bool = False,
    close_only_mode: bool = False,
    allowed_symbols_today: list[str] | None = None,
    stop_reason_code: str | None = None,
    symbol: str | None = None,
) -> dict:
    status = DailyPnLStatus(
        daily_trading_enabled=bool(daily_trading_enabled),
        trading_stopped_for_day=bool(trading_stopped_for_day),
        close_only_mode=bool(close_only_mode),
        allowed_symbols_today=tuple(s.upper() for s in (allowed_symbols_today or [])),
        stop_reason_code=stop_reason_code,
    )
    return evaluate_daily_pnl_guard(status=status, symbol=symbol).to_dict()


@mcp.tool()
def setup_memory_score(symbol: str, driver: str) -> dict:
    mem = _get_setup_memory()
    return {
        "ok": True,
        "symbol": symbol.upper(),
        "driver": driver,
        "score": mem.setup_score(symbol, driver),
        "consecutive_symbol_losses": mem.symbol_consecutive_losses(symbol),
        "history_note": mem.setup_history_note(symbol, driver),
        "stats_path": str(mem.path),
    }


@mcp.tool()
def setup_memory_record(symbol: str, driver: str, won: bool, pnl: float) -> dict:
    mem = _get_setup_memory()
    mem.record_trade(symbol=symbol, driver=driver, won=won, pnl=pnl)
    setup_stats = mem.get_setup_stats(symbol, driver)
    sym_stats = mem.get_symbol_stats(symbol)
    return {
        "ok": True,
        "symbol": symbol.upper(),
        "driver": driver,
        "setup_stats": setup_stats.to_dict() if setup_stats else None,
        "symbol_stats": sym_stats.to_dict() if sym_stats else None,
    }


if __name__ == "__main__":
    log.info("risk-mcp v%s starting", __version__)
    mcp.run()
