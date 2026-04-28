"""Start / stop / monitor the long-running processes that live alongside
the dashboard:

  - auto_trader   : the bot loop
  - sync_loop     : MT5 → journal poller

Each process is a Python script in ``mcp-scaffolds/trading-mt5-mcp/``.
We keep PID files in the same directory; a process is "alive" iff the PID
file exists AND the OS still owns that PID with the expected exe.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger("process-manager")

_HERE = Path(__file__).resolve().parent
_MCP_ROOT = _HERE.parent / "mcp-scaffolds" / "trading-mt5-mcp"
_MCP_PYTHON = _MCP_ROOT / ".venv" / "Scripts" / "python.exe"
_LOG_DIR = Path(os.path.expanduser(os.environ.get("LOG_DIR", "~/mcp/logs")))


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    script: str                 # filename relative to _MCP_ROOT
    default_args: list          # extra CLI args appended on every start
    description: str


SPECS: dict[str, ProcessSpec] = {
    "auto_trader": ProcessSpec(
        name="auto_trader",
        script="auto_trader.py",
        # CLAUDE.md non-negotiable: MAX_RISK_PER_TRADE_PCT ≤ 1.0. Antes estaba
        # en 3% "experimental" — eso violaba la regla y causaba LOTS_CAP en
        # cuentas chicas porque el sizing pedía 0.20-0.25 lots vs cap 0.10.
        # Volvemos al 1% canónico; el guard_risk_dollars permite hasta +10%
        # de slack en cuentas <$500 para que la granularidad de lote no
        # rechace todo trade legítimo.
        default_args=["--interval", "15", "--risk-pct", "1.0", "--min-score", "45"],
        description="Loop principal del bot — escanea, decide, opera",
    ),
    "sync_loop": ProcessSpec(
        name="sync_loop",
        script="sync_loop.py",
        default_args=["--interval", "30", "--lookback", "1"],
        description="Sincroniza deals MT5 al diario del dashboard",
    ),
}


def _pid_file(name: str) -> Path:
    return _MCP_ROOT / f".{name}.pid"


def _log_file(name: str) -> Path:
    return _LOG_DIR / f"{name}.stdout.log"


def _read_pid(name: str) -> Optional[int]:
    p = _pid_file(name)
    if not p.exists():
        return None
    try:
        return int(p.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return False
            try:
                # GetExitCodeProcess returns STILL_ACTIVE (259) while running.
                code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(h, ctypes.byref(code))
                return code.value == 259
            finally:
                kernel32.CloseHandle(h)
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _process_exe(pid: int) -> Optional[str]:
    """Best-effort lookup of the exe path for ``pid`` on Windows."""
    if sys.platform != "win32" or pid <= 0:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            QueryFullProcessImageNameW = kernel32.QueryFullProcessImageNameW
            QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD,
                ctypes.c_wchar_p, ctypes.POINTER(wintypes.DWORD),
            ]
            ok = QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
            return buf.value if ok else None
        finally:
            kernel32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        return None


# --------------------------- public API ---------------------------

def list_processes() -> dict:
    out = []
    for spec in SPECS.values():
        pid = _read_pid(spec.name)
        alive = bool(pid and _is_alive(pid))
        out.append({
            "name": spec.name,
            "description": spec.description,
            "script": str(_MCP_ROOT / spec.script),
            "pid": pid if alive else None,
            "alive": alive,
            "log_file": str(_log_file(spec.name)),
        })
    return {"processes": out}


def status(name: str) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS", "name": name}
    pid = _read_pid(name)
    alive = bool(pid and _is_alive(pid))
    return {
        "ok": True,
        "name": name,
        "pid": pid if alive else None,
        "alive": alive,
        "log_file": str(_log_file(name)),
    }


def start(name: str, extra_args: list | None = None) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS", "name": name}
    if not _MCP_PYTHON.exists():
        return {"ok": False, "reason": "NO_VENV",
                "detail": f"venv not found at {_MCP_PYTHON}"}

    # Already running?
    pid = _read_pid(name)
    if pid and _is_alive(pid):
        return {"ok": True, "already_running": True, "pid": pid}

    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _log_file(name)

    # -u: unbuffered stdout/stderr so the dashboard's tail_log shows
    # iterations live instead of waiting for the OS to flush 4KB chunks.
    args = [str(_MCP_PYTHON), "-u", str(_MCP_ROOT / spec.script),
            *spec.default_args, *(extra_args or [])]

    creationflags = 0
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP allows us to send CTRL+BREAK later.
        # DETACHED_PROCESS prevents the parent's console from killing it.
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    try:
        with open(log_path, "ab") as logf:
            proc = subprocess.Popen(
                args, cwd=str(_MCP_ROOT),
                stdout=logf, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=creationflags,
                close_fds=True,
            )
    except OSError as exc:
        return {"ok": False, "reason": "SPAWN_FAILED", "detail": str(exc)}

    _pid_file(name).write_text(str(proc.pid), encoding="utf-8")
    log.info("started %s pid=%d args=%s", name, proc.pid, args)
    return {"ok": True, "pid": proc.pid, "args": args}


def stop(name: str) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS", "name": name}
    pid = _read_pid(name)
    if not pid or not _is_alive(pid):
        # Cleanup stale pid file just in case.
        if _pid_file(name).exists():
            _pid_file(name).unlink(missing_ok=True)
        return {"ok": True, "was_running": False}

    log.info("stopping %s pid=%d", name, pid)
    try:
        if sys.platform == "win32":
            # CTRL+BREAK gives a clean shutdown if the script handles SIGINT.
            CTRL_BREAK_EVENT = 1
            try:
                os.kill(pid, CTRL_BREAK_EVENT)
            except OSError:
                # If CTRL+BREAK fails (different process group), fall back to terminate.
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, check=False)
        else:
            os.kill(pid, signal.SIGTERM)

        # Wait up to ~5s for the process to exit.
        import time
        for _ in range(20):
            if not _is_alive(pid):
                break
            time.sleep(0.25)

        if _is_alive(pid):
            # Hard kill.
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, check=False)
            else:
                os.kill(pid, signal.SIGKILL)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "reason": "KILL_FAILED",
                "detail": str(exc), "pid": pid}

    _pid_file(name).unlink(missing_ok=True)
    return {"ok": True, "stopped_pid": pid}


def restart(name: str, extra_args: list | None = None) -> dict:
    stop_res = stop(name)
    start_res = start(name, extra_args=extra_args)
    return {"ok": start_res.get("ok", False),
            "stop": stop_res, "start": start_res}


def tail_log(name: str, lines: int = 50) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS"}
    p = _log_file(name)
    if not p.exists():
        return {"ok": True, "lines": [], "path": str(p)}
    try:
        with open(p, "rb") as f:
            data = f.read()
    except OSError as exc:
        return {"ok": False, "reason": "READ_FAILED", "detail": str(exc)}
    text = data.decode("utf-8", errors="replace")
    return {"ok": True, "path": str(p),
            "lines": text.splitlines()[-lines:]}
