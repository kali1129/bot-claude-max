"""trading-mt5-mcp v1.0.0 — the only MCP that touches money.

Exposes MT5 read tools + ``place_order`` with hardcoded pre-trade guards
(see ``lib/guards.py``). All constants come from ``_shared/rules.py``.

Logs to stderr (stdout is reserved for the MCP protocol).
"""
from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Wire up imports BEFORE we touch lib/* so they can resolve `rules`.
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "_shared"))

load_dotenv(HERE / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("trading-mt5-mcp")

import MetaTrader5 as mt5  # noqa: E402  (import after sys.path setup)
from mcp.server.fastmcp import FastMCP  # noqa: E402

import halt as halt_mod  # noqa: E402
from lib import connection, guards, idempotency, logger, sync  # noqa: E402

# Capa 4 ports
from lib.sl_tp_manager import validate_sl_tp as _validate_sl_tp  # noqa: E402
from lib.trailing_stop import evaluate_trailing_stop as _eval_trailing  # noqa: E402
from lib.quality_checks import (  # noqa: E402
    QualityThresholds,
    check_bar_series as _check_bar_series,
    check_quote as _check_quote,
)
from lib.position_reconciliation import reconcile_positions as _reconcile_positions  # noqa: E402


__version__ = "1.0.0"

MODE = os.environ.get("TRADING_MODE", "paper").lower()
MAGIC = int(os.environ.get("MT5_MAGIC", "20260427"))

mcp = FastMCP("trading")


# --------------------------- helpers ---------------------------

TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def _reject(reason: str, detail: str = "", **extra) -> dict:
    return {"ok": False, "reason": reason, "detail": detail, **extra}


def _utc_hour() -> int:
    return datetime.now(timezone.utc).hour


def _utc_minute() -> int:
    return datetime.now(timezone.utc).minute


def _paper_open_positions() -> list:
    """Return paper positions from paper_open.json (patchable in tests)."""
    try:
        paper_file = Path(__file__).parent / "paper_open.json"
        if paper_file.exists():
            import json as _json
            return _json.loads(paper_file.read_text(encoding="utf-8")) or []
    except Exception:  # noqa: BLE001
        pass
    return []


def _paper_pnl_today() -> float:
    """Sum the P&L of paper trades that closed today (UTC)."""
    import json
    from pathlib import Path
    f = Path(__file__).parent / "paper_trades.jsonl"
    if not f.exists():
        return 0.0
    today_iso = datetime.now(timezone.utc).date().isoformat()
    total = 0.0
    try:
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = t.get("closed_at", "")
            if ts.startswith(today_iso):
                total += float(t.get("pnl_usd", 0.0))
    except OSError:
        return 0.0
    return total


# File-lock for the place_order critical section. Two concurrent MCP
# clients both reading "0 positions open" then both submitting would
# bypass MAX_OPEN_POSITIONS=1. The lock serialises read-positions ↔
# order_send so the second caller sees the first call's result via
# idempotency cache or via positions_get returning the new ticket.
_STATE_DIR_ENV = (os.environ.get("STATE_DIR") or "").strip()
if _STATE_DIR_ENV:
    _LOCK_FILE = Path(os.path.expanduser(_STATE_DIR_ENV)) / "place_order.lock"
else:
    _LOCK_FILE = Path(os.path.expanduser(
        os.environ.get("LOG_DIR", "~/mcp/logs"))).parent / "state" / "place_order.lock"


class _PlaceOrderLock:
    """Cross-process exclusive lock around the place_order critical section.
    Uses Win32 LockFileEx on Windows, fcntl.flock on POSIX. Times out after
    30s rather than blocking forever."""

    def __init__(self, path: Path = _LOCK_FILE, timeout: float = 30.0):
        self.path = path
        self.timeout = timeout
        self._fh = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self.path, "a+")
        deadline = time.time() + self.timeout
        if sys.platform == "win32":
            import msvcrt  # type: ignore
            while True:
                try:
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.time() > deadline:
                        self._fh.close(); self._fh = None
                        raise TimeoutError("place_order lock timeout")
                    time.sleep(0.05)
        else:
            import fcntl  # type: ignore
            while True:
                try:
                    fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.time() > deadline:
                        self._fh.close(); self._fh = None
                        raise TimeoutError("place_order lock timeout")
                    time.sleep(0.05)
        return self

    def __exit__(self, *_exc):
        try:
            if self._fh is not None:
                if sys.platform == "win32":
                    import msvcrt  # type: ignore
                    try:
                        self._fh.seek(0)
                        msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl  # type: ignore
                    try:
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass
                self._fh.close()
        finally:
            self._fh = None


def _reconcile_pending(coid: str) -> Optional[dict]:
    """Look up MT5 history for an order whose ``comment == coid``. Used to
    recover from a crash that left an idempotency entry in the PENDING
    state — the broker may or may not have accepted the order.

    Returns:
      - dict with the same shape as a successful place_order if a matching
        deal/order is found in the last hour
      - None if nothing is found (caller may safely re-submit)
    """
    if not coid:
        return None
    try:
        # Window: 1h back is more than enough — pending markers TTL out at 60s
        # but a paranoid window covers slow restarts.
        from datetime import timedelta as _td
        end = datetime.now(timezone.utc)
        start = end - _td(hours=1)
        # Search both deals and orders; the comment field carries either the
        # raw coid (≤30 chars) or the c-<sha1[:28]> hash for longer coids.
        if len(coid) > 30:
            import hashlib as _hl
            needle = "c-" + _hl.sha1(coid.encode("utf-8")).hexdigest()[:28]
        else:
            needle = coid

        deals = mt5.history_deals_get(start, end) or []
        for d in deals:
            if int(getattr(d, "magic", 0)) != int(MAGIC):
                continue
            if (d.comment or "") != needle:
                continue
            if d.entry != mt5.DEAL_ENTRY_IN:
                continue
            return {
                "ok": True,
                "ticket": int(d.order),
                "filled_at": float(d.price),
                "mode": MODE,
                "client_order_id": coid,
                "reconciled_from": "deal",
            }
        # No matching IN deal — also check orders in case the order is still
        # working (rare for IOC but possible).
        orders = mt5.history_orders_get(start, end) or []
        for o in orders:
            if int(getattr(o, "magic", 0)) != int(MAGIC):
                continue
            if (o.comment or "") != needle:
                continue
            return {
                "ok": True,
                "ticket": int(o.ticket),
                "filled_at": float(o.price_open),
                "mode": MODE,
                "client_order_id": coid,
                "reconciled_from": "order",
            }
    except Exception:  # noqa: BLE001
        # Any reconciliation error is safe to swallow — the safe default is
        # "I don't know if it executed" which the caller treats as None →
        # they'll re-submit. The idempotency marker still protects against
        # a third concurrent retry.
        return None
    return None


def _today_trade_stats() -> dict:
    """Counts trades placed by THIS bot today (filter by MAGIC), and the
    trailing run of losses since the last win. Reads MT5 deal history; in
    paper mode also folds in paper_trades.jsonl. Used by guards to enforce
    MAX_TRADES_PER_DAY + MAX_CONSECUTIVE_LOSSES."""
    # Broker timezone gotcha — see lib/sync.py for the explanation.
    from datetime import timedelta as _td
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) - _td(days=1)
    history_end = now_utc + _td(hours=24)

    # MT5 closed deals (today, this bot's magic) → list of (closed_at, profit)
    closes = []
    if MODE != "paper":
        try:
            deals = mt5.history_deals_get(today_start, history_end) or []
            for d in deals:
                if int(getattr(d, "magic", 0)) != int(MAGIC):
                    continue
                if d.entry != mt5.DEAL_ENTRY_OUT:
                    continue
                closes.append((float(d.time), float(d.profit or 0.0)))
        except Exception:  # noqa: BLE001
            pass

    # Paper trades closed today
    if MODE == "paper":
        import json as _json
        from pathlib import Path as _Path
        f = _Path(__file__).parent / "paper_trades.jsonl"
        if f.exists():
            today_iso = today_start.date().isoformat()
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        t = _json.loads(line)
                    except _json.JSONDecodeError:
                        continue
                    if (t.get("closed_at") or "").startswith(today_iso):
                        # use a synthetic timestamp so ordering works
                        closes.append((t.get("closed_at"), float(t.get("pnl_usd", 0.0))))
            except OSError:
                pass

    # Order chronologically
    try:
        closes.sort(key=lambda x: x[0])
    except TypeError:
        pass

    # Consecutive losing streak (from the end backwards until a win/be appears)
    streak = 0
    for _ts, pnl in reversed(closes):
        if pnl < 0:
            streak += 1
        else:
            break

    # Number of trades opened today: count IN deals with this magic, OR len(closes)+open positions as a proxy.
    trades_today = 0
    if MODE != "paper":
        try:
            deals = mt5.history_deals_get(today_start, history_end) or []
            trades_today = sum(
                1 for d in deals
                if int(getattr(d, "magic", 0)) == int(MAGIC) and d.entry == mt5.DEAL_ENTRY_IN
            )
            # plus still-open positions opened today
            positions = mt5.positions_get(magic=int(MAGIC)) or []
            for p in positions:
                if datetime.fromtimestamp(p.time, timezone.utc) >= today_start:
                    trades_today += 1
        except Exception:  # noqa: BLE001
            pass
    else:
        trades_today = len(closes)  # paper: every closed paper trade is one trade

    return {"trades_today": trades_today, "consecutive_losses_today": streak}


def _account_state() -> dict:
    """Account + day P&L. Includes paper trades closed today so the daily-
    DD guard works even when TRADING_MODE=paper (where MT5 balance is
    static)."""
    info = mt5.account_info()
    if info is None:
        return {"balance": 0.0, "equity": 0.0, "daily_pl_usd": 0.0, "daily_pl_pct": 0.0}
    # Broker timezone offset: see lib/sync.py — bump `end` 24h forward and
    # reach back 1 day in `start` so we capture today regardless of broker
    # server tz (XM = UTC+3, others vary).
    from datetime import timedelta as _td
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0) - _td(days=1)
    deals = mt5.history_deals_get(today_start, now_utc + _td(hours=24)) or []
    # Realised P&L "today" — since broker timestamps are in server TZ but
    # exposed as UTC, "deals from the last 24h sliding window" is a robust
    # proxy for "today's P&L" regardless of broker offset. The strict
    # broker-day boundary is unknowable without `terminal_info().timezone`
    # which not all brokers expose.
    cutoff_24h = (now_utc - _td(hours=24)).timestamp() - 24 * 3600  # tz buffer
    realised = sum(
        float(d.profit or 0.0)
        for d in deals
        if d.entry == mt5.DEAL_ENTRY_OUT and float(d.time) >= cutoff_24h
    )
    unrealised = float(info.profit or 0.0)
    paper_today = _paper_pnl_today() if MODE == "paper" else 0.0
    daily_pl = realised + unrealised + paper_today
    daily_pl_pct = (daily_pl / info.balance * 100.0) if info.balance else 0.0
    return {
        "login": info.login,
        "server": info.server,
        "currency": info.currency,
        "leverage": info.leverage,
        "balance": float(info.balance),
        "equity": float(info.equity),
        "margin": float(info.margin),
        "margin_free": float(info.margin_free),
        "margin_level": float(info.margin_level) if info.margin else 0.0,
        "profit": unrealised,
        "daily_pl_usd": round(daily_pl, 2),
        "daily_pl_pct": round(daily_pl_pct, 3),
        "trade_allowed": bool(info.trade_allowed),
    }


def _open_positions() -> list:
    positions = mt5.positions_get() or []
    out = []
    for p in positions:
        out.append({
            "ticket": int(p.ticket),
            "symbol": p.symbol,
            "side": "buy" if p.type == 0 else "sell",
            "lots": float(p.volume),
            "entry": float(p.price_open),
            "current": float(p.price_current),
            "sl": float(p.sl),
            "tp": float(p.tp),
            "profit_usd": float(p.profit),
            "open_time_utc": datetime.fromtimestamp(p.time, tz=timezone.utc).isoformat(),
            "magic": int(p.magic),
            "comment": p.comment or "",
        })
    return out


# --------------------------- tools ---------------------------

@mcp.tool()
def health() -> dict:
    """Server status + connection state."""
    conn = connection.ensure()
    return {
        "version": __version__,
        "mode": MODE,
        "magic": MAGIC,
        "halted": halt_mod.is_halted(),
        "halt_reason": halt_mod.reason() if halt_mod.is_halted() else None,
        **conn,
    }


@mcp.tool()
def initialize_mt5() -> dict:
    """Force a (re)connect; usually unnecessary — every tool calls ensure()."""
    return connection.ensure()


@mcp.tool()
def get_account_info() -> dict:
    connection.ensure()
    return _account_state()


@mcp.tool()
def get_open_positions() -> dict:
    connection.ensure()
    return {"positions": _open_positions()}


@mcp.tool()
def get_rates(symbol: str, timeframe: str = "M15", n: int = 200) -> dict:
    """OHLCV bars. timeframe ∈ {M1,M5,M15,M30,H1,H4,D1}. Max n = 5000."""
    connection.ensure()
    tf = TIMEFRAMES.get(timeframe.upper())
    if tf is None:
        return _reject("BAD_TIMEFRAME", f"timeframe {timeframe} not in {list(TIMEFRAMES)}")
    n = max(1, min(int(n), 5000))
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    if rates is None or len(rates) == 0:
        err = mt5.last_error()
        return _reject("NO_DATA", f"{symbol}/{timeframe}: {err}")
    bars = []
    for r in rates:
        bars.append({
            "time":   datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).isoformat(),
            "open":   float(r["open"]),
            "high":   float(r["high"]),
            "low":    float(r["low"]),
            "close":  float(r["close"]),
            "volume": int(r["tick_volume"]),
        })
    return {"symbol": symbol, "timeframe": timeframe.upper(), "bars": bars}


@mcp.tool()
def get_tick(symbol: str) -> dict:
    connection.ensure()
    t = mt5.symbol_info_tick(symbol)
    if t is None:
        return _reject("NO_TICK", f"no tick for {symbol}")
    info = mt5.symbol_info(symbol)
    spread_pts = info.spread if info else None
    return {
        "symbol": symbol,
        "bid": float(t.bid),
        "ask": float(t.ask),
        "last": float(t.last),
        "spread_points": spread_pts,
        "time_utc": datetime.fromtimestamp(t.time, tz=timezone.utc).isoformat(),
    }


@mcp.tool()
def get_trade_history(days: int = 7) -> dict:
    """Closed deals over the last N days."""
    connection.ensure()
    end = datetime.now(timezone.utc)
    start = datetime.fromtimestamp(end.timestamp() - max(1, days) * 86_400, tz=timezone.utc)
    deals = mt5.history_deals_get(start, end) or []
    out = []
    for d in deals:
        out.append({
            "ticket": int(d.ticket),
            "position_id": int(d.position_id),
            "symbol": d.symbol,
            "side": "buy" if d.type == 0 else "sell",
            "volume": float(d.volume),
            "price": float(d.price),
            "profit": float(d.profit),
            "comment": d.comment or "",
            "time_utc": datetime.fromtimestamp(d.time, tz=timezone.utc).isoformat(),
            "entry": "in" if d.entry == mt5.DEAL_ENTRY_IN else "out" if d.entry == mt5.DEAL_ENTRY_OUT else "other",
        })
    return {"deals": out, "from": start.isoformat(), "to": end.isoformat()}


@mcp.tool()
def calculate_lot_size(symbol: str, sl_pips: float, risk_pct: float = 1.0) -> dict:
    """Suggested lot size for a given SL distance (in pips) and % risk."""
    connection.ensure()
    info = mt5.symbol_info(symbol)
    if info is None:
        return _reject("NO_SYMBOL", f"{symbol} not in MarketWatch")
    acc = mt5.account_info()
    if acc is None:
        return _reject("NO_ACCOUNT", "account info unavailable")
    point = info.point or 0.00001
    pip_size = point * 10  # 1 pip = 10 points on 5-digit FX
    sl_distance = sl_pips * pip_size
    sl_ticks = sl_distance / info.trade_tick_size
    dollars_per_lot = sl_ticks * info.trade_tick_value
    if dollars_per_lot <= 0:
        return _reject("BAD_TICK_VALUE", f"trade_tick_value={info.trade_tick_value}")
    budget = float(acc.balance) * (risk_pct / 100.0)
    raw_lots = budget / dollars_per_lot
    step = info.volume_step or 0.01
    snapped = round(round(raw_lots / step) * step, 4)
    snapped = max(snapped, info.volume_min or 0.01)
    return {
        "symbol": symbol,
        "lots": snapped,
        "raw_lots": round(raw_lots, 4),
        "risk_dollars": round(budget, 2),
        "sl_distance": round(sl_distance, 5),
        "dollars_per_lot": round(dollars_per_lot, 2),
        "volume_step": step,
    }


@mcp.tool()
def place_order(
    symbol: str,
    side: str,
    lots: float,
    sl: float,
    tp: float,
    comment: str = "claude",
    client_order_id: Optional[str] = None,
) -> dict:
    """The ONLY tool that affects the account.

    Order of checks:
      0. kill-switch (~/mcp/.HALT)
      0.5 idempotency replay (60s)
      1..8 — see ``lib/guards.py``
      9. mode switch — paper logs synthetic ticket; demo/live calls mt5.order_send
    """
    coid = client_order_id or f"auto-{uuid.uuid4().hex[:12]}"
    # MT5 truncates the order comment to 31 chars; if a coid exceeds that
    # the broker would silently store a non-unique tag, breaking the
    # comment-based reconciliation in `_reconcile_pending`. Hash long ones
    # to a deterministic 30-char marker (`c-` + 28 hex of sha1) so the
    # original coid → broker comment mapping is still 1-to-1 within an
    # idempotency window.
    if len(coid) > 30:
        import hashlib as _hl
        coid_for_broker = "c-" + _hl.sha1(coid.encode("utf-8")).hexdigest()[:28]
    else:
        coid_for_broker = coid

    # 0. Kill-switch — first, no exceptions.
    if halt_mod.is_halted():
        result = _reject("HALTED", halt_mod.reason() or "kill-switch active")
        logger.log_order({"client_order_id": coid, "tool": "place_order",
                          "input": {"symbol": symbol, "side": side, "lots": lots},
                          "result": result, "mode": MODE})
        # Cache the HALTED result in the idempotency window — same coid
        # arriving again during the halt must replay this rejection, never
        # re-evaluate guards (the halt could be lifted mid-retry and the
        # un-cached path would race straight to order_send).
        return idempotency.remember(coid, result)

    # NOTE: from this point until return we hold the cross-process lock so
    # two concurrent MCP clients cannot both pass the MAX_POSITIONS check
    # and both submit (TOCTOU on the "open positions" count). The lock
    # auto-releases on every return path, including exceptions.
    with _PlaceOrderLock():
        # 0.5 Idempotency replay (and PENDING reconciliation)
        cached = idempotency.check(coid)
        if cached is not None:
            if idempotency.is_pending(cached):
                reconciled = _reconcile_pending(coid)
                if reconciled is not None:
                    return idempotency.remember(coid, {**reconciled,
                                                        "idempotent_replay": True,
                                                        "recovered": True})
                # Nothing found → safe to fall through (re-submit). The fresh
                # remember() below overwrites the PENDING marker.
            else:
                return {**cached, "idempotent_replay": True}

        side = side.lower()
        if side not in ("buy", "sell"):
            return idempotency.remember(coid, _reject("BAD_SIDE", "side must be buy|sell"))

        connection.ensure()

        # Build the context dict the guards consume.
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return idempotency.remember(coid, _reject("NO_TICK", f"no tick for {symbol}"))
        entry = float(tick.ask if side == "buy" else tick.bid)

        info = mt5.symbol_info(symbol)
        sl_dist = abs(entry - sl) if sl else 0.0
        risk_usd = 0.0
        if info and info.trade_tick_size:
            risk_usd = lots * (sl_dist / info.trade_tick_size) * info.trade_tick_value

        acc = _account_state()
        positions = _open_positions()
        # In demo/live mode MT5 IS the source of truth for open positions; never
        # mix in paper_open.json (which can carry stale entries from a prior
        # paper run and would phantom-block real trading). Only count paper
        # entries when the MCP itself is in paper mode.
        paper_open = _paper_open_positions() if MODE == "paper" else []
        open_symbols = [p["symbol"] for p in positions] + [p["symbol"] for p in paper_open]
        today_stats = _today_trade_stats()
        ctx = {
            "symbol": symbol, "side": side, "lots": lots,
            "entry": entry, "sl": sl, "tp": tp,
            "utc_hour": _utc_hour(),
            "utc_minute": _utc_minute(),
            "open_positions_count": len(positions) + len(paper_open),
            "open_symbols": open_symbols,
            "daily_pl_pct": acc["daily_pl_pct"],
            "balance": acc["balance"],
            "risk_usd": risk_usd,
            "trades_today": today_stats["trades_today"],
            "consecutive_losses_today": today_stats["consecutive_losses_today"],
        }

        rejection = guards.run_guards(ctx)
        if rejection is not None:
            result = _reject(rejection["reason"], rejection["detail"])
            logger.log_order({"client_order_id": coid, "tool": "place_order",
                              "input": ctx, "result": result, "mode": MODE})
            return idempotency.remember(coid, result)

        # PAPER mode — never call order_send
        if MODE == "paper":
            ticket = int(time.time() * 1000)
            result = {"ok": True, "ticket": ticket, "filled_at": entry,
                      "mode": "paper", "client_order_id": coid}
            logger.log_paper({"client_order_id": coid, "symbol": symbol,
                              "side": side, "lots": lots, "sl": sl, "tp": tp,
                              "ticket": ticket, "entry": entry, "magic": MAGIC,
                              "risk_usd": round(risk_usd, 2)})
            return idempotency.remember(coid, result)

        # DEMO / LIVE — pre-flight PENDING marker BEFORE order_send so a crash
        # between this point and the post-write doesn't lose track of the coid.
        idempotency.mark_pending(coid)

        request = {
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       float(lots),
            "type":         mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
            "price":        entry,
            "sl":           float(sl),
            "tp":           float(tp),
            "deviation":    20,
            "magic":        MAGIC,
            "comment":      coid_for_broker,
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time":    mt5.ORDER_TIME_GTC,
        }
        res = mt5.order_send(request)
        logger.log_order({"client_order_id": coid, "tool": "place_order",
                          "input": ctx, "request": request,
                          "retcode": res.retcode if res else None,
                          "comment": res.comment if res else None,
                          "mode": MODE})
        if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
            detail = f"retcode={getattr(res, 'retcode', 'n/a')}: {getattr(res, 'comment', 'n/a')}"
            return idempotency.remember(coid, _reject("MT5_REJECTED", detail))
        return idempotency.remember(coid, {
            "ok": True,
            "ticket": int(res.order),
            "filled_at": float(res.price),
            "mode": MODE,
            "client_order_id": coid,
        })


@mcp.tool()
def close_position(ticket: int) -> dict:
    """Close a position by ticket. No guards — closing must always be possible."""
    connection.ensure()
    positions = mt5.positions_get(ticket=int(ticket)) or []
    if not positions:
        return _reject("NO_POSITION", f"ticket {ticket} not found")
    p = positions[0]
    tick = mt5.symbol_info_tick(p.symbol)
    if tick is None:
        return _reject("NO_TICK", f"no tick for {p.symbol}")
    request = {
        "action":       mt5.TRADE_ACTION_DEAL,
        "symbol":       p.symbol,
        "volume":       float(p.volume),
        "position":     int(p.ticket),
        "type":         mt5.ORDER_TYPE_SELL if p.type == 0 else mt5.ORDER_TYPE_BUY,
        "price":        float(tick.bid if p.type == 0 else tick.ask),
        "deviation":    20,
        "magic":        int(p.magic),
        "comment":      "claude-close",
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    if MODE == "paper":
        return {"ok": True, "mode": "paper", "ticket": int(p.ticket), "synthetic": True}
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        return _reject("MT5_REJECTED", f"close failed: retcode={getattr(res, 'retcode', 'n/a')}")
    return {"ok": True, "mode": MODE, "ticket": int(p.ticket), "closed_at": float(res.price)}


@mcp.tool()
def modify_sl_tp(ticket: int, sl: Optional[float] = None, tp: Optional[float] = None) -> dict:
    """Move SL/TP. SL can only move *toward* entry, never away."""
    connection.ensure()
    positions = mt5.positions_get(ticket=int(ticket)) or []
    if not positions:
        return _reject("NO_POSITION", f"ticket {ticket} not found")
    p = positions[0]
    if sl is not None:
        if p.type == 0 and sl < p.sl and p.sl > 0:
            return _reject("SL_AGAINST", "no alejar SL para buy")
        if p.type == 1 and sl > p.sl and p.sl > 0:
            return _reject("SL_AGAINST", "no alejar SL para sell")
    if MODE == "paper":
        return {"ok": True, "mode": "paper", "ticket": int(p.ticket),
                "sl": sl if sl is not None else float(p.sl),
                "tp": tp if tp is not None else float(p.tp)}
    request = {
        "action":   mt5.TRADE_ACTION_SLTP,
        "position": int(p.ticket),
        "symbol":   p.symbol,
        "sl":       float(sl) if sl is not None else float(p.sl),
        "tp":       float(tp) if tp is not None else float(p.tp),
    }
    res = mt5.order_send(request)
    if res is None or res.retcode != mt5.TRADE_RETCODE_DONE:
        return _reject("MT5_REJECTED", f"modify failed: retcode={getattr(res, 'retcode', 'n/a')}")
    return {"ok": True, "mode": MODE, "ticket": int(p.ticket)}


@mcp.tool()
def sync_to_dashboard(lookback_days: int = 1) -> dict:
    """Push closed deals from MT5 history to the dashboard journal."""
    connection.ensure()
    return sync.push_recent_deals(mt5, lookback_days=lookback_days)




# ============================================================================
# Capa 4 (legacy ports)
# ============================================================================


@mcp.tool()
def validate_sl_tp(
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    bid: float | None = None,
    ask: float | None = None,
) -> dict:
    """Validate SL/TP against side and (optional) latest quote.

    BUY: stop_loss < entry < take_profit. SELL: take_profit < entry < stop_loss.
    Entry resolves to ask for BUY (when present), bid for SELL.
    """
    return _validate_sl_tp(
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        bid=bid,
        ask=ask,
    ).to_dict()


@mcp.tool()
def calc_trailing_stop(
    side: str,
    entry_price: float,
    current_price: float,
    current_stop_loss: float,
    trigger_distance: float,
    trail_distance: float,
    min_step: float = 0.0,
) -> dict:
    """Propose a deterministic trailing-stop adjustment.

    Returns: {ok, should_update, new_stop_loss, reason_code}.
    Caller is responsible for actually applying the change via modify_sl_tp.
    """
    return _eval_trailing(
        side=side,
        entry_price=entry_price,
        current_price=current_price,
        current_stop_loss=current_stop_loss,
        trigger_distance=trigger_distance,
        trail_distance=trail_distance,
        min_step=min_step,
    ).to_dict()


@mcp.tool()
def assess_data_quality(
    symbol: str,
    timeframe: str,
    bars: list[dict],
    stale_after_seconds: int = 30,
    max_spread_points: float | None = None,
    allow_zero_volume: bool = False,
) -> dict:
    """Validate OHLCV bars: gaps, duplicates, stale state, spread/volume anomalies.

    Returns a quality report: {ok, has_errors, has_warnings, flags: [...]}.
    """
    thresholds = QualityThresholds(
        stale_after_seconds=stale_after_seconds,
        max_spread_points=max_spread_points,
        allow_zero_volume=allow_zero_volume,
    )
    return _check_bar_series(symbol, timeframe, bars, thresholds=thresholds)


@mcp.tool()
def assess_quote_quality(
    quote: dict,
    stale_after_seconds: int = 30,
    max_spread_points: float | None = None,
) -> dict:
    """Validate one tick/quote: freshness, spread, bid/ask sanity.

    `quote` needs: symbol, timestamp, bid, ask. Optional: spread.
    """
    thresholds = QualityThresholds(
        stale_after_seconds=stale_after_seconds,
        max_spread_points=max_spread_points,
    )
    return _check_quote(quote, thresholds=thresholds)


@mcp.tool()
def reconcile_positions(
    mt5_positions: list[dict] | None = None,
    journal_positions: list[dict] | None = None,
) -> dict:
    """Compare current MT5 open positions vs. backend journal positions.

    If `mt5_positions` is None, fetches via `get_open_positions()`. The
    `journal_positions` argument is REQUIRED (the dashboard backend has the
    journal source of truth — caller passes that view in).

    Returns the diff: matched, missing_in_journal, missing_in_mt5, mismatched.
    """
    if journal_positions is None:
        return {
            "ok": False,
            "reason": "JOURNAL_REQUIRED",
            "detail": "journal_positions must be provided by the caller (dashboard view).",
        }

    if mt5_positions is None:
        connection.ensure()
        mt5_positions = _open_positions()

    diff = _reconcile_positions(
        mt5_positions=mt5_positions,
        journal_positions=journal_positions,
    )
    return diff.to_dict()


# --------------------------- entrypoint ---------------------------

if __name__ == "__main__":
    log.info("trading-mt5-mcp v%s starting (mode=%s, magic=%s)", __version__, MODE, MAGIC)
    mcp.run()
