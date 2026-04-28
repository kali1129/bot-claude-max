"""Append-only JSONL helpers for audit trails.

Port of xm-mt5-trading-platform/src/common/jsonl.py. Kept identical because
the bot nuevo also uses JSONL for orders/deals/audit.
"""
from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any


JsonDefault = Callable[[Any], Any]


def append_jsonl(path: Path, record: Any, *, default: JsonDefault | None = None) -> None:
    """Append one JSON object to a JSONL file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True, default=default))
        handle.write("\n")


def read_jsonl_records(path: Path, *, skip_invalid: bool = True) -> list[dict[str, Any]]:
    """Return parsed JSON objects from a JSONL file."""
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                if skip_invalid:
                    continue
                raise
            if isinstance(payload, dict):
                records.append(payload)
    return records


def read_jsonl_tail(
    path: Path,
    *,
    max_lines: int = 500,
    skip_invalid: bool = True,
) -> list[dict[str, Any]]:
    """Return the last *max_lines* JSON objects from a JSONL file via tail-seek."""
    if not path.exists():
        return []

    read_bytes = max(max_lines * 768, 16384)

    try:
        file_size = path.stat().st_size
    except OSError:
        return read_jsonl_records(path, skip_invalid=skip_invalid)

    with path.open("rb") as fh:
        if file_size <= read_bytes:
            raw_bytes = fh.read()
        else:
            fh.seek(-read_bytes, 2)
            raw_bytes = fh.read()
            nl = raw_bytes.find(b"\n")
            if nl != -1:
                raw_bytes = raw_bytes[nl + 1 :]

    records: list[dict[str, Any]] = []
    for line in raw_bytes.decode("utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            if skip_invalid:
                continue
            raise
        if isinstance(payload, dict):
            records.append(payload)

    return records[-max_lines:]


__all__ = ["append_jsonl", "read_jsonl_records", "read_jsonl_tail"]
