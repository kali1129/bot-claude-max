"""Backfill the research log with the 8 historical trades that closed before
the per-trade research code was deployed.

For each closed trade in the journal we look up its MT5 deals (IN+OUT) and
write a synthetic ``open`` + ``close`` pair to ``trade_research.jsonl``.
We do NOT have the scoring breakdown for these (the bot didn't record it
at the time), so the breakdown is empty — but we DO have entry/exit/SL/TP,
pnl, r_multiple, duration, exit_reason, and side. Enough to do post-mortem
on outcomes even without the per-component score.

Idempotent: skips tickets already in the research log.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import urllib.request

HERE = Path(__file__).resolve().parent
MCP = HERE.parent / "mcp-scaffolds" / "trading-mt5-mcp"
sys.path.insert(0, str(MCP))
from dotenv import load_dotenv
load_dotenv(MCP / ".env")

import MetaTrader5 as mt5  # noqa: E402

LOG_DIR = Path(os.path.expanduser(os.environ.get("LOG_DIR", "~/mcp/logs")))
RESEARCH_LOG = LOG_DIR / "trade_research.jsonl"


def existing_tickets() -> set:
    """Return set of tickets already in the research log."""
    if not RESEARCH_LOG.exists():
        return set()
    out = set()
    for line in RESEARCH_LOG.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            t = r.get("ticket")
            if t is not None:
                out.add(int(t))
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    if not mt5.initialize():
        print(f"mt5 init failed: {mt5.last_error()}", file=sys.stderr)
        return 1

    seen = existing_tickets()
    print(f"existing research records: {len(seen)} tickets")

    # Pull last 7 days of deals
    end = datetime.now(timezone.utc) + timedelta(hours=24)
    start = end - timedelta(days=7) - timedelta(hours=24)
    deals = mt5.history_deals_get(start, end) or []
    print(f"loaded {len(deals)} deals from MT5 history")

    # Group by position_id → IN + OUT
    by_pos: dict[int, dict] = {}
    for d in deals:
        pos = int(getattr(d, "position_id", 0) or 0)
        if pos == 0:
            continue
        by_pos.setdefault(pos, {})
        if d.entry == mt5.DEAL_ENTRY_IN:
            by_pos[pos]["in"] = d
        elif d.entry == mt5.DEAL_ENTRY_OUT:
            by_pos[pos]["out"] = d

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped = 0
    no_pair = 0

    with open(RESEARCH_LOG, "a", encoding="utf-8") as f:
        for pos_id, pair in by_pos.items():
            if pos_id in seen:
                skipped += 1
                continue
            in_d = pair.get("in")
            out_d = pair.get("out")
            if not in_d or not out_d:
                no_pair += 1
                continue

            side = "buy" if int(in_d.type) == 0 else "sell"
            entry = float(in_d.price)
            exit_price = float(out_d.price)
            pnl = float(out_d.profit or 0.0)
            lots = float(out_d.volume)
            symbol = out_d.symbol or in_d.symbol

            # SL/TP from the IN deal or the order
            sl_val = float(in_d.sl) if getattr(in_d, "sl", 0) else None
            tp_val = float(in_d.tp) if getattr(in_d, "tp", 0) else None
            if sl_val is None or tp_val is None:
                try:
                    orders = mt5.history_orders_get(ticket=int(in_d.order)) or []
                    for o in orders:
                        if sl_val is None and getattr(o, "sl", 0):
                            sl_val = float(o.sl)
                        if tp_val is None and getattr(o, "tp", 0):
                            tp_val = float(o.tp)
                        if sl_val is not None and tp_val is not None:
                            break
                except Exception:  # noqa: BLE001
                    pass

            sl_dist = abs(entry - sl_val) if (sl_val and entry) else 0.0
            try:
                info = mt5.symbol_info(symbol)
                tick_size = float(info.trade_tick_size or info.point or 1e-5) if info else 1e-5
                tick_value = float(info.trade_tick_value or 1.0) if info else 1.0
                risk_usd = (sl_dist / tick_size) * tick_value * lots if (sl_dist > 0 and tick_size > 0) else 0.0
            except Exception:  # noqa: BLE001
                risk_usd = 0.0
            r_mult = round(pnl / risk_usd, 2) if risk_usd > 0 else 0.0

            # Heuristic exit_reason
            if pnl > 0 and tp_val:
                near_tp = abs(exit_price - tp_val) <= max(0.0010 * tp_val, 0.0001)
                reason = "TP_HIT" if near_tp else "EARLY_TAKE"
            elif pnl <= 0 and sl_val:
                near_sl = abs(exit_price - sl_val) <= max(0.0010 * sl_val, 0.0001)
                reason = "SL_HIT" if near_sl else "MANUAL_OR_EARLY"
            else:
                reason = "UNKNOWN"

            in_ts = datetime.fromtimestamp(in_d.time, timezone.utc)
            out_ts = datetime.fromtimestamp(out_d.time, timezone.utc)
            duration_s = max(0, int((out_ts - in_ts).total_seconds()))

            # Write open record (no scoring breakdown — bot didn't have research wired then)
            open_rec = {
                "ts": in_ts.isoformat(),
                "event": "open",
                "ticket": int(pos_id),
                "symbol": symbol,
                "side": side,
                "entry": entry,
                "sl": sl_val,
                "tp": tp_val,
                "lots": lots,
                "atr": None,
                "score": None,
                "rec": None,
                "breakdown": {},
                "risk_usd": round(risk_usd, 2),
                "context": {
                    "balance_at_entry": None,
                    "trades_today_before": None,
                    "consecutive_losses_today": None,
                    "open_positions_before": None,
                    "utc_hour": in_ts.hour,
                    "utc_minute": in_ts.minute,
                },
                "config": {
                    "min_score": None,
                    "interval_s": None,
                    "risk_pct": None,
                    "watchlist_size": None,
                },
                "backfilled": True,
            }
            close_rec = {
                "ts": out_ts.isoformat(),
                "event": "close",
                "ticket": int(pos_id),
                "symbol": symbol,
                "side": side,
                "entry": entry,
                "exit": exit_price,
                "exit_reason": reason,
                "pnl_usd": round(pnl, 2),
                "r_multiple": r_mult,
                "duration_seconds": duration_s,
                "mfe_r": None,
                "mae_r": None,
                "max_favorable_price": None,
                "max_adverse_price": None,
                "be_moved": False,
                "trail_count": 0,
                "original_sl": sl_val,
                "original_tp": tp_val,
                "backfilled": True,
            }
            f.write(json.dumps(open_rec, default=str) + "\n")
            f.write(json.dumps(close_rec, default=str) + "\n")
            written += 1

    print(f"backfilled: {written} new   skipped (already in log): {skipped}   incomplete pairs: {no_pair}")
    mt5.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
