

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


# ── Phase 1 imports ─────────────────────────────────────────────
import json as _json
import time as _time
from pathlib import Path as _Path

# ── Correlated pairs map (Phase 1) ──────────────────────────────
CORRELATED_PAIRS = {
    "EURUSD": ["GBPUSD", "EURGBP", "EURJPY"],
    "GBPUSD": ["EURUSD", "EURGBP", "GBPJPY"],
    "USDJPY": ["EURJPY", "GBPJPY", "CADJPY"],
    "EURJPY": ["USDJPY", "EURUSD", "GBPJPY"],
    "GBPJPY": ["USDJPY", "GBPUSD", "EURJPY"],
    "AUDUSD": ["NZDUSD", "AUDJPY"],
    "NZDUSD": ["AUDUSD", "NZDJPY"],
    "USDCAD": ["USDCHF", "CADJPY"],
    "USDCHF": ["USDCAD", "EURUSD"],
    "EURGBP": ["EURUSD", "GBPUSD"],
    "CADJPY": ["USDJPY", "USDCAD"],
}


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

# ── Phase 1 Guards ──────────────────────────────────────────────

def guard_correlation(ctx: dict):
    """Block opening a position if we already have a same-direction
    position on a correlated pair. Uses open_positions from ctx."""
    symbol = ctx.get("symbol", "")
    direction = ctx.get("direction", "")
    open_positions = ctx.get("open_positions", [])

    correlated = CORRELATED_PAIRS.get(symbol, [])
    if not correlated or not open_positions:
        return None

    for pos in open_positions:
        pos_sym = pos.get("symbol", "")
        pos_dir = pos.get("direction", "") or pos.get("type", "")
        # Normalize direction
        pos_dir_norm = "BUY" if "BUY" in str(pos_dir).upper() else "SELL" if "SELL" in str(pos_dir).upper() else ""
        dir_norm = "BUY" if "BUY" in str(direction).upper() or "LONG" in str(direction).upper() else "SELL"

        if pos_sym in correlated and pos_dir_norm == dir_norm:
            return {
                "reason": "CORRELATED_PAIR",
                "detail": f"{symbol} {dir_norm} blocked: already have {pos_sym} {pos_dir_norm} (correlated)",
            }
    return None


def guard_equity_drawdown(ctx: dict):
    """Block all new trades if account equity has dropped more than
    MAX_EQUITY_DD_PCT from its peak. Peak tracked in state file."""
    max_dd_pct = float(os.environ.get("MAX_EQUITY_DD_PCT", "10.0"))
    state_file = _Path(os.environ.get("STATE_DIR", "/opt/trading-bot/state")) / "equity_peak.json"

    equity = ctx.get("equity") or ctx.get("account_equity")
    if equity is None or equity <= 0:
        return None  # Can't check without equity info

    # Load or init peak
    peak = equity
    try:
        if state_file.exists():
            data = _json.loads(state_file.read_text())
            peak = max(data.get("peak", equity), equity)
    except Exception:
        pass

    # Save new peak
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(_json.dumps({"peak": peak, "last_equity": equity}))
    except Exception:
        pass

    if peak > 0:
        dd_pct = (peak - equity) / peak * 100
        if dd_pct >= max_dd_pct:
            return {
                "reason": "EQUITY_DRAWDOWN",
                "detail": f"Equity ${equity:.2f} is {dd_pct:.1f}% below peak ${peak:.2f} (max allowed: {max_dd_pct}%)",
            }
    return None


def guard_cooldown_after_losses(ctx: dict):
    """After N consecutive losses, pause trading for M minutes.
    Env: COOLDOWN_AFTER_LOSSES (default 3), COOLDOWN_MINUTES (default 30)."""
    consec_threshold = int(os.environ.get("COOLDOWN_AFTER_LOSSES", "3"))
    cooldown_min = int(os.environ.get("COOLDOWN_MINUTES", "30"))
    state_file = _Path(os.environ.get("STATE_DIR", "/opt/trading-bot/state")) / "loss_cooldown.json"

    # Check if we're in cooldown
    try:
        if state_file.exists():
            data = _json.loads(state_file.read_text())
            cooldown_until = data.get("cooldown_until", 0)
            if _time.time() < cooldown_until:
                remaining = int((cooldown_until - _time.time()) / 60)
                return {
                    "reason": "LOSS_COOLDOWN",
                    "detail": f"Cooling down after {consec_threshold} consecutive losses. {remaining} min remaining.",
                }
    except Exception:
        pass

    # Check recent trades for consecutive losses
    recent_results = ctx.get("recent_results", [])
    if not recent_results:
        return None

    consec = 0
    for r in recent_results:
        pnl = r.get("pnl", 0) if isinstance(r, dict) else r
        if pnl < 0:
            consec += 1
        else:
            break

    if consec >= consec_threshold:
        # Enter cooldown
        cooldown_until = _time.time() + cooldown_min * 60
        try:
            state_file.parent.mkdir(parents=True, exist_ok=True)
            state_file.write_text(_json.dumps({
                "cooldown_until": cooldown_until,
                "triggered_at": _time.time(),
                "consecutive_losses": consec,
            }))
        except Exception:
            pass
        return {
            "reason": "LOSS_COOLDOWN",
            "detail": f"{consec} consecutive losses detected. Entering {cooldown_min}-minute cooldown.",
        }
    return None


