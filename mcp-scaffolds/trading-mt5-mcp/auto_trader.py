"""auto_trader.py — autonomous loop that ties the 4 MCPs together.

Every interval:
  1. Pre-flight: kill-switch + risk-mcp.should_stop_trading + open positions
  2. Scan a watchlist for the best setup (analysis-mcp.score_setup)
  3. Size with risk-mcp.calc_position_size (1% risk)
  4. Place the order via trading-mt5-mcp.place_order

Logs every iteration to ~/mcp/logs/auto_trader.jsonl so you can audit later.

Run from inside the trading-mt5-mcp venv:
    .venv/Scripts/python auto_trader.py

Args:
    --interval N    seconds between scans (default 300 = 5 min)
    --risk-pct R    % of balance per trade (default 1.0)
    --min-score S   minimum analysis score to take a trade (default 70)
    --symbols A,B,C overrides the watchlist
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
SCAFFOLDS = HERE.parent

# Allow this script to import the trading MCP server module and _shared/.
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(SCAFFOLDS / "_shared"))

load_dotenv(HERE / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s auto-trader %(message)s",
)
log = logging.getLogger("auto-trader")

import MetaTrader5 as mt5  # noqa: E402
import server as trading                              # trading-mt5-mcp/server.py    # noqa: E402
import halt as halt_mod                                # _shared/halt.py              # noqa: E402

# New shared modules (capital ledger, expectancy, regime, correlation, kelly)
from common import capital_ledger, expectancy_tracker, regime as regime_mod, correlation as corr_mod, sizing_kelly  # noqa: E402

# Cross-MCP imports: load analysis-mcp/lib and risk-mcp/lib explicitly by
# file path so we don't collide with trading-mt5-mcp's own ``lib`` package.
import importlib.util  # noqa: E402


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# analysis-mcp expects "from . import indicators / structure" inside
# scoring.py, so we register the package + submodules under a private
# namespace.
_ANALYSIS_DIR = SCAFFOLDS / "analysis-mcp" / "lib"
_analysis_pkg = importlib.util.module_from_spec(
    importlib.util.spec_from_loader("analysis_lib", loader=None,
                                     is_package=True))
_analysis_pkg.__path__ = [str(_ANALYSIS_DIR)]
sys.modules["analysis_lib"] = _analysis_pkg

indicators = _load_module("analysis_lib.indicators", _ANALYSIS_DIR / "indicators.py")
structure  = _load_module("analysis_lib.structure",  _ANALYSIS_DIR / "structure.py")
scoring    = _load_module("analysis_lib.scoring",    _ANALYSIS_DIR / "scoring.py")

risk_sizing = _load_module(
    "risk_sizing",
    SCAFFOLDS / "risk-mcp" / "lib" / "sizing.py",
)

LOG_DIR = Path(os.path.expanduser(os.environ.get("LOG_DIR", "~/mcp/logs")))
LOG_FILE = LOG_DIR / "auto_trader.jsonl"
PAPER_OPEN_FILE = HERE / "paper_open.json"   # in-flight paper trades
PAPER_TRADES_FILE = HERE / "paper_trades.jsonl"  # closed paper trades
LAST_SCAN_FILE = HERE / "last_scan.json"     # most recent scan snapshot

# Research log — structured per-trade record for post-test analysis.
# Each line is one event: {open, manage, close}. Stitched together by ticket.
# The dashboard pulls this via /api/research/trades.
RESEARCH_LOG = LOG_DIR / "trade_research.jsonl"
# State file used while a position is open to track MAE/MFE (max adverse /
# max favorable excursion in pips). Lives next to the lock file.
RESEARCH_STATE_FILE = Path(os.path.expanduser(
    os.environ.get("LOG_DIR", "~/mcp/logs"))).parent / "state" / "position_state.json"

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8000").rstrip("/")
DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "").strip()
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TG_ENABLED = (os.environ.get("TELEGRAM_NOTIFICATIONS_ENABLED", "true") or "")\
    .strip().lower() in {"1", "true", "yes", "on"}


def _tg_send(text: str) -> None:
    """Best-effort Telegram notification — never blocks the bot."""
    if not (TG_ENABLED and TG_TOKEN and TG_CHAT):
        return
    try:
        import urllib.request, urllib.error  # noqa: WPS433
        body = json.dumps({
            "chat_id": TG_CHAT, "text": text[:3500],
            "disable_web_page_preview": True, "parse_mode": "Markdown",
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=4).close()
    except Exception as exc:  # noqa: BLE001
        log.debug("telegram failed: %s", exc)

# Watchlist tuning — 24h test máxima cobertura.
# Crypto primero (24/7, volatilidad alta, exento del blackout).
# Luego majors + gold + 3 nuevos majors (USDCHF, NZDUSD, USDCAD) para
# que con interval=15s y min_score=45 el bot tenga ~10 candidatos por
# escaneo y dispare trades aún cuando algunos están en consolidación.
WATCHLIST_DEFAULT = [
    "BTCUSD", "ETHUSD",
    "XAUUSD",
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD",
]

# Symbols that ignore session/blackout rules (single source of truth — antes
# estaba duplicado en 3 lugares con valores ligeramente distintos).
ALWAYS_TRADEABLE = {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT", "BTCEUR"}
ALWAYS_TRADEABLE_24H = ALWAYS_TRADEABLE  # alias para compat

NL = chr(10)  # newline for use inside f-strings

# === Multi-strategy engine (v3) ===
sys.path.insert(0, str(HERE))  # ensure strategies/ is importable
import strategies as strat_engine

# Global hard filters
MAX_SPREAD_PCT_OF_R = float(os.environ.get("MAX_SPREAD_PCT_OF_R", "35.0"))
FOREX_SESSION_START_UTC = 7       # forex: only trade 07:00-20:00 UTC
FOREX_SESSION_END_UTC = 20

# Anti-repaint: exigir que la barra M15 esté cerrada (con tolerancia)
# antes de evaluar setups. Evita que escaneos cada 15s evalúen 60 veces
# la misma barra incompleta y disparen signals que se reorganizan después.
# Default: requerir 14 min mínimos transcurridos en la barra M15 actual
# (último candle "casi cerrado") + dedup por (strategy, symbol, bar_open_time).
ANTI_REPAINT_MIN_BAR_AGE_SEC = int(os.environ.get(
    "ANTI_REPAINT_MIN_BAR_AGE_SEC", "0"))   # 0 = desactivado por defecto (compat con stress test)

# Cooldown post-rejection por símbolo. Cuando place_order rechaza por motivos
# persistentes (LOW_PROFIT_PAIR, RISK_EXCEEDED, etc.), no re-intentar el
# mismo símbolo hasta que pase este cooldown.
SYMBOL_COOLDOWN_AFTER_REJECT_MIN = int(os.environ.get(
    "SYMBOL_COOLDOWN_AFTER_REJECT_MIN", "30"))
# Motivos que activan cooldown (otros se reintentan inmediato)
COOLDOWN_REASONS = {
    "LOW_PROFIT_PAIR", "RISK_EXCEEDED", "EQUITY_DRAWDOWN",
    "DAILY_LOSS_LIMIT", "LOSS_COOLDOWN", "MAX_TRADES_PER_DAY",
    "CORRELATED_PAIR", "CORRELATED_CONCENTRATION", "REGIME_INCOMPATIBLE",
    "NEGATIVE_EXPECTANCY",
}

# Cooldown state in-memory (dict symbol → unix ts hasta cuándo skipear)
_SYMBOL_COOLDOWN_UNTIL: dict = {}

# Anti-repaint dedup: { (strategy_id, symbol, bar_open_time_iso) → ts }
_LAST_PROPOSED: dict = {}



_running = True


def _on_signal(signum, _frame):
    global _running
    log.info("signal %s — stopping after current iteration", signum)
    _running = False


def _rotate_if_needed(path: Path, max_mb: float = 50.0) -> None:
    """Rotación simple: si el archivo > max_mb, lo rota a .1.gz (sin gzip por
    simplicidad — solo rename con timestamp). Mantiene últimos 5 archivos.

    Llamado de forma "best effort" — failures no rompen el bot.
    """
    try:
        if not path.exists():
            return
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb < max_mb:
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rotated = path.with_suffix(path.suffix + f".{ts}")
        path.rename(rotated)
        # Mantener solo últimos 5 rotados
        rotated_files = sorted(path.parent.glob(f"{path.name}.*"))
        for old in rotated_files[:-5]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


_AUDIT_LINES_SINCE_ROTATE = 0
_RESEARCH_LINES_SINCE_ROTATE = 0


def _audit(payload: dict) -> None:
    global _AUDIT_LINES_SINCE_ROTATE
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")
    # Check size cada ~500 líneas (no en cada write — overhead)
    _AUDIT_LINES_SINCE_ROTATE += 1
    if _AUDIT_LINES_SINCE_ROTATE >= 500:
        _rotate_if_needed(LOG_FILE, max_mb=50.0)
        _AUDIT_LINES_SINCE_ROTATE = 0


# ============================================================================
# Research log — structured per-trade record for post-test feedback
# ============================================================================

def _research_write(event_type: str, payload: dict) -> None:
    """Append one structured event to the research log. Never raises."""
    global _RESEARCH_LINES_SINCE_ROTATE
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **payload,
        }
        with open(RESEARCH_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        _RESEARCH_LINES_SINCE_ROTATE += 1
        if _RESEARCH_LINES_SINCE_ROTATE >= 500:
            _rotate_if_needed(RESEARCH_LOG, max_mb=20.0)
            _RESEARCH_LINES_SINCE_ROTATE = 0
    except OSError as exc:
        log.warning("research_log write failed: %s", exc)


def _research_load_state() -> dict:
    """Position-state map: ticket → {entry_time, original_sl, original_tp,
    max_favorable_price, max_adverse_price, ...}. Used to compute MAE/MFE
    on close."""
    if not RESEARCH_STATE_FILE.exists():
        return {}
    try:
        return json.loads(RESEARCH_STATE_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _research_save_state(state: dict) -> None:
    try:
        RESEARCH_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        RESEARCH_STATE_FILE.write_text(json.dumps(state, default=str), encoding="utf-8")
    except OSError:
        pass


def _research_open(*, ticket: int, setup: dict, lots: float, risk_dollars: float,
                    balance: float, trades_today: int, consecutive_losses: int,
                    open_positions_before: int, args, watchlist,
                    spread: float = None, runners_up: list = None) -> None:
    """Capture a complete snapshot at the moment the bot opened a trade.
    Includes scoring breakdown, ATR, market context, and bot config so we
    can do post-mortem analysis on what worked vs what didn't."""
    payload = {
        "ticket": int(ticket),
        "symbol": setup["symbol"],
        "side": setup["side"],
        "entry": setup["entry"],
        "sl": setup["sl"],
        "tp": setup["tp"],
        "lots": float(lots),
        "atr": setup.get("atr"),
        "score": setup.get("score"),
        "rec": setup.get("rec"),
        "breakdown": setup.get("breakdown", {}),
        "risk_usd": round(float(risk_dollars), 2),
        "context": {
            "balance_at_entry": round(float(balance), 2),
            "trades_today_before": int(trades_today),
            "consecutive_losses_today": int(consecutive_losses),
            "open_positions_before": int(open_positions_before),
            "utc_hour": datetime.now(timezone.utc).hour,
            "utc_minute": datetime.now(timezone.utc).minute,
        },
        "config": {
            "min_score": int(args.min_score),
            "interval_s": int(args.interval),
            "risk_pct": float(args.risk_pct),
            "watchlist_size": len(watchlist),
        },
        # Spread at entry: how much the bid-ask gap is eating before we even
        # start. If spread is N% of the SL distance, that's N% of every R
        # given to the broker for free. Critical for live transition.
        "strategy_id": setup.get("strategy_id", "unknown"),
        "spread_at_entry": (round(float(spread), 6) if spread is not None else None),
        "spread_pct_of_r": (
            round(float(spread) / max(abs(setup["entry"] - setup["sl"]), 1e-9) * 100, 2)
            if spread is not None else None
        ),
        # Top runners-up that the bot REJECTED in favour of this trade. If
        # we're picking USDJPY at score 75 but rejecting EURUSD at 70, we
        # want to know — sometimes the runner-up would have been the win.
        "runners_up": [
            {"symbol": r.get("symbol"), "side": r.get("side"),
             "score": r.get("score"), "rec": r.get("rec")}
            for r in (runners_up or [])[:3]
        ],
    }
    _research_write("open", payload)
    # Seed the state for MAE/MFE tracking. CRITICAL: persistir sl_atr_mult
    # y atr_at_entry para que _manage_open_positions calcule R correctamente
    # según la estrategia que lo abrió, no un hardcoded 1.5.
    sid = setup.get("strategy_id", "")
    sl_atr_mult = 1.5
    try:
        if sid and sid in strat_engine.REGISTRY:
            sl_atr_mult = float(strat_engine.REGISTRY[sid].sl_atr_mult)
    except Exception:  # noqa: BLE001
        pass
    state = _research_load_state()
    state[str(int(ticket))] = {
        "symbol": setup["symbol"],
        "side": setup["side"],
        "entry": setup["entry"],
        "original_sl": setup["sl"],
        "original_tp": setup["tp"],
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "max_favorable_price": setup["entry"],
        "max_adverse_price": setup["entry"],
        "max_favorable_at": datetime.now(timezone.utc).isoformat(),
        "max_adverse_at": datetime.now(timezone.utc).isoformat(),
        "be_moved": False,
        "trail_count": 0,
        # Persistir contexto de la estrategia para que el manage haga R-progress
        # correcto. Sin esto el trailing usa SL_MULT hardcoded 1.5 y rompe el
        # RR prometido en breakout_hunter (2.0) y mean_reverter (2.0).
        "strategy_id": sid,
        "sl_atr_mult": sl_atr_mult,
        "atr_at_entry": float(setup.get("atr") or 0.0),
    }
    _research_save_state(state)


