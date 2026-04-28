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

DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "http://localhost:8001").rstrip("/")
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
    "USDCHF", "NZDUSD", "USDCAD",
]

ALWAYS_TRADEABLE = {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"}

_running = True


def _on_signal(signum, _frame):
    global _running
    log.info("signal %s — stopping after current iteration", signum)
    _running = False


def _audit(payload: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")


# ============================================================================
# Research log — structured per-trade record for post-test feedback
# ============================================================================

def _research_write(event_type: str, payload: dict) -> None:
    """Append one structured event to the research log. Never raises."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **payload,
        }
        with open(RESEARCH_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
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
    # Seed the state for MAE/MFE tracking
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
    })


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
    _tg_send(
        f"{icon} *Trade cerrado* ({reason})\n"
        f"`{trade['symbol']}` {side_es} @ `{exit_price}`\n"
        f"P&L *${pnl_usd:+.2f}* · {r_multiple:+.2f}R"
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
                    _tg_send(
                        f"⚠️ *PAPER force-close* (monitor stuck)\n"
                        f"`{t['symbol']}` ticket=`{t['ticket']}` — "
                        f"sin tick por {fails} ciclos. Cerrado en entry."
                    )
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
            except Exception as exc:  # noqa: BLE001
                log.warning("research close write failed for %s: %s", ticket, exc)
    except Exception as exc:  # noqa: BLE001
        log.warning("close detection failed: %s", exc)

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

            # Initial SL distance: |entry - initial sl|. The bot opens with
            # SL = 1.0×ATR distance, so we can re-derive 1R by reading the
            # position's CURRENT sl ONLY if it hasn't been moved yet. After
            # the first move, current_sl is at entry (or beyond) so it would
            # under-state 1R. We need a stable anchor: parse it from the
            # comment which we'd need to set, OR re-compute from M15 ATR
            # NOW (close enough — ATR doesn't drift much in minutes).
            m15 = trading.get_rates(sym, "M15", 50)
            bars = m15.get("bars") if isinstance(m15, dict) else None
            if not bars:
                continue
            atr = _atr_distance(bars)
            if atr <= 0:
                continue

            r = _r_progress(side, entry, atr, current_price)
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
                    _tg_send(
                        f"🔒 *SL movido a breakeven*\n"
                        f"`{sym}` {side_es} ticket=`{p.ticket}`\n"
                        f"SL: `{current_sl}` → `{new_sl}` (entry)\n"
                        f"R actual: *+{r:.2f}R*"
                    )
                continue

            # === Phase 2: ATR trailing ===
            info = mt5.symbol_info(sym)
            digits = info.digits if info else 5
            if side == "buy":
                proposed = round(current_price - 1.0 * atr, digits)
                # Only move SL UP for buy
                if proposed <= current_sl:
                    continue
            else:
                proposed = round(current_price + 1.0 * atr, digits)
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
                _tg_send(
                    f"📈 *SL trailing*\n"
                    f"`{sym}` {side_es} ticket=`{p.ticket}`\n"
                    f"SL: `{current_sl}` → `{proposed}`\n"
                    f"R actual: *+{r:.2f}R*"
                )
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


def _propose_setup(bars_m15, bars_h4, bars_d1, tick) -> list:
    """Return up to 2 candidate setups (long, short) with entry/sl/tp."""
    if not tick:
        return []
    atr = _atr_distance(bars_m15)
    if atr <= 0:
        return []
    proposals = []
    for side in ("buy", "sell"):
        entry = tick["ask"] if side == "buy" else tick["bid"]
        # SL 1.0×ATR, TP 2.5×ATR. R:R nominal 2.5 (well above MIN_RR=2.0).
        # The earlier 2.0 and 2.05 multipliers tripped RR_TOO_LOW after the
        # 5-decimal price rounding because the rounding noise on a tight
        # 2.0 ratio drops it under 2.0 about half the time. 2.5× gives the
        # bot real headroom AND better expectancy when the trade wins.
        if side == "buy":
            sl = entry - 1.0 * atr
            tp = entry + 2.5 * atr
        else:
            sl = entry + 1.0 * atr
            tp = entry - 2.5 * atr
        score = scoring.score_setup(bars_m15, side, entry, sl, tp,
                                     ohlcv_h4=bars_h4, ohlcv_d1=bars_d1)
        proposals.append({
            "side": side, "entry": round(entry, 5), "sl": round(sl, 5),
            "tp": round(tp, 5), "atr": round(atr, 5),
            "score": score["score"], "rec": score["recommendation"],
            "breakdown": score["breakdown"],
        })
    return proposals


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


def _scan(watchlist) -> dict | None:
    """Returns the best (highest scoring) setup across the watchlist."""
    best = None
    iteration_log = []
    for sym in watchlist:
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

            proposals = _propose_setup(m15["bars"], h4_bars, d1_bars, tick_resp)
            for p in proposals:
                iteration_log.append({"symbol": sym, **p})
                if best is None or p["score"] > best["score"]:
                    best = {"symbol": sym, **p}
        except Exception as exc:  # noqa: BLE001
            log.exception("scan failed for %s", sym)
            iteration_log.append({"symbol": sym, "error": str(exc)})
    _save_last_scan(best, iteration_log)
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
    ap.add_argument("--min-score", type=int, default=70,
                    help="min composite score to enter (default 70)")
    ap.add_argument("--symbols", default=None,
                    help="comma-separated watchlist override")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    watchlist = (args.symbols.split(",") if args.symbols else WATCHLIST_DEFAULT)
    watchlist = [s.strip() for s in watchlist if s.strip()]

    log.info("auto-trader starting — interval=%ss risk=%.1f%% min_score=%d watchlist=%s",
             args.interval, args.risk_pct, args.min_score, watchlist)
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

            # Multi-symbol: hasta MAX_OPEN_POSITIONS posiciones, máximo 1 por símbolo.
            from rules import MAX_OPEN_POSITIONS  # noqa: WPS433  late import
            paper_trades = _load_paper_open()
            paper_open_n = len(paper_trades)
            total_open = len(mt5_positions) + paper_open_n
            open_symbols = {p["symbol"].upper() for p in mt5_positions} | \
                            {p["symbol"].upper() for p in paper_trades}
            if total_open >= MAX_OPEN_POSITIONS:
                log.info("max positions hit (%d/%d) — passing",
                         total_open, MAX_OPEN_POSITIONS)
                _audit({"iter": iteration, "skip": "MAX_POSITIONS_BOT",
                        "balance": balance, "open_symbols": list(open_symbols)})
                _sleep(args.interval)
                continue

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
                _sleep(args.interval)
                continue

            # 3. size
            sym_info = _symbol_size_inputs(best["symbol"])
            if sym_info is None:
                log.warning("no symbol info for %s — skip", best["symbol"])
                _sleep(args.interval)
                continue

            size = risk_sizing.calc_position_size(
                balance=balance,
                risk_pct=args.risk_pct,
                entry=best["entry"], sl=best["sl"],
                tick_value=sym_info["tick_value"],
                tick_size=sym_info["tick_size"],
                lot_step=sym_info["volume_step"],
                min_lot=sym_info["volume_min"],
                max_lot=min(sym_info["volume_max"], 0.5),
            )
            log.info("setup %s %s score=%d lots=%s risk=%s",
                     best["symbol"], best["side"], best["score"],
                     size.get("lots"), size.get("risk_dollars"))

            if size.get("lots", 0) <= 0:
                _audit({"iter": iteration, "skip": "SIZE_ZERO",
                        "best": best, "size": size})
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
                    "best": best, "size": size, "result": result, "coid": coid})

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
                    f"🟢 *Trade abierto* (paper)\n"
                    f"`{best['symbol']}` {side_es} · {size['lots']} lots\n"
                    f"Entry `{best['entry']}` · SL `{best['sl']}` · TP `{best['tp']}`\n"
                    f"Score `{best['score']}` · riesgo *${size.get('risk_dollars', 0):.2f}*"
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
