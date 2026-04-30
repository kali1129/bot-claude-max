"""Read-only bridge to MetaTrader5 for the dashboard control panel.

On Linux VPS, MT5 runs under Wine. This bridge calls a helper script via
Wine Python subprocess to get account data. The kill-switch functions work
with local files and don't need Wine.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("mt5-bridge")

_HERE = Path(__file__).resolve().parent
_HELPER = _HERE / "mt5_wine_helper.py"
_WINE_PYTHON = r"C:\Program Files\Python311\python.exe"
_WINEPREFIX = "/opt/trading-bot/wine"
_HALT_FILE = Path(os.environ.get("HALT_FILE", "/opt/trading-bot/state/.HALT"))

# Cache status for 5 seconds to avoid spawning Wine subprocesses on every request
_status_cache = None
_status_cache_ts = 0
_CACHE_TTL = 5.0


def _run_wine_helper(command: str, *args, timeout: int = 60) -> dict:
    """Run mt5_wine_helper.py under Wine Python and parse JSON output."""
    helper_wine_path = r"Z:\opt\trading-bot\app\backend\mt5_wine_helper.py"
    cmd = [
        "wine", _WINE_PYTHON, helper_wine_path, command, *[str(a) for a in args]
    ]
    env = {
        "WINEPREFIX": _WINEPREFIX,
        "WINEARCH": "win64",
        "DISPLAY": ":99",
        "WINEDEBUG": "-all",
        "HOME": os.environ.get("HOME", "/home/deploy"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return {"connected": False, "reason": f"Wine helper timed out after {timeout}s"}
    except FileNotFoundError:
        return {"connected": False, "reason": "wine binary not found"}

    if proc.returncode != 0:
        stderr_tail = (proc.stderr or "")[-300:]
        return {"connected": False, "reason": f"Wine helper exited {proc.returncode}",
                "detail": stderr_tail}

    # Parse the last line of stdout as JSON (Wine noise goes to stderr)
    stdout = proc.stdout.strip()
    if not stdout:
        return {"connected": False, "reason": "Wine helper produced no output"}

    last_line = stdout.splitlines()[-1].strip()
    try:
        return json.loads(last_line)
    except json.JSONDecodeError:
        return {"connected": False, "reason": "Wine helper output not valid JSON",
                "detail": last_line[:200]}


def status() -> dict:
    """Snapshot of the connected MT5 account + open positions."""
    import time
    global _status_cache, _status_cache_ts

    now = time.time()
    if _status_cache is not None and (now - _status_cache_ts) < _CACHE_TTL:
        return _status_cache

    result = _run_wine_helper("status")
    _status_cache = result
    _status_cache_ts = now
    return result


def trigger_sync(lookback_days: int = 7) -> dict:
    """Sync closed deals from MT5 to dashboard journal."""
    return _run_wine_helper("sync", lookback_days, timeout=180)


# ---- Kill-switch (file-based, no Wine needed) ----

def halt_status() -> dict:
    if not _HALT_FILE.exists():
        return {"halted": False}
    try:
        body = _HALT_FILE.read_text(encoding="utf-8").strip()
    except OSError as e:
        return {"halted": True, "reason": f"halt file unreadable: {e}"}
    parsed_reason = body or "no reason recorded"
    halted_at = None
    try:
        parsed = json.loads(body) if body else {}
        if isinstance(parsed, dict):
            parsed_reason = parsed.get("reason") or parsed_reason
            halted_at = parsed.get("halted_at")
    except json.JSONDecodeError:
        pass
    out = {"halted": True, "reason": parsed_reason, "path": str(_HALT_FILE)}
    if halted_at:
        out["halted_at"] = halted_at
    return out


def halt_set(reason: str) -> dict:
    _HALT_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = {"halted_at": timestamp, "reason": reason or "no reason"}
    _HALT_FILE.write_text(json.dumps(payload), encoding="utf-8")
    log.warning("kill-switch armed reason=%r path=%s", reason, _HALT_FILE)
    return {"halted": True, **payload, "path": str(_HALT_FILE)}


def halt_clear() -> dict:
    if _HALT_FILE.exists():
        _HALT_FILE.unlink()
        log.warning("kill-switch released path=%s", _HALT_FILE)
    return {"halted": False}
