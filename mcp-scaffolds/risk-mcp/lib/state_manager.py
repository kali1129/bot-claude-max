"""Atomic JSON state for the account guardian. Migration-aware.

The whole point: if the MCP crashes mid-write, we never leave a corrupt
state.json. Atomic rename ensures all-or-nothing.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

CURRENT_SCHEMA_VERSION = 1


def state_path() -> Path:
    return Path(os.path.expanduser(os.environ.get(
        "STATE_FILE",
        str(Path(__file__).resolve().parent.parent / "state.json"),
    )))


def deals_path() -> Path:
    return Path(os.path.expanduser(os.environ.get(
        "DEALS_FILE",
        str(Path(__file__).resolve().parent.parent / "deals.jsonl"),
    )))


def _starting_balance() -> float:
    raw = os.environ.get("STARTING_BALANCE", "800")
    try:
        return float(raw)
    except ValueError:
        return 800.0


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _new_state() -> dict:
    bal = _starting_balance()
    return {
        "_schema_version": CURRENT_SCHEMA_VERSION,
        "starting_balance_today": bal,
        "current_equity": bal,
        "deals_today": [],
        "consecutive_losses": 0,
        "locked_until_utc": None,
        "last_reset_date": _today_iso(),
    }


def _migrate(s: dict, from_v: int) -> dict:
    if from_v == 0:
        s["_schema_version"] = 1
        for d in s.get("deals_today", []):
            d.setdefault("deal_ticket", None)
    return s


def load_state() -> dict:
    p = state_path()
    if not p.exists():
        s = _new_state()
        save_state(s)
        return s
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # Corrupt file — back it up and start fresh.
        backup = p.with_suffix(".corrupt." + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S"))
        p.rename(backup)
        s = _new_state()
        save_state(s)
        return s
    v = s.get("_schema_version", 0)
    if v < CURRENT_SCHEMA_VERSION:
        s = _migrate(s, from_v=v)
        save_state(s)
    return s


def save_state(state: dict) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def append_history(deal: dict) -> None:
    p = deals_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(deal) + "\n")


def load_history() -> list:
    p = deals_path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