def _research_manage(*, ticket: int, action: str, old_sl: float, new_sl: float,
                      rr_progress: float, current_price: float) -> None:
    """Record an SL move (BE or trailing). Updates state too."""
    _research_write("manage", {
        "ticket": int(ticket),
        "action": action,
        "old_sl": old_sl,
        "new_sl": new_sl,
        "rr_progress": round(rr_progress, 3),
        "current_price": current_price,
    })
    state = _research_load_state()
    s = state.get(str(int(ticket)))
    if s:
        if action == "breakeven":
            s["be_moved"] = True
        elif action == "trail":
            s["trail_count"] = int(s.get("trail_count", 0)) + 1
            s["last_trail_sl"] = new_sl
        _research_save_state(state)


def _research_update_excursion(ticket: int, current_price: float) -> None:
    """Track MAE/MFE while the trade is open. Called every iteration of
    _manage_open_positions for each known position."""
    state = _research_load_state()
    s = state.get(str(int(ticket)))
    if not s:
        return
    side = s.get("side")
    now_iso = datetime.now(timezone.utc).isoformat()
    if side == "buy":
        if current_price > s.get("max_favorable_price", current_price):
            s["max_favorable_price"] = current_price
            s["max_favorable_at"] = now_iso
        if current_price < s.get("max_adverse_price", current_price):
            s["max_adverse_price"] = current_price
            s["max_adverse_at"] = now_iso
    else:  # sell
        if current_price < s.get("max_favorable_price", current_price):
            s["max_favorable_price"] = current_price
            s["max_favorable_at"] = now_iso
        if current_price > s.get("max_adverse_price", current_price):
            s["max_adverse_price"] = current_price
            s["max_adverse_at"] = now_iso
    state[str(int(ticket))] = s
    _research_save_state(state)


