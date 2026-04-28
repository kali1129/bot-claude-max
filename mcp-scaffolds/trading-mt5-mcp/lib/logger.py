"""JSONL logger for orders + paper-mode orders."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(os.path.expanduser(os.environ.get("LOG_DIR", "~/mcp/logs")))


def _write(path: Path, payload: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")


def log_order(payload: dict) -> None:
    _write(LOG_DIR / "orders.jsonl", payload)


def log_paper(payload: dict) -> None:
    _write(LOG_DIR / "paper_orders.jsonl", payload)


def log_deal(payload: dict) -> None:
    _write(LOG_DIR / "deals.jsonl", payload)