def guard_low_profit_pair(ctx: dict):
    """Block pairs that have shown negative avg R over recent trades.
    Reads from trade_research.jsonl if available."""
    min_trades = int(os.environ.get("LOW_PROFIT_MIN_TRADES", "5"))
    min_avg_r = float(os.environ.get("LOW_PROFIT_MIN_AVG_R", "-0.3"))
    symbol = ctx.get("symbol", "")

    log_file = _Path(os.environ.get("LOG_DIR", "/opt/trading-bot/logs")) / "trade_research.jsonl"
    if not log_file.exists():
        return None

    # Parse recent closed trades for this symbol
    symbol_rs = []
    try:
        lines = log_file.read_text(encoding="utf-8").splitlines()
        # Read last 500 lines max for performance
        for line in lines[-500:]:
            line = line.strip()
            if not line:
                continue
            try:
                rec = _json.loads(line)
            except Exception:
                continue
            if rec.get("event") != "close":
                continue
            if rec.get("symbol") != symbol:
                continue
            r = rec.get("r_multiple")
            if r is not None:
                symbol_rs.append(float(r))
    except Exception:
        return None

    if len(symbol_rs) < min_trades:
        return None

    # Check last N trades
    recent = symbol_rs[-20:]  # last 20 closed trades on this symbol
    avg_r = sum(recent) / len(recent)

    if avg_r < min_avg_r:
        return {
            "reason": "LOW_PROFIT_PAIR",
            "detail": f"{symbol} avg R = {avg_r:.3f} over last {len(recent)} trades (threshold: {min_avg_r})",
        }
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Guards activos. Cada guard se categoriza como ENFORCE (rechaza) o LOG_ONLY
# (loggea pero no bloquea). Esto permite "stress test" del usuario donde
# todos los caps están relajados pero seguimos midiendo cuántas veces se
# habrían disparado en producción.
#
# Modo controlado vía env GUARD_MODE:
#   - "enforce" (default producción): rejection → trade bloqueado
#   - "log_only" (test mode actual): rejection se devuelve con flag log_only
#       para que el caller la registre pero NO bloquea el trade
#   - "off": no corre guards (no usar en live)
# ═══════════════════════════════════════════════════════════════════════════

# Guards que SIEMPRE bloquean (no se pueden bypasear ni en stress test —
# son sanity checks, no caps de risk).
HARD_GUARDS = [
    guard_sl_tp_required,
    guard_sl_tp_side,
]

# Guards que producen rejection en modo enforce y log_only en modo log_only.
SOFT_GUARDS = [
    guard_rr,
    guard_blocked_hour,
    guard_max_positions,
    guard_daily_dd,
    guard_lots_cap,
    guard_consecutive_losses,
    guard_trades_per_day,
    guard_risk_dollars,
    guard_correlation,
    guard_equity_drawdown,
    guard_cooldown_after_losses,
    guard_low_profit_pair,
]


def _guard_mode() -> str:
    return (os.environ.get("GUARD_MODE", "enforce") or "enforce").strip().lower()


def run_guards(ctx: dict):
    """Run hard guards (always enforce) then soft guards (mode-dependent).

    Returns:
      - dict {reason, detail, ...} si una hard guard rechaza, OR si una
        soft guard rechaza en modo enforce → caller bloquea el trade.
      - dict {reason, detail, log_only: True, would_block_in_enforce: [...]}
        si soft guards rechazaron pero estamos en modo log_only → caller
        registra pero NO bloquea.
      - None si todo pasa.
    """
    # 1) Hard guards: SL/TP required + side. Siempre enforce.
    for g in HARD_GUARDS:
        res = g(ctx)
        if res is not None:
            return res

    mode = _guard_mode()
    if mode == "off":
        return None

    # 2) Soft guards: en enforce, rechaza al primero. En log_only, recolecta
    #    todos y devuelve un payload informativo sin bloquear.
    if mode == "log_only":
        violations = []
        for g in SOFT_GUARDS:
            try:
                res = g(ctx)
            except Exception as exc:  # noqa: BLE001  guards no deben crashear el bot
                violations.append({"guard": g.__name__, "error": str(exc)})
                continue
            if res is not None:
                violations.append({"guard": g.__name__, **res})
        if violations:
            return {
                "reason": "SOFT_GUARDS_LOG_ONLY",
                "detail": f"{len(violations)} soft guard(s) would block in enforce mode",
                "log_only": True,
                "would_block_in_enforce": violations,
            }
        return None

    # mode == "enforce" → primer fail bloquea
    for g in SOFT_GUARDS:
        res = g(ctx)
        if res is not None:
            return res
    return None


# Backwards-compat: el array original GUARDS sigue exportándose por si
# algún test viejo lo importa.
GUARDS = HARD_GUARDS + SOFT_GUARDS
