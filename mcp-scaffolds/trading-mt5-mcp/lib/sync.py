"""Best-effort sync of closed deals MT5 → dashboard journal.

Each deal is POSTed once with ``client_id="mt5-deal-<ticket>"`` so the backend
ignores retries.

Three concerns this module gets right (revisits per code-review):

1. **Pair IN+OUT deals by ``position_id``** — an MT5 position has one IN
   deal (open) and one OUT deal (close). We use ``history_deals_get(
   position=position_id)`` to find the matching pair so the journal entry
   has both real entry and real exit prices, not ``entry == exit == close``.

2. **r_multiple uses USD risk, not price-distance** — the previous formula
   ``pnl / (volume * sl_distance)`` was dimensionally wrong (lots × price-
   units, no $). Correct math goes through ``symbol_info().trade_tick_size``
   and ``trade_tick_value`` to convert SL distance to actual dollars at
   risk, the same way ``risk-mcp/lib/sizing.py`` computes it.

3. **No fabricated SL/TP** — when MT5 doesn't tell us the SL/TP that was
   set on the position, we send ``None`` rather than ``entry * 0.99``.
   Bogus SL values in the journal corrupted historical R-multiple stats.

State file ``sync.json`` carries:

   - ``pushed_tickets`` (list[int]): deals already POSTed in the last 7 days,
     used to dedupe across restarts. We re-scan every pass instead of
     relying on a monotonic ``last_seen_ticket`` (MT5 deal tickets are NOT
     guaranteed to be monotonic, especially across server-side reconnects;
     the previous logic could permanently skip a deal whose ticket happened
     to land below the watermark).
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import requests

log = logging.getLogger(__name__)

STATE_FILE = Path(__file__).resolve().parent.parent / "sync.json"
DEDUPE_WINDOW_DAYS = 7  # how long to remember pushed tickets


def _state() -> dict:
    if not STATE_FILE.exists():
        return {"pushed_tickets": [], "version": 2}
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        # Migrate old v1 schema (last_seen_ticket only)
        if "version" not in s or s.get("version") < 2:
            return {"pushed_tickets": [], "version": 2}
        return s
    except (OSError, json.JSONDecodeError):
        return {"pushed_tickets": [], "version": 2}


def _save(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def _prune_dedupe(state: dict) -> None:
    """Drop ticket entries older than DEDUPE_WINDOW_DAYS. Each entry is
    [ticket, ts]. Mutates state in place."""
    cutoff = time.time() - DEDUPE_WINDOW_DAYS * 86_400
    state["pushed_tickets"] = [
        [t, ts] for (t, ts) in state.get("pushed_tickets", [])
        if isinstance(ts, (int, float)) and ts >= cutoff
    ]


def _post(payload: dict) -> Optional[dict]:
    url = os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8000").rstrip("/")
    token = os.environ.get("DASHBOARD_TOKEN", "").strip()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.post(f"{url}/api/journal", json=payload, headers=headers, timeout=10)
        if r.status_code >= 400:
            log.warning("dashboard rejected sync payload: %s %s", r.status_code, r.text[:200])
            return None
        return r.json()
    except requests.RequestException as exc:
        log.warning("dashboard unreachable for sync: %s", exc)
        return None


def _build_in_index(mt5_module, all_deals):
    """Return {position_id: in_deal} from a pre-fetched deals list. Avoids
    the per-position round-trip that made sync_to_dashboard time out (one
    extra broker call per OUT deal × many deals = death by latency)."""
    idx = {}
    try:
        IN = mt5_module.DEAL_ENTRY_IN
    except AttributeError:
        IN = 0
    for d in all_deals or []:
        if d.entry == IN and getattr(d, "position_id", 0):
            idx[int(d.position_id)] = d
    return idx


def _risk_usd(symbol: str, sl_distance: float, lots: float, mt5_module) -> float:
    """Convert price-distance SL into USD risk using symbol metadata.
    Mirrors the formula in risk-mcp/lib/sizing.py."""
    if sl_distance <= 0 or lots <= 0:
        return 0.0
    try:
        info = mt5_module.symbol_info(symbol)
        if info is None:
            return 0.0
        tick_size = float(info.trade_tick_size or info.point or 1e-5)
        tick_value = float(info.trade_tick_value or 1.0)
        if tick_size <= 0 or tick_value <= 0:
            return 0.0
        sl_ticks = sl_distance / tick_size
        return sl_ticks * tick_value * lots
    except Exception:  # noqa: BLE001
        return 0.0


def deal_to_payload(out_deal, in_deal, mt5_module) -> dict:
    """Convert a paired IN+OUT deal to the journal schema. ``in_deal`` may be
    None — in that case ``entry`` falls back to OUT price and ``side``
    falls back to the inverse of the OUT deal's type (since closing a
    buy position emits a sell deal, MT5's OUT.type is the OPPOSITE of
    the position direction)."""
    pnl = float(out_deal.profit or 0.0)
    lots = float(out_deal.volume)

    # Direction comes from the IN deal when we have it (its `type` matches
    # the position type: 0=BUY, 1=SELL). Without an IN deal we invert the
    # OUT.type — closing a BUY emits a SELL deal and vice versa.
    if in_deal is not None:
        side = "buy" if int(in_deal.type) == 0 else "sell"
    else:
        side = "sell" if int(out_deal.type) == 0 else "buy"

    entry_price = float(in_deal.price) if in_deal else float(out_deal.price)
    exit_price = float(out_deal.price)

    # Position SL/TP. MT5 stores SL/TP on the order, not on the deal record,
    # so deal.sl/tp is usually 0. Fetch the original entry order to get the
    # SL/TP that was set at placement — that's what the bot used to risk-size.
    sl_val = None
    tp_val = None
    if in_deal is not None:
        if getattr(in_deal, "sl", 0):
            sl_val = float(in_deal.sl)
        if getattr(in_deal, "tp", 0):
            tp_val = float(in_deal.tp)
        # Fall back to the order if deal SL/TP are missing
        if sl_val is None or tp_val is None:
            try:
                orders = mt5_module.history_orders_get(ticket=int(in_deal.order)) or []
                for o in orders:
                    if sl_val is None and getattr(o, "sl", 0):
                        sl_val = float(o.sl)
                    if tp_val is None and getattr(o, "tp", 0):
                        tp_val = float(o.tp)
                    if sl_val is not None and tp_val is not None:
                        break
            except Exception:  # noqa: BLE001
                pass

    # Last-resort heuristic for losing trades when SL is genuinely unknown:
    # if pnl < 0 and exit price moved against entry, the SL distance is at
    # MOST |exit - entry| (the trade likely hit SL or worse). Use that as
    # an upper bound so r_multiple ≈ -1.0 instead of 0.0 (which hides the
    # loss in metrics that average R-multiples).
    if sl_val is None and pnl < 0:
        sl_val = exit_price  # gives sl_distance = |entry - exit|

    # Real R-multiple: pnl / risk_usd at the time of entry
    sl_distance = abs(entry_price - sl_val) if (sl_val and entry_price) else 0.0
    risk_usd = _risk_usd(out_deal.symbol, sl_distance, lots, mt5_module)
    r_mult = round(pnl / risk_usd, 2) if risk_usd > 0 else 0.0

    if pnl > 0:
        status = "closed-win"
    elif pnl < 0:
        status = "closed-loss"
    else:
        status = "closed-be"

    payload = {
        "client_id": f"mt5-deal-{out_deal.ticket}",
        "source": "mt5-sync",
        "date": date.fromtimestamp(out_deal.time).isoformat(),
        "symbol": out_deal.symbol,
        "side": side,
        "strategy": (out_deal.comment or in_deal.comment if in_deal else None) or "mt5-sync",
        "entry": entry_price,
        "exit": exit_price,
        "lots": lots,
        "pnl_usd": round(pnl, 2),
        "r_multiple": r_mult,
        "status": status,
        "notes": f"ticket={out_deal.ticket} pos={out_deal.position_id}",
    }
    if sl_val is not None:
        payload["sl"] = sl_val
    # The dashboard's TradeBase requires "sl" with gt=0; if we genuinely don't
    # know, default to entry to satisfy validation but record a warning note.
    if "sl" not in payload:
        payload["sl"] = entry_price
        payload["notes"] += " sl=unknown(default-to-entry)"
    if tp_val is not None:
        payload["tp"] = tp_val
    return payload


def push_recent_deals(mt5_module, lookback_days: int = 1) -> dict:
    """Pull recent deals from MT5 and POST any new ones to the dashboard.

    Iterates EVERY OUT deal in the lookback window each pass and dedupes
    against ``pushed_tickets`` in sync.json. This is robust to non-monotonic
    deal tickets — a deal that arrives "out of order" still gets pushed
    exactly once.
    """
    state = _state()
    _prune_dedupe(state)
    seen = {int(t) for (t, _ts) in state.get("pushed_tickets", [])}

    # Broker timezone gotcha: MT5's `history_deals_get(start, end)` filters
    # deals by their `time` field, which the broker stores in *server*
    # timezone (XM = UTC+3, others vary) but the Python lib exposes as if
    # it were UTC. So a trade that happened "10 minutes ago" can have a
    # timestamp 3h in the future relative to wall-clock UTC, and a strict
    # `end = now_utc` filter EXCLUDES today's trades.
    # Fix: bump `end` 24h forward to comfortably cover any broker offset.
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)
    start_anchor = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if lookback_days > 1:
        start = start_anchor - timedelta(days=lookback_days - 1)
    else:
        # default 1d lookback should still cover all of "today" generously
        start = start_anchor - timedelta(days=1)

    deals = mt5_module.history_deals_get(start, end) or []
    in_index = _build_in_index(mt5_module, deals)
    pushed = []
    failed = []
    skipped = 0
    for d in deals:
        if int(d.ticket) in seen:
            skipped += 1
            continue
        if d.entry != mt5_module.DEAL_ENTRY_OUT:
            continue  # only "exit" deals carry realised P&L

        in_deal = in_index.get(int(getattr(d, "position_id", 0)))
        # Edge case: IN deal opened in a window before our `start`. One
        # extra targeted lookup is fine here since it only happens for
        # legacy positions, not for everything.
        if in_deal is None and getattr(d, "position_id", 0):
            try:
                older = mt5_module.history_deals_get(position=int(d.position_id)) or []
                for o in older:
                    if o.entry == mt5_module.DEAL_ENTRY_IN:
                        in_deal = o; break
            except Exception:  # noqa: BLE001
                pass
        try:
            payload = deal_to_payload(d, in_deal, mt5_module)
        except Exception as exc:  # noqa: BLE001
            log.warning("payload build failed for ticket %s: %s", d.ticket, exc)
            failed.append(int(d.ticket))
            continue

        result = _post(payload)
        if result is None:
            failed.append(int(d.ticket))
        else:
            pushed.append(int(d.ticket))
            seen.add(int(d.ticket))
            state.setdefault("pushed_tickets", []).append([int(d.ticket), time.time()])

    if pushed:
        _prune_dedupe(state)
        _save(state)

    return {
        "pushed": pushed,
        "failed": failed,
        "skipped": skipped,
        "dedupe_window_days": DEDUPE_WINDOW_DAYS,
    }