def _research_close(*, ticket: int, exit_price: float, pnl_usd: float,
                     r_multiple: float, exit_reason: str) -> None:
    """Stitch the open record + manage events + close into a final summary
    line in the research log. Pulls MAE/MFE from state file then drops the
    state entry (position is closed)."""
    state = _research_load_state()
    s = state.pop(str(int(ticket)), {}) or {}
    _research_save_state(state)

    entry = float(s.get("entry") or exit_price)
    side = s.get("side", "buy")
    # MAE / MFE in the trade's R-units (relative to the original SL distance)
    orig_sl = float(s.get("original_sl") or 0)
    sl_dist = abs(entry - orig_sl) if orig_sl else 0.0
    if sl_dist > 0:
        if side == "buy":
            mfe_r = (s.get("max_favorable_price", entry) - entry) / sl_dist
            mae_r = (entry - s.get("max_adverse_price", entry)) / sl_dist * -1
        else:
            mfe_r = (entry - s.get("max_favorable_price", entry)) / sl_dist
            mae_r = (s.get("max_adverse_price", entry) - entry) / sl_dist * -1
    else:
        mfe_r = mae_r = 0.0

    opened_at = s.get("opened_at")
    duration_s = None
    time_to_mfe_s = None
    time_to_mae_s = None
    if opened_at:
        try:
            o = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
            duration_s = int((datetime.now(timezone.utc) - o).total_seconds())
            mfe_at = s.get("max_favorable_at")
            if mfe_at:
                try:
                    mfe_dt = datetime.fromisoformat(mfe_at.replace("Z", "+00:00"))
                    time_to_mfe_s = int((mfe_dt - o).total_seconds())
                except (ValueError, TypeError):
                    pass
            mae_at = s.get("max_adverse_at")
            if mae_at:
                try:
                    mae_dt = datetime.fromisoformat(mae_at.replace("Z", "+00:00"))
                    time_to_mae_s = int((mae_dt - o).total_seconds())
                except (ValueError, TypeError):
                    pass
        except (ValueError, TypeError):
            pass

    _research_write("close", {
        "ticket": int(ticket),
        "symbol": s.get("symbol"),
        "side": side,
        "entry": entry,
        "exit": exit_price,
        "exit_reason": exit_reason,
        "pnl_usd": round(float(pnl_usd), 2),
        "r_multiple": round(float(r_multiple), 2),
        "duration_seconds": duration_s,
        "mfe_r": round(mfe_r, 2),
        "mae_r": round(mae_r, 2),
        "max_favorable_price": s.get("max_favorable_price"),
        "max_adverse_price": s.get("max_adverse_price"),
        "time_to_mfe_seconds": time_to_mfe_s,
        "time_to_mae_seconds": time_to_mae_s,
        "be_moved": bool(s.get("be_moved")),
        "trail_count": int(s.get("trail_count", 0)),
        "original_sl": s.get("original_sl"),
        "original_tp": s.get("original_tp"),
        "strategy_id": s.get("strategy_id"),
    })

    # Registrar en el expectancy_tracker. Esto alimenta la decisión "edge
    # PROVEN | UNCERTAIN | NEGATIVE" que usa _propose_setup en próximos scans.
    try:
        sid = s.get("strategy_id") or "unknown"
        if s.get("symbol"):
            expectancy_tracker.register_close(
                strategy_id=sid,
                symbol=s.get("symbol"),
                r_multiple=float(r_multiple),
                pnl_usd=float(pnl_usd),
                utc_hour=datetime.now(timezone.utc).hour,
                extra={"exit_reason": exit_reason,
                        "be_moved": bool(s.get("be_moved")),
                        "duration_s": duration_s},
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("expectancy register failed for ticket %s: %s", ticket, exc)


# --------------------------- paper trade tracker ---------------------------

def _load_paper_open() -> list:
    if not PAPER_OPEN_FILE.exists():
        return []
    try:
        return json.loads(PAPER_OPEN_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _save_paper_open(trades: list) -> None:
    PAPER_OPEN_FILE.write_text(json.dumps(trades, indent=2, default=str),
                                encoding="utf-8")


def _append_closed(trade: dict) -> None:
    with open(PAPER_TRADES_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(trade, default=str) + "\n")


def _post_journal(payload: dict) -> bool:
    """POST a closed paper trade to the dashboard journal (best-effort)."""
    import requests  # noqa: WPS433
    headers = {"Content-Type": "application/json"}
    if DASHBOARD_TOKEN:
        headers["Authorization"] = f"Bearer {DASHBOARD_TOKEN}"
    try:
        r = requests.post(f"{DASHBOARD_URL}/api/journal", json=payload,
                          headers=headers, timeout=5)
        return r.status_code < 400
    except requests.RequestException as exc:
        log.warning("dashboard journal post failed: %s", exc)
        return False


def _open_paper_trade(setup: dict, lots: float, ticket: int,
                       balance_at_entry: float) -> None:
    """Save a paper trade to disk so it survives restarts."""
    trades = _load_paper_open()
    trades.append({
        "ticket": ticket,
        "symbol": setup["symbol"],
        "side": setup["side"],
        "lots": lots,
        "entry": setup["entry"],
        "sl": setup["sl"],
        "tp": setup["tp"],
        "score": setup["score"],
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "balance_at_entry": balance_at_entry,
    })
    _save_paper_open(trades)


def _close_paper_trade(trade: dict, exit_price: float, reason: str) -> dict:
    """Compute pnl + r-multiple, write to journal + dashboard, return summary."""
    side = trade["side"]
    lots = trade["lots"]
    entry = trade["entry"]
    sl = trade["sl"]

    # Pull tick value/size for proper $ pnl.
    try:
        info = mt5.symbol_info(trade["symbol"])
        tick_value = float(info.trade_tick_value or 1.0) if info else 1.0
        tick_size = float(info.trade_tick_size or info.point or 1e-5) if info else 1e-5
    except Exception:  # noqa: BLE001
        tick_value, tick_size = 1.0, 1e-5

    distance = (exit_price - entry) if side == "buy" else (entry - exit_price)
    ticks = distance / tick_size
    # MT5's ``trade_tick_value`` is the dollar value of one tick on a *contract*
    # (1.0 lot for FX/CFD, 1 share for stocks). To get the dollar PnL on
    # ``lots`` lots we multiply by ``lots`` exactly once. Earlier comment in
    # this function speculated about brokers where tick_value already includes
    # lots — that's not the standard MQL5 contract: ``trade_tick_value`` is
    # always per 1.0 lot. Verified by sanity check: 0.01 lots EURUSD with a
    # 10-pip move → 0.01 * (0.0010/0.00001) * tick_value(=$1) = $1.00.
    pnl_usd = round(ticks * tick_value * lots, 2)

    sl_distance = abs(entry - sl)
    sl_ticks = sl_distance / tick_size if tick_size > 0 else 0
    risk_usd = sl_ticks * tick_value * lots
    r_multiple = round(pnl_usd / risk_usd, 2) if risk_usd > 0 else 0.0

    if pnl_usd > 0:
        status = "closed-win"
    elif pnl_usd < 0:
        status = "closed-loss"
    else:
        status = "closed-be"

    closed = {
        **trade,
        "exit_price": round(exit_price, 5),
        "exit_reason": reason,
        "closed_at": datetime.now(timezone.utc).isoformat(),
        "pnl_usd": pnl_usd,
        "r_multiple": r_multiple,
        "status": status,
    }
    _append_closed(closed)

    # POST to dashboard journal (idempotent via client_id)
    journal_payload = {
        "client_id": f"paper-trade-{trade['ticket']}",
        "source": "manual",
        "date": closed["opened_at"][:10],
        "symbol": trade["symbol"],
        "side": side,
        "strategy": f"auto_trader[score{trade['score']}]",
        "entry": entry,
        "exit": exit_price,
        "sl": sl,
        "tp": trade["tp"],
        "lots": lots,
        "pnl_usd": pnl_usd,
        "r_multiple": r_multiple,
        "status": status,
        "notes": f"paper · ticket={trade['ticket']} · exit={reason}",
    }
    _post_journal(journal_payload)
    side_es = "compra" if side == "buy" else "venta"
    icon = "🟢" if pnl_usd > 0 else ("🔴" if pnl_usd < 0 else "⚪")
    _tg_wl = "Ganó" if pnl_usd > 0 else "Perdió"
    _tg_send(
        f"{icon} *{_tg_wl}:* {trade['symbol']}\n"
        f"P&L: *${pnl_usd:+.2f}*"
    )
    return closed


MONITOR_MAX_FAILURES = 60   # ~30 min at 30 s interval — then force-close


def _monitor_paper_trades() -> dict:
    """For each open paper trade, check the live tick. Close if hit SL/TP.
    A trade whose tick keeps failing for MONITOR_MAX_FAILURES iterations
    in a row is force-closed at last-known mid-price so it doesn't block
    a slot forever."""
    trades = _load_paper_open()
    if not trades:
        return {"open": 0, "closed": []}
    still_open = []
    just_closed = []
    for t in trades:
        try:
            tk = trading.get_tick(t["symbol"])
            tick_failed = ("ok" in tk and tk["ok"] is False)
            if tick_failed:
                fails = int(t.get("monitor_failures", 0)) + 1
                if fails >= MONITOR_MAX_FAILURES:
                    # Force-close at last-known entry (no fresh price → safest
                    # is to flatten at entry, marking it as a wash). Audit
                    # this so the user sees something is broken with the feed.
                    log.warning("PAPER %s force-closed after %d monitor "
                                "failures — symbol feed appears dead",
                                t["symbol"], fails)
                    closed = _close_paper_trade(t, float(t["entry"]),
                                                 "MONITOR_STUCK")
                    just_closed.append(closed)
                    # SILENCED: paper force-close telegram
                    continue
                t["monitor_failures"] = fails
                still_open.append(t)
                continue
            # Tick OK → reset the failure counter
            t.pop("monitor_failures", None)
            bid = tk["bid"]
            ask = tk["ask"]
            side = t["side"]
            sl = t["sl"]
            tp = t["tp"]
            # Close conditions:
            if side == "buy":
                if bid <= sl:
                    just_closed.append(_close_paper_trade(t, bid, "SL"))
                    continue
                if bid >= tp:
                    just_closed.append(_close_paper_trade(t, bid, "TP"))
                    continue
            else:  # sell
                if ask >= sl:
                    just_closed.append(_close_paper_trade(t, ask, "SL"))
                    continue
                if ask <= tp:
                    just_closed.append(_close_paper_trade(t, ask, "TP"))
                    continue
            still_open.append(t)
        except Exception as exc:  # noqa: BLE001
            log.warning("monitor failed for %s: %s", t["symbol"], exc)
            t["monitor_failures"] = int(t.get("monitor_failures", 0)) + 1
            still_open.append(t)
    _save_paper_open(still_open)
    return {"open": len(still_open), "closed": just_closed}


# ============================================================================
# Open-position management: break-even + ATR trailing stop
# ============================================================================
#
# Once a trade reaches +1R unrealised, move SL to entry (no more loss possible).
# After that, trail SL behind price by 1.0× ATR(M15). This locks in gains so
# the bot doesn't watch a +2R run reverse to -1R.
#
# Demo/live ONLY — paper mode skips because paper_open.json doesn't preserve
# the original SL distance reliably and MT5 is the source of truth in demo.

from server import MAGIC as TRADING_MAGIC  # noqa: E402  reuse the same magic


def _r_progress(side: str, entry: float, sl_initial_distance: float,
                 current_price: float) -> float:
    """How many R-multiples of unrealised PnL the position has, given the
    INITIAL SL distance (not the current SL — we want the distance at
    open). Positive when the position is in profit."""
    if sl_initial_distance <= 0:
        return 0.0
    if side == "buy":
        delta = current_price - entry
    else:
        delta = entry - current_price
    return delta / sl_initial_distance


def _manage_open_positions(iteration: int) -> None:
    """For each of THIS bot's open MT5 positions:
      - if R >= 1.0 and SL not at/past entry → move SL to entry (breakeven)
      - if R >= 1.0 and SL already at/past entry → trail SL behind price by 1× ATR(M15)
    Skip in paper mode. Skip positions whose magic doesn't match THIS bot.
    Errors are logged but do not crash the iteration.

    Also detects positions that have closed since the last call (by diffing
    state file vs current open positions) and writes a research_close
    record for each — pulling the OUT deal pnl/exit price from MT5 history.
    """
    from server import MODE  # noqa: WPS433
    if MODE == "paper":
        return

    try:
        positions = mt5.positions_get(magic=int(TRADING_MAGIC)) or []
    except Exception as exc:  # noqa: BLE001
        log.warning("manage: positions_get failed: %s", exc)
        return

    # Detect closures: anything in research state that's no longer open
    try:
        live_tickets = {int(p.ticket) for p in positions}
        state = _research_load_state()
        closed_tickets = [int(t) for t in state.keys() if int(t) not in live_tickets]
        for ticket in closed_tickets:
            try:
                # Find the matching OUT deal in MT5 history. The
                # ``position=`` kwarg of history_deals_get is unreliable on
                # some brokers — they return ALL deals in the window. Filter
                # by position_id manually to be safe.
                from datetime import timedelta as _td
                end = datetime.now(timezone.utc) + _td(hours=24)
                start = datetime.now(timezone.utc) - _td(hours=48)
                deals = mt5.history_deals_get(start, end) or []
                out_deal = next(
                    (d for d in deals
                     if int(getattr(d, "position_id", 0)) == int(ticket)
                     and d.entry == mt5.DEAL_ENTRY_OUT), None)
                if out_deal is None:
                    # Fallback: position-targeted query (works on most brokers)
                    deals = mt5.history_deals_get(position=int(ticket)) or []
                    out_deal = next(
                        (d for d in deals
                         if int(getattr(d, "position_id", 0)) == int(ticket)
                         and d.entry == mt5.DEAL_ENTRY_OUT), None)
                if out_deal is None:
                    log.warning("close detected for %s but no OUT deal found", ticket)
                    # Drop it from state anyway — don't keep retrying
                    state.pop(str(int(ticket)), None)
                    _research_save_state(state)
                    continue
                pnl = float(out_deal.profit or 0.0)
                exit_price = float(out_deal.price)
                # Heuristic exit_reason
                snap = state.get(str(int(ticket)), {}) or {}
                orig_sl = float(snap.get("original_sl") or 0)
                orig_tp = float(snap.get("original_tp") or 0)
                side = snap.get("side", "buy")
                reason = "UNKNOWN"
                if pnl > 0 and orig_tp:
                    near_tp = abs(exit_price - orig_tp) <= 0.0010 * (orig_tp or 1)
                    if near_tp:
                        reason = "TP_HIT"
                    elif snap.get("be_moved") or snap.get("trail_count", 0) > 0:
                        reason = "TRAILING_TP"
                    else:
                        reason = "EARLY_TAKE"
                elif pnl <= 0:
                    if snap.get("be_moved") or snap.get("trail_count", 0) > 0:
                        reason = "TRAILING_SL"
                    elif orig_sl:
                        near_sl = abs(exit_price - orig_sl) <= 0.0010 * (orig_sl or 1)
                        reason = "SL_HIT" if near_sl else "MANUAL_OR_EARLY"
                    else:
                        reason = "MANUAL_OR_EARLY"
                # r_multiple
                entry = float(snap.get("entry") or out_deal.price)
                sl_dist = abs(entry - orig_sl) if orig_sl else 0.0
                # Compute risk_usd properly via tick_value
                try:
                    info = mt5.symbol_info(out_deal.symbol)
                    tick_size = float(info.trade_tick_size or info.point or 1e-5)
                    tick_value = float(info.trade_tick_value or 1.0)
                    risk_usd = (sl_dist / tick_size) * tick_value * float(out_deal.volume) \
                        if (sl_dist > 0 and tick_size > 0) else 0.0
                except Exception:  # noqa: BLE001
                    risk_usd = 0.0
                r_mult = round(pnl / risk_usd, 2) if risk_usd > 0 else 0.0
                _research_close(
                    ticket=int(ticket), exit_price=exit_price,
                    pnl_usd=pnl, r_multiple=r_mult, exit_reason=reason,
                )
                _audit({"iter": iteration, "phase": "research_close",
                        "ticket": ticket, "exit": exit_price,
                        "pnl": pnl, "r": r_mult, "reason": reason})
                # Telegram: trade closed (demo/live) -- full post-mortem
                # Compute duration + MFE/MAE from state snapshot
                _tg_dur_s = None
                _tg_opened = snap.get("opened_at")
                if _tg_opened:
                    try:
                        _tg_o = datetime.fromisoformat(str(_tg_opened).replace("Z", "+00:00"))
                        _tg_dur_s = int((datetime.now(timezone.utc) - _tg_o).total_seconds())
                    except (ValueError, TypeError):
                        pass
                _tg_sl_dist = abs(entry - orig_sl) if orig_sl else 0.0
                if _tg_sl_dist > 0:
                    if side == 'buy':
                        _tg_mfe = (snap.get("max_favorable_price", entry) - entry) / _tg_sl_dist
                        _tg_mae = (entry - snap.get("max_adverse_price", entry)) / _tg_sl_dist * -1
                    else:
                        _tg_mfe = (entry - snap.get("max_favorable_price", entry)) / _tg_sl_dist
                        _tg_mae = (snap.get("max_adverse_price", entry) - entry) / _tg_sl_dist * -1
                else:
                    _tg_mfe = _tg_mae = 0.0
                _ci = "\U0001f7e2" if pnl > 0 else ("\U0001f534" if pnl < 0 else "⚪")
                _cs = "compra" if side == "buy" else "venta"
                if _tg_dur_s is not None:
                    _ch = _tg_dur_s // 3600
                    _cm = (_tg_dur_s % 3600) // 60
                    _cd = f"{_ch}h {_cm}m" if _ch > 0 else f"{_cm}m"
                else:
                    _cd = "?"
                _tg_wl2 = "Ganó" if pnl > 0 else "Perdió"
                _tg_send(
                    f"{_ci} *{_tg_wl2}:* {out_deal.symbol}\n"
                    f"P&L: *${pnl:+.2f}* · Duración: {_cd}"
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("research close write failed for %s: %s", ticket, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("close detection failed: %s", exc)

    # Cargar state una sola vez para todos los tickets del loop. Si el load
    # falla, usamos {} y los lookups por ticket retornarán None — el código
    # tiene fallbacks (ATR actual × 1.5).
    try:
        state = _research_load_state()
    except Exception:  # noqa: BLE001
        state = {}

    for p in positions:
        try:
            sym = p.symbol
            side = "buy" if p.type == 0 else "sell"
            entry = float(p.price_open)
            current_sl = float(p.sl) if p.sl else 0.0
            current_tp = float(p.tp) if p.tp else 0.0

            tick = mt5.symbol_info_tick(sym)
            if tick is None:
                continue
            current_price = tick.bid if side == "buy" else tick.ask

            # Update MAE/MFE tracking for this position (cheap, runs every iter)
            try:
                _research_update_excursion(int(p.ticket), float(current_price))
            except Exception:  # noqa: BLE001
                pass

            # Initial SL distance — anchor para R-progress. Preferimos lo que
            # se persistió en position_state.json al abrir (atr_at_entry +
            # sl_atr_mult según la estrategia). Si no existe (posiciones
            # legacy abiertas antes de este fix), reconstruimos desde:
            #   1) la distancia entry→original_sl si está en state
            #   2) ATR actual × SL multiplier de la estrategia activa
            #   3) ATR actual × 1.5 (fallback)
            ticket_state = state.get(str(int(p.ticket)), {}) if isinstance(state, dict) else {}
            atr_at_entry = float(ticket_state.get("atr_at_entry") or 0.0)
            sl_mult_from_state = float(ticket_state.get("sl_atr_mult") or 0.0)
            initial_sl_distance = 0.0
            orig_sl_state = float(ticket_state.get("original_sl") or 0.0)
            if orig_sl_state > 0:
                # Mejor: usar la distancia exacta al SL original
                initial_sl_distance = abs(entry - orig_sl_state)
            elif atr_at_entry > 0 and sl_mult_from_state > 0:
                initial_sl_distance = atr_at_entry * sl_mult_from_state
            if initial_sl_distance <= 0:
                # Fallback final: ATR actual × 1.5 (compat con código viejo)
                m15 = trading.get_rates(sym, "M15", 50)
                bars = m15.get("bars") if isinstance(m15, dict) else None
                if not bars:
                    continue
                atr_now = _atr_distance(bars)
                if atr_now <= 0:
                    continue
                initial_sl_distance = atr_now * 1.5

            # Para el TRAILING (paso 2) sí necesitamos ATR actual (no del entry)
            m15 = trading.get_rates(sym, "M15", 50)
            bars = m15.get("bars") if isinstance(m15, dict) else None
            if not bars:
                continue
            atr = _atr_distance(bars)
            if atr <= 0:
                continue

            r = _r_progress(side, entry, initial_sl_distance, current_price)
            sl_at_or_past_entry = (
                (side == "buy" and current_sl >= entry > 0) or
                (side == "sell" and 0 < current_sl <= entry)
            )

            if r < 1.0:
                # Not far enough into profit yet — leave alone
                continue

            # === Phase 1: breakeven ===
            if not sl_at_or_past_entry:
                # Round to symbol precision
                info = mt5.symbol_info(sym)
                digits = info.digits if info else 5
                new_sl = round(entry, digits)
                # Same-side guard: SL must not move the wrong way (server's
                # modify_sl_tp also enforces this).
                if (side == "buy" and new_sl <= current_sl and current_sl > 0) or \
                   (side == "sell" and new_sl >= current_sl and current_sl > 0):
                    continue
                resp = trading.modify_sl_tp(int(p.ticket), sl=new_sl,
                                             tp=current_tp or None)
                ok = bool(resp.get("ok"))
                _audit({
                    "iter": iteration, "phase": "manage",
                    "action": "breakeven",
                    "ticket": int(p.ticket), "symbol": sym,
                    "old_sl": current_sl, "new_sl": new_sl,
                    "rr_progress": round(r, 2),
                    "result": resp,
                })
                if ok:
                    log.info("BE %s ticket=%d sl %s -> %s (R=%.2f)",
                             sym, p.ticket, current_sl, new_sl, r)
                    _research_manage(
                        ticket=int(p.ticket), action="breakeven",
                        old_sl=current_sl, new_sl=new_sl,
                        rr_progress=r, current_price=current_price,
                    )
                    side_es = "compra" if side == "buy" else "venta"
                    # SILENCED: SL breakeven telegram
                continue

            # === Phase 2: ATR trailing — usa el multiplier de la estrategia ===
            # Antes hardcoded 1.0 × ATR para todos. Ahora usamos el sl_atr_mult
            # de la estrategia que abrió el trade (1.5 trend_rider, 2.0
            # breakout_hunter, etc.). El trail debe respetar la "amplitud"
            # original del SL para no estrangular el setup.
            trail_mult = sl_mult_from_state if sl_mult_from_state > 0 else 1.0
            info = mt5.symbol_info(sym)
            digits = info.digits if info else 5
            if side == "buy":
                proposed = round(current_price - trail_mult * atr, digits)
                # Only move SL UP for buy
                if proposed <= current_sl:
                    continue
            else:
                proposed = round(current_price + trail_mult * atr, digits)
                # Only move SL DOWN for sell
                if proposed >= current_sl:
                    continue

            resp = trading.modify_sl_tp(int(p.ticket), sl=proposed,
                                         tp=current_tp or None)
            ok = bool(resp.get("ok"))
            _audit({
                "iter": iteration, "phase": "manage",
                "action": "trail",
                "ticket": int(p.ticket), "symbol": sym,
                "old_sl": current_sl, "new_sl": proposed,
                "rr_progress": round(r, 2),
                "result": resp,
            })
            if ok:
                log.info("TRAIL %s ticket=%d sl %s -> %s (R=%.2f)",
                         sym, p.ticket, current_sl, proposed, r)
                _research_manage(
                    ticket=int(p.ticket), action="trail",
                    old_sl=current_sl, new_sl=proposed,
                    rr_progress=r, current_price=current_price,
                )
                side_es = "compra" if side == "buy" else "venta"
                # SILENCED: SL trailing telegram
        except Exception as exc:  # noqa: BLE001
            log.warning("manage failed for ticket %s: %s",
                        getattr(p, "ticket", "?"), exc)
            continue


def _atr_distance(bars, default=0.0010) -> float:
    """ATR(14) on the last bar — fallback to a sensible default."""
    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    if len(closes) < 20:
        return default
    import numpy as np
    a = indicators.atr(np.array(highs), np.array(lows), np.array(closes), 14)
    last = a[-1] if len(a) and not np.isnan(a[-1]) else default
    return float(last) if last > 0 else default


def _bar_is_closed_enough(bars_m15: list, min_age_sec: int) -> bool:
    """Anti-repaint: la última barra M15 debe tener al menos ``min_age_sec``
    segundos de antigüedad. Una barra "casi cerrada" (>=14min en M15) es
    estable. Una barra fresca (0-30s) cambia con cada tick.

    Si min_age_sec == 0, la check está desactivada.
    """
    if min_age_sec <= 0 or not bars_m15:
        return True
    try:
        last_bar = bars_m15[-1]
        bar_time_iso = last_bar.get("time")
        if not bar_time_iso:
            return True
        bar_dt = datetime.fromisoformat(str(bar_time_iso).replace("Z", "+00:00"))
        age_sec = (datetime.now(timezone.utc) - bar_dt).total_seconds()
        return age_sec >= min_age_sec
    except (ValueError, TypeError, KeyError):
        return True  # data inválida → no bloquear (better than crash)


def _dedup_key(strategy_id: str, symbol: str, bars_m15: list) -> str | None:
    """Clave de dedup para anti-repaint: no re-emitir la misma propuesta
    sobre la misma barra."""
    if not bars_m15:
        return None
    try:
        return f"{strategy_id}:{symbol}:{bars_m15[-1].get('time', '?')}"
    except Exception:  # noqa: BLE001
        return None


def _propose_setup(bars_m15, bars_h4, bars_d1, tick,
                    current_regime: str | None = None) -> list:
    """Multi-strategy: all eligible strategies propose signals.

    Filtros nuevos:
      - Anti-repaint: si la barra M15 está fresca (< ANTI_REPAINT_MIN_BAR_AGE_SEC),
        descarta toda propuesta para evitar disparar sobre una barra incompleta.
      - Regime gate: si ``current_regime`` está informado, filtra estrategias
        cuyos valid_regimes no lo incluyen (mean_reverter en TREND, etc.).
      - Dedup: mismo (strategy_id, symbol, bar_open_time) → no propone otra vez.
      - Expectancy gate: si la combo (strategy:symbol) tiene verdict NEGATIVE
        con n suficiente, descarta el setup (no perder más en lo que ya pierde).
    """
    if not tick:
        return []
    sym = getattr(_propose_setup, '_current_symbol', 'UNKNOWN')

    # Anti-repaint: barra cerrada o configurable a 0 (desactivado)
    if not _bar_is_closed_enough(bars_m15, ANTI_REPAINT_MIN_BAR_AGE_SEC):
        return []

    eligible = strat_engine.get_eligible_strategies()
    proposals = []
    for strategy in eligible:
        sid = strategy.id
        # Regime gate
        if current_regime and not regime_mod.is_strategy_compatible(sid, current_regime):
            continue
        # Dedup por barra
        key = _dedup_key(sid, sym, bars_m15)
        if key and key in _LAST_PROPOSED:
            continue
        # Expectancy gate: NEGATIVE con n>=15 → no abrir nuevos trades
        edge = expectancy_tracker.edge_status(sid, sym)
        if edge.get("verdict") == "NEGATIVE":
            # No spam de logs; solo registramos una vez por barra
            if key:
                _LAST_PROPOSED[key] = time.time()
            continue
        try:
            signals = strategy.propose(sym, tick, bars_m15, bars_h4, bars_d1)
            for s in signals:
                proposals.append({
                    "side": s.side, "entry": s.entry, "sl": s.sl,
                    "tp": s.tp, "atr": s.atr, "score": s.score,
                    "rec": s.rec, "breakdown": s.breakdown,
                    "strategy_id": s.strategy_id,
                    "extra": s.extra,
                    "edge": edge,                # info para audit / sizing
                    "regime": current_regime,
                })
            # Marca el dedup tras procesar (independientemente de si emitió)
            if key:
                _LAST_PROPOSED[key] = time.time()
        except Exception as exc:
            log.warning("strategy %s failed for %s: %s", strategy.id, sym, exc)
    return proposals


def _purge_dedup_cache(max_entries: int = 5000) -> None:
    """Limpia entries viejos del dedup cache (>2h) para que no crezca infinito."""
    if len(_LAST_PROPOSED) < max_entries:
        return
    cutoff = time.time() - 2 * 3600
    stale = [k for k, ts in _LAST_PROPOSED.items() if ts < cutoff]
    for k in stale:
        del _LAST_PROPOSED[k]


def _detect_regime_for(symbol: str) -> dict:
    """Pulls H4+D1 bars y corre regime detector. Retorna {regime, details}.
    Cacheado de forma simple por símbolo (1 vez cada N min)."""
    cache = getattr(_detect_regime_for, "_cache", {})
    last = cache.get(symbol)
    now = time.time()
    if last and now - last["ts"] < 600:   # cache 10 min
        return last["data"]
    try:
        d1 = trading.get_rates(symbol, "D1", 250)
        h4 = trading.get_rates(symbol, "H4", 250)
        bars_d1 = d1.get("bars") if isinstance(d1, dict) else None
        bars_h4 = h4.get("bars") if isinstance(h4, dict) else None
        tick = trading.get_tick(symbol)
        cur_price = float(tick.get("bid", 0) or 0) if isinstance(tick, dict) else 0
        result = regime_mod.detect(bars_d1 or [], bars_h4 or [], cur_price)
    except Exception as exc:  # noqa: BLE001
        log.debug("regime detect failed for %s: %s", symbol, exc)
        result = {"regime": "UNKNOWN", "details": {"error": str(exc)}}
    cache[symbol] = {"ts": now, "data": result}
    _detect_regime_for._cache = cache
    return result

def _save_last_scan(best, candidates) -> None:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "best": best,
        "candidates": candidates,
    }
    try:
        LAST_SCAN_FILE.write_text(
            json.dumps(payload, indent=2, default=str),
            encoding="utf-8",
        )
    except OSError:
        pass


def _scan(watchlist) -> tuple:
    """Returns (best, iteration_log).

    Filtros aplicados antes de evaluar estrategia:
      - cooldown post-rejection del símbolo (skip)
      - regime detector (pasado a _propose_setup para gate por estrategia)
    """
    best = None
    iteration_log = []
    now = time.time()
    for sym in watchlist:
        # Skip si está en cooldown post-rejection
        cool_until = _SYMBOL_COOLDOWN_UNTIL.get(sym, 0)
        if cool_until > now:
            iteration_log.append({"symbol": sym, "status": "cooldown",
                                  "remaining_min": int((cool_until - now) / 60)})
            continue
        try:
            tick_resp = trading.get_tick(sym)
            if tick_resp.get("ok") is False:
                iteration_log.append({"symbol": sym, "status": "no-tick"})
                continue
            m15 = trading.get_rates(sym, "M15", 200)
            if "bars" not in m15:
                iteration_log.append({"symbol": sym, "status": "no-bars-m15"})
                continue
            h4 = trading.get_rates(sym, "H4", 200)
            h4_bars = h4.get("bars") if "bars" in h4 else None
            d1 = trading.get_rates(sym, "D1", 100)
            d1_bars = d1.get("bars") if "bars" in d1 else None

            # Régimen del símbolo (cacheado 10 min)
            regime_info = _detect_regime_for(sym)
            current_regime = regime_info.get("regime")

            _propose_setup._current_symbol = sym  # pass symbol context
            proposals = _propose_setup(m15["bars"], h4_bars, d1_bars, tick_resp,
                                        current_regime=current_regime)
            if not proposals:
                iteration_log.append({"symbol": sym, "status": "no-proposals",
                                      "regime": current_regime})
                continue
            for p in proposals:
                iteration_log.append({"symbol": sym, **p})
                if best is None or p["score"] > best["score"]:
                    best = {"symbol": sym, **p}
        except Exception as exc:  # noqa: BLE001
            log.exception("scan failed for %s", sym)
            iteration_log.append({"symbol": sym, "error": str(exc)})
    _save_last_scan(best, iteration_log)
    _purge_dedup_cache()
    return best, iteration_log


def _symbol_size_inputs(symbol: str) -> dict | None:
    """Pulls tick_size + tick_value + volume_step from MT5 symbol metadata."""
    info = mt5.symbol_info(symbol)
    if info is None:
        if not mt5.symbol_select(symbol, True):
            return None
        info = mt5.symbol_info(symbol)
    if info is None:
        return None
    return {
        "tick_size":   float(info.trade_tick_size or info.point or 0.00001),
        "tick_value":  float(info.trade_tick_value or 1.0),
        "volume_step": float(info.volume_step or 0.01),
        "volume_min":  float(info.volume_min or 0.01),
        "volume_max":  float(info.volume_max or 100.0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=300,
                    help="seconds between scans (default 300)")
    ap.add_argument("--risk-pct", type=float, default=1.0,
                    help="risk percent per trade (default 1.0)")
    ap.add_argument("--min-score", type=int, default=40,
                    help="min composite score to enter (default 70)")
    ap.add_argument("--symbols", default=None,
                    help="comma-separated watchlist override")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    watchlist = (args.symbols.split(",") if args.symbols else WATCHLIST_DEFAULT)
    watchlist = [s.strip() for s in watchlist if s.strip()]

    _active_name = strat_engine.get_active_strategy().name
    log.info("auto-trader starting — interval=%ss risk=%.1f%% min_score=%d watchlist=%s",
             args.interval, args.risk_pct, args.min_score, watchlist)

    # Inicializar capital_ledger con el balance real de MT5 (si está conectado).
    # Esto reemplaza el patrón anterior de "balance hardcodeado $800":
    # ahora tenemos starting_balance separado del target y peak tracking real.
    try:
        _h0 = trading.health()
        if _h0.get("connected") and _h0.get("account"):
            _bal0 = float(_h0["account"].get("balance") or 0)
            if _bal0 > 0:
                _ld = capital_ledger.init_if_empty(_bal0)
                log.info("capital_ledger: target=$%.2f starting=$%.2f current=$%.2f peak=$%.2f",
                         _ld.get("target_capital_usd") or 0,
                         _ld.get("starting_balance_usd") or 0,
                         _ld.get("current_balance_usd") or 0,
                         _ld.get("peak_equity_usd") or 0)
    except Exception as _exc_l:
        log.warning("capital_ledger init failed: %s", _exc_l)

    _tg_send(
        f"🤖 *Bot iniciado*\n"
        f"Cada {args.interval}s · Riesgo {args.risk_pct}% · Score mín {args.min_score}"
    )
    _audit({"event": "start", "interval": args.interval, "risk_pct": args.risk_pct,
            "min_score": args.min_score, "watchlist": watchlist})

    iteration = 0
    while _running:
        iteration += 1
        try:
            # 0. kill-switch
            if halt_mod.is_halted():
                log.info("HALT armed — skipping iteration")
                _audit({"iter": iteration, "skip": "HALTED",
                        "reason": halt_mod.reason()})
                _sleep(args.interval)
                continue

            # 1. account state + already-open positions
            health = trading.health()
            if not health.get("connected"):
                log.warning("MT5 disconnected — waiting")
                _audit({"iter": iteration, "skip": "MT5_DISCONNECTED"})
                _sleep(args.interval)
                continue

            # 1.4 manage existing demo/live positions (BE + ATR trailing).
            # Runs BEFORE the paper monitor so MT5 SL changes propagate before
            # any other check.
            _manage_open_positions(iteration)

            # Periodic summary every 12 iterations (~1 hour at 5min interval)
            # Count closed trades today for summary trigger
            _closed_trade_count = 0
            try:
                _ctd = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                with open(RESEARCH_LOG, "r") as _ctf:
                    for _ctl in _ctf:
                        try:
                            _ctr = json.loads(_ctl)
                            if _ctr.get("event") == "close" and _ctr.get("ts", "").startswith(_ctd):
                                _closed_trade_count += 1
                        except (json.JSONDecodeError, ValueError):
                            pass
            except FileNotFoundError:
                pass
            if _closed_trade_count > 0 and _closed_trade_count % 10 == 0 and _closed_trade_count != getattr(_tg_send, "_last_summary_at", -1):
                try:
                    _sa = trading.get_account_info()
                    _sp = trading.get_open_positions().get("positions", [])
                    _sb = _sa.get("balance", 0)
                    _se = _sa.get("equity", 0)
                    _sf = _sa.get("profit", 0)
                    _sm = _sa.get("margin_free", 0)
                    _ss = [p["symbol"] for p in _sp]
                    _sd = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    _sw = _sl2 = 0
                    _st = 0.0
                    try:
                        with open(RESEARCH_LOG, "r") as _srf:
                            for _sln in _srf:
                                try:
                                    _sr = json.loads(_sln)
                                    if _sr.get("event") == "close" and _sr.get("ts", "").startswith(_sd):
                                        _spnl = float(_sr.get("pnl_usd", 0))
                                        _st += _spnl
                                        if _spnl > 0: _sw += 1
                                        elif _spnl < 0: _sl2 += 1
                                except (json.JSONDecodeError, ValueError):
                                    pass
                    except FileNotFoundError:
                        pass
                    _so = f" ({', '.join(_ss)})" if _ss else ""
                    _tg_send(
                        f"📊 *Resumen* (iter {iteration})\n"
                        f"Balance: ${_sb:.2f} · P&L hoy: ${_st:+.2f}\n"
                        f"Hoy: {_sw}W / {_sl2}L · Posiciones: {len(_sp)}"
                    )
                except Exception as _sx:
                    log.debug("periodic summary failed: %s", _sx)
                # Mark that we sent summary at this count
                _tg_send._last_summary_at = _closed_trade_count

            # 1.5 monitor open paper trades (always, even if we won't open new)
            monitor = _monitor_paper_trades()
            for closed in monitor["closed"]:
                log.info("PAPER %s closed: %s @ %s pnl=$%.2f (%sR)",
                         closed["symbol"], closed["status"],
                         closed["exit_price"], closed["pnl_usd"],
                         closed["r_multiple"])
                _audit({"iter": iteration, "phase": "close",
                        "trade": closed})

            acc = trading.get_account_info()
            mt5_positions = trading.get_open_positions().get("positions", [])
            balance = acc.get("balance", 0.0)
            equity = acc.get("equity", balance) or balance

            # Capital ledger: actualiza balance/peak + detecta drift sospechoso
            try:
                _drift = capital_ledger.is_drift_suspicious(balance)
                if _drift:
                    log.warning("capital drift detected: %s", _drift["hint"])
                    _audit({"iter": iteration, "event": "capital_drift", **_drift})
                    _tg_send(
                        f"⚠️ *Cambio de balance no esperado*\n"
                        f"{_drift['hint']}"
                    )
                capital_ledger.update_balance(balance, equity)
            except Exception as _exc_cl:
                log.debug("capital_ledger update failed: %s", _exc_cl)

            # Multi-symbol: hasta MAX_OPEN_POSITIONS posiciones, máximo 1 por símbolo.
            from rules import MAX_OPEN_POSITIONS  # noqa: WPS433  late import
            paper_trades = _load_paper_open()
            paper_open_n = len(paper_trades)
            total_open = len(mt5_positions) + paper_open_n
            open_symbols = {p["symbol"].upper() for p in mt5_positions} | \
                            {p["symbol"].upper() for p in paper_trades}
            # if total_open >= MAX_OPEN_POSITIONS:
                # log.info("max positions hit (%d/%d) — passing",
                         # total_open, MAX_OPEN_POSITIONS)
                # _audit({"iter": iteration, "skip": "MAX_POSITIONS_BOT",
                        # "balance": balance, "open_symbols": list(open_symbols)})
                # _sleep(args.interval)
                # continue

            if balance <= 0:
                log.warning("balance %.2f — nothing to risk", balance)
                _audit({"iter": iteration, "skip": "NO_BALANCE",
                        "balance": balance})
                _sleep(args.interval)
                continue

            # 2. scan — exclude symbols we already have a position in
            scannable = [s for s in watchlist if s.upper() not in open_symbols]
            if not scannable:
                _audit({"iter": iteration, "skip": "ALL_SYMBOLS_OPEN",
                        "open_symbols": list(open_symbols)})
                _sleep(args.interval)
                continue
            best, scan_log = _scan(scannable)
            _audit({"iter": iteration, "phase": "scan", "balance": balance,
                    "best_score": best["score"] if best else 0,
                    "open_symbols": list(open_symbols),
                    "candidates": scan_log})

            if best is None or best["score"] < args.min_score:
                log.info("no setup ≥ %d (best %s)", args.min_score,
                         best["score"] if best else "n/a")
                if iteration % 6 == 0:
                    _nt = sorted(
                        [c for c in scan_log if "score" in c],
                        key=lambda x: -int(x.get("score", 0))
                    )[:5]
                    _nl = []
                    for _nc in _nt:
                        _nl.append(
                            f"  {_nc.get('symbol','')} {_nc.get('side','')} "
                            f"score={_nc.get('score','')} {_nc.get('rec','')}"
                        )
                    _ns = NL.join(_nl) if _nl else "  ninguno"
                    # SILENCED: sin señal telegram
                _sleep(args.interval)
                continue

            # === GLOBAL HARD FILTERS (v3) ===
            # Spread filter: reject if spread eats too much of SL distance
            # DISABLED: _gf_tick = trading.get_tick(best["symbol"])
            # DISABLED: if _gf_tick.get("ok") is not False:
                # DISABLED: _gf_spread = abs(float(_gf_tick.get("ask", 0)) - float(_gf_tick.get("bid", 0)))
                # DISABLED: _gf_sl_dist = abs(best["entry"] - best["sl"])
                # DISABLED: _gf_spread_pct = (_gf_spread / _gf_sl_dist * 100) if _gf_sl_dist > 0 else 999
                # DISABLED: if _gf_spread_pct > MAX_SPREAD_PCT_OF_R:
                    # DISABLED: log.info("SPREAD FILTER: %s %.1f%% > %.0f%% — skip",
                             # DISABLED: best["symbol"], _gf_spread_pct, MAX_SPREAD_PCT_OF_R)
                    # DISABLED: _audit({"iter": iteration, "skip": "SPREAD_TOO_HIGH",
                            # DISABLED: "symbol": best["symbol"], "spread_pct": round(_gf_spread_pct, 1)})
                    # DISABLED: _sleep(args.interval)
                    # DISABLED: continue
 # DISABLED:             # Session filter: REMOVED — each strategy defines its own trading hours
            # via strategy.hard_filter() -> base.is_in_trading_hours()
            # DISABLED: _gf_hour = datetime.now(timezone.utc).hour
 # DISABLED:             # Strategy-specific hard filter (use the strategy that proposed the signal)
            # DISABLED: _hf_strat_id = best.get("strategy_id", "")
            # DISABLED: _active_strat = strat_engine.REGISTRY.get(_hf_strat_id, strat_engine.get_active_strategy())
            # DISABLED: if hasattr(best, 'get') and best.get("extra"):
                # DISABLED: # Build a mock signal for the hard filter
                # DISABLED: from strategies.base import Signal as _Sig
                # DISABLED: _mock = _Sig(
                    # DISABLED: symbol=best["symbol"], side=best["side"],
                    # DISABLED: entry=best["entry"], sl=best["sl"], tp=best["tp"],
                    # DISABLED: atr=best.get("atr", 0), score=best["score"],
                    # DISABLED: rec=best["rec"], breakdown=best.get("breakdown", {}),
                    # DISABLED: strategy_id=best.get("strategy_id", ""),
                    # DISABLED: extra=best.get("extra", {}),
                # DISABLED: )
                # DISABLED: _hf_pass, _hf_reason = _active_strat.hard_filter(_mock, _gf_tick)
                # DISABLED: if not _hf_pass:
                    # DISABLED: log.info("STRATEGY FILTER: %s %s — skip", best["symbol"], _hf_reason)
                    # DISABLED: _audit({"iter": iteration, "skip": "STRATEGY_FILTER",
                            # DISABLED: "symbol": best["symbol"], "reason": _hf_reason})
                    # DISABLED: _sleep(args.interval)
                    # DISABLED: continue
            # 2.5 CORRELATION FILTER — bloquea concentración silenciosa
            # Hoy el bot abre 5 trades USDxxx pensando que está diversificado;
            # son una sola apuesta direccional con 5x leverage.
            _all_open = list(mt5_positions) + [
                {"symbol": p["symbol"], "side": p["side"]} for p in paper_trades
            ]
            _conc = corr_mod.would_concentrate(
                new_symbol=best["symbol"], new_side=best["side"],
                open_positions=_all_open,
                threshold=float(os.environ.get("CORR_THRESHOLD", "0.65")),
            )
            if _conc:
                log.info("correlation filter blocked %s: %s",
                         best["symbol"], _conc.get("detail") or _conc.get("reason"))
                _audit({"iter": iteration, "skip": "CORRELATED_CONCENTRATION",
                        "symbol": best["symbol"], **_conc})
                # Cooldown corto: el setup volverá a ser válido si las
                # posiciones correlacionadas se cierran.
                _SYMBOL_COOLDOWN_UNTIL[best["symbol"]] = time.time() + 10 * 60
                _sleep(args.interval)
                continue

            # 3. size — KELLY FRACTION ESCALADO POR SCORE Y EXPECTANCY
            sym_info = _symbol_size_inputs(best["symbol"])
            if sym_info is None:
                log.warning("no symbol info for %s — skip", best["symbol"])
                _sleep(args.interval)
                continue

            # Kelly multiplier: si la combo (strategy:symbol) tiene historia
            # con expectancy probada, escala risk_pct hacia arriba (hasta 1.5x).
            # Si tiene expectancy negativa, retorna risk_pct = 0 (no tradear).
            try:
                from rules import MAX_RISK_PER_TRADE_PCT as _MAX_R
            except ImportError:
                _MAX_R = 5.0
            _edge_stats = best.get("edge", {}) or {}
            _exp_combo = expectancy_tracker.list_combos(min_n=0)
            _combo_key = f"{best.get('strategy_id','?')}:{best['symbol']}"
            _stats = _exp_combo.get(_combo_key) or {}
            _kelly = sizing_kelly.compute(
                base_risk_pct=float(args.risk_pct),
                score=int(best.get("score", 0)),
                expectancy_stats=_stats,
                max_risk_pct=float(_MAX_R),
            )
            _eff_risk_pct = _kelly["risk_pct"]
            if _eff_risk_pct <= 0.0:
                log.info("kelly = 0 for %s (%s) — skip",
                         best["symbol"], _kelly["components"].get("reason"))
                _audit({"iter": iteration, "skip": "KELLY_ZERO",
                        "symbol": best["symbol"], "kelly": _kelly})
                _SYMBOL_COOLDOWN_UNTIL[best["symbol"]] = time.time() + \
                    SYMBOL_COOLDOWN_AFTER_REJECT_MIN * 60
                _sleep(args.interval)
                continue

            # max_lot dinámico: cap absoluto + cap por NOCIONAL.
            # Antes era 0.5 lots fijo — pero 0.5 lots BTCUSD a $77k = $38k
            # exposure en cuenta de $200 = 190x leverage = una vela ATR mata
            # la cuenta. El nocional cap evita esto.
            #
            # Per-class defaults (env override para tunear):
            #   - FX: hasta 1000% notional (10x lev — usual para 0.01 lots
            #     en cuenta de $200)
            #   - Crypto: 200% notional (2x lev, BTC/ETH ya volátiles)
            #   - Otros: 500% notional default
            _sym_upper = best["symbol"].upper()
            if _sym_upper in {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT", "BTCEUR"}:
                _default_notional_pct = 200.0
                _env_key = "MAX_NOTIONAL_PCT_CRYPTO"
            elif _sym_upper.endswith(("USD", "JPY", "GBP", "EUR", "CHF", "AUD",
                                       "NZD", "CAD")) and len(_sym_upper) == 6:
                _default_notional_pct = 1000.0
                _env_key = "MAX_NOTIONAL_PCT_FX"
            else:
                _default_notional_pct = 500.0
                _env_key = "MAX_NOTIONAL_PCT"
            _max_notional_pct = float(os.environ.get(_env_key,
                                                      str(_default_notional_pct)))
            _contract = sizing_kelly.contract_size_for(best["symbol"])
            _notional_lots = sizing_kelly.notional_max_lots(
                balance=balance,
                current_price=best["entry"],
                contract_size=_contract,
                max_notional_pct=_max_notional_pct,
            )
            _abs_cap = float(os.environ.get("MAX_LOTS_PER_TRADE", "0.5"))
            _eff_max_lot_raw = min(_abs_cap, sym_info["volume_max"], _notional_lots)
            # CRÍTICO: snappear al volume_step del broker antes de pasarlo
            # como max_lot. Sin esto, `risk_sizing.calc_position_size` puede
            # devolver lots como 0.0147 que MT5 rechaza con retcode=10014
            # ("Invalid volume").
            import math as _math
            _step = sym_info["volume_step"] or 0.01
            _eff_max_lot = _math.floor(_eff_max_lot_raw / _step) * _step
            _eff_max_lot = round(_eff_max_lot, 4)
            # Si el cap nocional pone el max_lot por debajo del mínimo del
            # broker, la cuenta es muy chica para tradear este símbolo —
            # NO override forzado al min, mejor saltar (preserva el sentido
            # del cap nocional).
            if _eff_max_lot < sym_info["volume_min"]:
                log.info("notional cap < min_lot for %s (max=%.4f min=%.4f) — skip",
                         best["symbol"], _eff_max_lot, sym_info["volume_min"])
                _audit({"iter": iteration, "skip": "NOTIONAL_TOO_SMALL",
                        "symbol": best["symbol"],
                        "max_lot_calculated": _eff_max_lot,
                        "min_lot_broker": sym_info["volume_min"],
                        "max_notional_pct_used": _max_notional_pct})
                _SYMBOL_COOLDOWN_UNTIL[best["symbol"]] = time.time() + 30 * 60
                _sleep(args.interval)
                continue

            size = risk_sizing.calc_position_size(
                balance=balance,
                risk_pct=_eff_risk_pct,
                entry=best["entry"], sl=best["sl"],
                tick_value=sym_info["tick_value"],
                tick_size=sym_info["tick_size"],
                lot_step=sym_info["volume_step"],
                min_lot=sym_info["volume_min"],
                max_lot=_eff_max_lot,
            )
            log.info("setup %s %s score=%d kelly_pct=%.3f%% lots=%s risk=$%s edge=%s",
                     best["symbol"], best["side"], best["score"],
                     _eff_risk_pct, size.get("lots"), size.get("risk_dollars"),
                     (_edge_stats or {}).get("verdict") or "?")

            if size.get("lots", 0) <= 0:
                _audit({"iter": iteration, "skip": "SIZE_ZERO",
                        "best": best, "size": size, "kelly": _kelly,
                        "max_lot_used": _eff_max_lot})
                _sleep(args.interval)
                continue

            # 4. place_order (mode=paper → synthetic ticket; demo/live → real)
            coid = f"auto-{iteration}-{uuid.uuid4().hex[:8]}"
            result = trading.place_order(
                symbol=best["symbol"], side=best["side"],
                lots=float(size["lots"]),
                sl=float(best["sl"]), tp=float(best["tp"]),
                comment=f"auto[{best['score']}]",
                client_order_id=coid,
            )
            log.info("place_order → %s", result)
            _audit({"iter": iteration, "phase": "order",
                    "best": best, "size": size, "result": result, "coid": coid,
                    "kelly": _kelly})

            # Cooldown automático si place_order rechazó por motivo persistente.
            # Antes el bot reintentaba el mismo USDJPY 139 veces/hora aunque
            # estaba bloqueado por LOW_PROFIT_PAIR.
            if not result.get("ok"):
                _reason = result.get("reason", "")
                if _reason in COOLDOWN_REASONS:
                    _until = time.time() + SYMBOL_COOLDOWN_AFTER_REJECT_MIN * 60
                    _SYMBOL_COOLDOWN_UNTIL[best["symbol"]] = _until
                    log.info("cooldown set for %s due to %s (%d min)",
                             best["symbol"], _reason,
                             SYMBOL_COOLDOWN_AFTER_REJECT_MIN)
                    _audit({"iter": iteration, "phase": "cooldown_set",
                            "symbol": best["symbol"], "reason": _reason,
                            "until": datetime.fromtimestamp(_until, timezone.utc).isoformat()})

            # Research log — capture the full setup snapshot for any successful
            # placement (paper or demo). This is the per-trade feedback record.
            if result.get("ok"):
                try:
                    today_stats = trading._today_trade_stats()  # noqa: SLF001
                    # Spread at entry: real bid-ask gap right now on this symbol
                    cur_tick = trading.get_tick(best["symbol"])
                    spread = None
                    if cur_tick.get("ok") is not False:
                        spread = abs(float(cur_tick.get("ask", 0)) - float(cur_tick.get("bid", 0)))
                    # Runners-up: top 3 candidates from this scan (excluding the chosen one)
                    runners = []
                    for c in scan_log:
                        if c.get("status") or c.get("error"):
                            continue
                        if c.get("symbol") == best["symbol"] and c.get("side") == best["side"]:
                            continue
                        runners.append(c)
                    runners = sorted(runners, key=lambda r: -int(r.get("score", 0)))[:3]
                    _research_open(
                        ticket=int(result["ticket"]),
                        setup=best,
                        lots=float(size["lots"]),
                        risk_dollars=float(size.get("risk_dollars", 0.0)),
                        balance=float(balance),
                        trades_today=int(today_stats.get("trades_today", 0)),
                        consecutive_losses=int(today_stats.get("consecutive_losses_today", 0)),
                        open_positions_before=int(total_open),
                        args=args,
                        watchlist=watchlist,
                        spread=spread,
                        runners_up=runners,
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning("research_open write failed: %s", exc)

            # In paper mode the result has a synthetic ticket. Track it
            # locally so _monitor_paper_trades can close it on SL/TP.
            if result.get("ok") and result.get("mode") == "paper":
                _open_paper_trade(best, float(size["lots"]),
                                   int(result["ticket"]),
                                   balance_at_entry=balance)
                log.info("PAPER opened: %s %s %s lots @ %s (sl %s, tp %s)",
                         best["symbol"], best["side"], size["lots"],
                         best["entry"], best["sl"], best["tp"])
                side_es = "COMPRA" if best["side"] == "buy" else "VENTA"
                _tg_send(
                    f"🟢 *Entró:* {best['symbol']} {side_es}\n"
                    f"Riesgo: ${size.get('risk_dollars', 0):.2f} · "
                    f"{best.get('strategy_id', '?').replace('_', ' ').title()}"
                )

        except Exception as exc:  # noqa: BLE001
            log.exception("iteration crashed")
            _audit({"iter": iteration, "error": str(exc)})

        _sleep(args.interval)

    log.info("clean exit after %d iterations", iteration)
    _audit({"event": "stop", "iterations": iteration})


def _sleep(total: int) -> None:
    slept = 0
    while _running and slept < total:
        time.sleep(1)
        slept += 1


if __name__ == "__main__":
    main()
