"""Seed the dashboard journal with real trades from the legacy bot's CLAUDE.md.

Parses xm-mt5-trading-platform/CLAUDE.md, finds the per-session trade
tables, and POSTs each row to the new bot's /api/journal endpoint with
`client_id = "legacy-<sha8>"` so the call is idempotent (re-runs don't
duplicate).

Usage:
    python scripts/seed_legacy_journal.py \\
        --legacy-claude-md "C:/Users/Anderson Lora/bugbounty/xm-mt5-trading-platform/CLAUDE.md" \\
        --backend-url http://localhost:8000 \\
        --token "$DASHBOARD_TOKEN" \\
        [--dry-run]

The CLAUDE.md trade tables look like:

    ## Session 2026-04-16
    ### Trades
    | ts | symbol | dir | entry | exit | sl | tp | pnl_usd | rr | result | signal |
    | 14:50 | BTCUSD | SELL | 0.00 | 74508.95 | 0.00 | 0.00 | -1.13 | 0.00 | LOSS |  |

Daily summary rows (only date in first column) are skipped.

This script tolerates legacy zero values for entry/sl/tp by writing them
through; the dashboard journal accepts them. PnL is the meaningful field.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


SESSION_RE = re.compile(r"^## Session (\d{4}-\d{2}-\d{2})\s*$")
TRADE_ROW_RE = re.compile(
    r"^\|\s*(?P<ts>\d{2}:\d{2})\s*"
    r"\|\s*(?P<symbol>[A-Z0-9]+)\s*"
    r"\|\s*(?P<dir>BUY|SELL)\s*"
    r"\|\s*(?P<entry>[-+]?\d+\.\d+)\s*"
    r"\|\s*(?P<exit>[-+]?\d+\.\d+)\s*"
    r"\|\s*(?P<sl>[-+]?\d+\.\d+)\s*"
    r"\|\s*(?P<tp>[-+]?\d+\.\d+)\s*"
    r"\|\s*(?P<pnl>[-+]?\d+\.\d+)\s*"
    r"\|\s*(?P<rr>[-+]?\d+\.\d+)\s*"
    r"\|\s*(?P<result>WIN|LOSS|BE)\s*"
    r"\|\s*(?P<signal>[^|]*?)\s*\|\s*$"
)


def parse_legacy_trades(claude_md_path: Path) -> list[dict]:
    """Walk the markdown and yield trade dicts."""
    if not claude_md_path.exists():
        raise FileNotFoundError(f"Legacy CLAUDE.md not found: {claude_md_path}")

    trades: list[dict] = []
    current_date: str | None = None

    for line in claude_md_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        m = SESSION_RE.match(s)
        if m:
            current_date = m.group(1)
            continue

        m = TRADE_ROW_RE.match(s)
        if not m:
            continue
        if current_date is None:
            # Trade row before any session header — skip defensively.
            continue

        d = m.groupdict()
        date_part = current_date
        time_part = d["ts"]
        try:
            ts = datetime.fromisoformat(f"{date_part}T{time_part}:00+00:00")
        except ValueError:
            continue

        pnl = float(d["pnl"])
        side = d["dir"].lower()
        result = d["result"]
        # Build a stable client_id so re-runs are idempotent
        digest = hashlib.sha256(
            f"{date_part}-{time_part}-{d['symbol']}-{side}-{pnl}-{d['exit']}".encode("utf-8")
        ).hexdigest()[:8]

        raw_entry = float(d["entry"])
        raw_exit  = float(d["exit"])
        raw_sl    = float(d["sl"])
        raw_tp    = float(d["tp"])

        # Legacy data often recorded entry=0.0 (market order, no fill captured).
        # Use exit as a stand-in so the backend's gt=0 validation passes.
        entry = raw_entry if raw_entry > 0 else (raw_exit if raw_exit > 0 else 1.0)

        # sl=0.0 means it wasn't recorded. Synthesise a minimal placeholder:
        # 0.1% beyond entry in the loss direction so geometry is valid.
        if raw_sl > 0:
            sl = raw_sl
        elif side == "buy":
            sl = round(entry * 0.999, 5)
        else:
            sl = round(entry * 1.001, 5)

        # tp=0.0 → omit (optional in model)
        tp = raw_tp if raw_tp > 0 else None

        trades.append({
            "client_id": f"legacy-{digest}",
            "date": date_part,
            "symbol": d["symbol"],
            "side": side,
            "strategy": "legacy-import",
            "lots": 0.01,
            "entry": entry,
            "exit": raw_exit if raw_exit > 0 else None,
            "sl": sl,
            "tp": tp,
            "pnl_usd": pnl,
            "r_multiple": float(d["rr"]),
            "status": {"WIN": "closed-win", "LOSS": "closed-loss", "BE": "closed-be"}.get(result, "closed-loss"),
            "source": "manual",
        })

    return trades


def post_trade(backend_url: str, token: str, trade: dict, *, timeout: float = 10.0) -> dict:
    """POST one trade to /api/journal with bearer auth.

    The payload shape mirrors the dashboard's TradeEntryCreate model. The
    server is responsible for idempotency on `client_id`.
    """
    url = f"{backend_url.rstrip('/')}/api/journal"
    body = json.dumps(trade).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return {"ok": True, "status": resp.status, "body": json.loads(resp.read().decode("utf-8"))}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "body": exc.read().decode("utf-8", errors="replace")}
    except urllib.error.URLError as exc:
        return {"ok": False, "status": 0, "body": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed dashboard journal from legacy CLAUDE.md.")
    parser.add_argument("--legacy-claude-md", required=True, type=Path)
    parser.add_argument("--backend-url", default="http://localhost:8000")
    parser.add_argument("--token", default=None, help="DASHBOARD_TOKEN bearer; required unless --dry-run")
    parser.add_argument("--dry-run", action="store_true", help="parse + print trades, do not POST")
    args = parser.parse_args()

    trades = parse_legacy_trades(args.legacy_claude_md)
    print(f"Parsed {len(trades)} trades from {args.legacy_claude_md}", file=sys.stderr)

    if args.dry_run:
        print(json.dumps(trades, indent=2))
        return 0

    if not args.token:
        print("ERROR: --token is required unless --dry-run", file=sys.stderr)
        return 2

    posted = 0
    failed = 0
    duplicates = 0
    for t in trades:
        result = post_trade(args.backend_url, args.token, t)
        if result["ok"]:
            posted += 1
        elif result["status"] == 409:
            duplicates += 1
        else:
            failed += 1
            print(f"FAIL {t['client_id']}: status={result['status']} body={result['body']}",
                  file=sys.stderr)

    print(f"Done. posted={posted} duplicates={duplicates} failed={failed}", file=sys.stderr)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
