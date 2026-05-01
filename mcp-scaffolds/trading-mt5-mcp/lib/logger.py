"""JSONL logger for orders + paper-mode orders.

Cambios vs original:
  - **Log rotation**: cuando un archivo > MAX_LOG_MB (default 30), se rota
    a ``orders.jsonl.<timestamp>`` y se mantienen los últimos 5. Antes el
    archivo crecía sin límite (orders.jsonl ya tenía 122KB en 36h).
  - Check de tamaño se hace cada ~200 writes (no en cada write — overhead).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path(os.path.expanduser(os.environ.get("LOG_DIR", "~/mcp/logs")))
MAX_LOG_MB = float(os.environ.get("MAX_LOG_MB", "30"))

_writes_since_check: dict[str, int] = {}


def _rotate_if_needed(path: Path) -> None:
    try:
        if not path.exists():
            return
        size_mb = path.stat().st_size / (1024 * 1024)
        if size_mb < MAX_LOG_MB:
            return
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rotated = path.with_suffix(path.suffix + f".{ts}")
        path.rename(rotated)
        rotated_files = sorted(path.parent.glob(f"{path.name}.*"))
        for old in rotated_files[:-5]:
            try:
                old.unlink()
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass


def _write(path: Path, payload: dict) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"ts": datetime.now(timezone.utc).isoformat(), **payload}
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, default=str) + "\n")
    key = str(path)
    cnt = _writes_since_check.get(key, 0) + 1
    _writes_since_check[key] = cnt
    if cnt >= 200:
        _rotate_if_needed(path)
        _writes_since_check[key] = 0


def log_order(payload: dict) -> None:
    _write(LOG_DIR / "orders.jsonl", payload)


def log_paper(payload: dict) -> None:
    _write(LOG_DIR / "paper_orders.jsonl", payload)


def log_deal(payload: dict) -> None:
    _write(LOG_DIR / "deals.jsonl", payload)
