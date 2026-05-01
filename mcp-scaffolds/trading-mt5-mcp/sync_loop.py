"""Background sync poller: MT5 → dashboard journal.

Bug fix:
  El loop anterior llamaba ``server.sync_to_dashboard(args.lookback)`` —
  pero ``sync_to_dashboard`` está decorado como ``@mcp.tool()`` y solo
  funciona dentro del contexto MCP (stdio request). Cuando se importa
  directo desde un script standalone, FastMCP envuelve la función y la
  llamada falla silenciosamente cada 60s desde hace días. Resultado:
  el journal del dashboard nunca recibió entries ``mt5-sync``.

Fix: llamar directo a ``lib.sync.push_recent_deals(mt5, ...)`` que es la
función pura, no el tool MCP.

Mejoras adicionales:
  - Exponential backoff tras N fallos consecutivos (60s → 5m → 15m → 30m)
  - Telegram alert tras 5 fallos consecutivos
  - Log estructurado con métrica simple

Usage:
    .venv/Scripts/python sync_loop.py
    .venv/Scripts/python sync_loop.py --interval 30 --lookback 1
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import time
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "_shared"))
load_dotenv(HERE / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s sync-loop %(message)s",
)
log = logging.getLogger("sync-loop")

import MetaTrader5 as mt5  # noqa: E402  required for the live path
from lib import connection, sync as sync_lib  # noqa: E402

# Exponential backoff: cada N fallos seguidos, multiplicamos el sleep
_BACKOFF_AFTER_FAILS = 3
_BACKOFF_MAX_SEC = 30 * 60  # 30 min cap


_running = True


def _on_signal(signum, _frame):
    global _running
    log.info("received signal %s — shutting down after current iteration", signum)
    _running = False


def _telegram_alert(text: str) -> None:
    """Best-effort Telegram alert. Reusa env vars del bot."""
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    chat = (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()
    enabled = (os.environ.get("TELEGRAM_NOTIFICATIONS_ENABLED", "true") or "")\
        .strip().lower() in {"1", "true", "yes", "on"}
    if not (enabled and token and chat):
        return
    try:
        body = json.dumps({
            "chat_id": chat, "text": text[:3500],
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=4).close()
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="MT5 → dashboard journal sync poller")
    ap.add_argument("--interval", type=int,
                    default=int(os.environ.get("SYNC_INTERVAL_SECONDS", "60")),
                    help="seconds between syncs (default 60)")
    ap.add_argument("--lookback", type=int,
                    default=int(os.environ.get("SYNC_LOOKBACK_DAYS", "7")),
                    help="how many days of history to consider per pass")
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _on_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _on_signal)

    log.info("starting (interval=%ss, lookback=%sd, dashboard=%s)",
             args.interval, args.lookback,
             os.environ.get("DASHBOARD_URL", "http://127.0.0.1:8000"))

    iteration = 0
    fail_streak = 0
    base_interval = args.interval
    while _running:
        iteration += 1
        try:
            connection.ensure()
            # FIX CRÍTICO: llamamos a la función pura del lib, no al tool MCP
            # decorado que solo funciona en contexto stdio.
            res = sync_lib.push_recent_deals(mt5, lookback_days=args.lookback)
            pushed = len(res.get("pushed", []))
            failed = len(res.get("failed", []))
            if pushed:
                log.info("iter=%d pushed=%d failed=%d last_seen=%s",
                         iteration, pushed, failed, res.get("last_seen_ticket"))
            else:
                log.debug("iter=%d up-to-date (failed=%d)", iteration, failed)
            # Reset backoff
            if fail_streak > 0:
                log.info("recovered after %d failures", fail_streak)
            fail_streak = 0
        except Exception as exc:  # noqa: BLE001 — top-level loop must not crash
            fail_streak += 1
            log.exception("sync iteration failed (streak=%d): %s", fail_streak, exc)
            if fail_streak == 5:
                _telegram_alert(
                    f"⚠️ sync_loop ha fallado {fail_streak} veces seguidas. "
                    f"El journal del dashboard puede estar desfasado.\n"
                    f"Último error: {exc}"
                )

        # Backoff exponencial cuando la racha de fallos crece
        sleep_sec = base_interval
        if fail_streak >= _BACKOFF_AFTER_FAILS:
            mult = 2 ** (fail_streak - _BACKOFF_AFTER_FAILS + 1)
            sleep_sec = min(_BACKOFF_MAX_SEC, base_interval * mult)
            log.info("backoff: sleeping %ds (streak=%d)", sleep_sec, fail_streak)

        # Sleep in 1s slices so SIGINT is responsive
        slept = 0
        while _running and slept < sleep_sec:
            time.sleep(1)
            slept += 1

    log.info("clean exit after %d iterations", iteration)


if __name__ == "__main__":
    main()
