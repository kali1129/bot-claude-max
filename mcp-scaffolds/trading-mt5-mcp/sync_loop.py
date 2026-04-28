"""Background sync poller: MT5 → dashboard journal every 60s.

Run alongside the dashboard backend so closed deals appear in the journal
within a minute. The MCP itself stays as an on-demand tool for Claude;
this is the unattended path.

Usage:
    .venv/Scripts/python sync_loop.py
    .venv/Scripts/python sync_loop.py --interval 30 --lookback 1
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
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

import server  # noqa: E402


_running = True


def _on_signal(signum, _frame):
    global _running
    log.info("received signal %s — shutting down after current iteration", signum)
    _running = False


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
             os.environ.get("DASHBOARD_URL", "http://localhost:8001"))

    iteration = 0
    while _running:
        iteration += 1
        try:
            res = server.sync_to_dashboard(args.lookback)
            pushed = len(res.get("pushed", []))
            failed = len(res.get("failed", []))
            if pushed:
                log.info("iter=%d pushed=%d failed=%d last_seen=%s",
                         iteration, pushed, failed, res.get("last_seen_ticket"))
            else:
                log.debug("iter=%d up-to-date (failed=%d)", iteration, failed)
        except Exception as exc:  # noqa: BLE001 — top-level loop must not crash
            log.exception("sync iteration failed: %s", exc)

        # Sleep in 1s slices so SIGINT is responsive
        slept = 0
        while _running and slept < args.interval:
            time.sleep(1)
            slept += 1

    log.info("clean exit after %d iterations", iteration)


if __name__ == "__main__":
    main()
