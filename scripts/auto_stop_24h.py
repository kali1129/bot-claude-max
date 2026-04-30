"""One-shot script: stop the bot, query stats, notify Telegram with a final summary.

Triggered by Windows Task Scheduler 24h after the test starts. Idempotent —
safe to run multiple times (stop is no-op if already stopped, Telegram message
just gets re-sent).

Run from anywhere with the backend's venv:
    backend/.venv/Scripts/python.exe scripts/auto_stop_24h.py
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import datetime, timezone

BACKEND = os.environ.get("BACKEND_URL", "http://127.0.0.1:8000") + "/api"


def _get(path: str, default=None):
    try:
        with urllib.request.urlopen(f"{BACKEND}{path}", timeout=10) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"GET {path} failed: {exc}", file=sys.stderr)
        return default


def _post(path: str, body=None):
    body = json.dumps(body or {}).encode("utf-8")
    req = urllib.request.Request(
        f"{BACKEND}{path}", data=body, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"POST {path} failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    print(f"[auto-stop-24h] firing at {datetime.now(timezone.utc).isoformat()}")

    # 1. Stop both processes
    s1 = _post("/process/auto_trader/stop")
    s2 = _post("/process/sync_loop/stop")
    print(f"  auto_trader stop -> {s1}")
    print(f"  sync_loop   stop -> {s2}")

    # 2. Pull final state
    mt5 = _get("/mt5/status", default={}) or {}
    journal_stats = _get("/journal/stats", default={}) or {}
    bot = _get("/bot/status", default={}) or {}

    acc = mt5.get("account") or {}
    today = mt5.get("today") or {}
    balance = acc.get("balance", "?")
    equity = acc.get("equity", "?")
    starting_balance = float(os.environ.get("STARTING_BALANCE", "200.0"))  # from env

    closed = journal_stats.get("total_trades") or bot.get("closed_count", 0)
    wins = journal_stats.get("wins") or bot.get("wins", 0)
    losses = journal_stats.get("losses") or bot.get("losses", 0)
    win_rate = journal_stats.get("win_rate", 0.0)
    total_pnl = journal_stats.get("total_pnl_usd")
    if total_pnl is None:
        try:
            total_pnl = float(equity) - starting_balance
        except Exception:  # noqa: BLE001
            total_pnl = 0.0
    pnl_pct = (total_pnl / starting_balance * 100.0) if starting_balance else 0.0

    # 3. Telegram message
    msg = (
        "*Test 24h FINALIZADO*\n\n"
        f"`balance:`   ${balance}\n"
        f"`equity:`    ${equity}\n"
        f"`PnL total:` ${total_pnl:+.2f} ({pnl_pct:+.2f}%)\n\n"
        f"`trades:` {closed}\n"
        f"`win/loss:` {wins}/{losses}\n"
        f"`winrate:` {win_rate:.1f}%\n\n"
        "Procesos detenidos. La posicion abierta (si la hay) sigue su curso "
        "en MT5 — cierralo desde el dashboard si quieres."
    )
    out = _post("/telegram/test", {"text": msg})
    print(f"  telegram -> {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
