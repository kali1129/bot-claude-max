"""File-based kill-switch shared by all MCPs.

`place_order` checks this BEFORE every other guard. Latency-zero,
network-free, dashboard-independent. The dashboard /api/halt endpoint
writes/deletes the same file path so the GUI button and the CLI
`touch ~/mcp/.HALT` are equivalent.
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional

HALT_FILE = os.path.expanduser(os.environ.get("HALT_FILE", "/opt/trading-bot/state/.HALT"))


def is_halted() -> bool:
    return os.path.exists(HALT_FILE)


def reason() -> Optional[str]:
    if not is_halted():
        return None
    try:
        with open(HALT_FILE) as f:
            content = f.read().strip()
        # Backend writes plain "<timestamp> :: <reason>" lines; doc 10 uses JSON.
        # Try JSON first for richer payloads, then plain text.
        try:
            return json.loads(content).get("reason", "no reason given")
        except json.JSONDecodeError:
            return content or "no reason given"
    except OSError:
        return "halt file present but unreadable"


def halt(reason_text: str) -> dict:
    os.makedirs(os.path.dirname(HALT_FILE), exist_ok=True)
    payload = {
        "halted_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason_text or "no reason",
    }
    tmp = HALT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, HALT_FILE)
    return {"ok": True, "halted": True, **payload}


def resume() -> dict:
    if not is_halted():
        return {"ok": True, "was_halted": False}
    os.remove(HALT_FILE)
    return {"ok": True, "was_halted": True, "resumed_at": datetime.now(timezone.utc).isoformat()}
