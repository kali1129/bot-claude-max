"""Start / stop / monitor the long-running processes that live alongside
the dashboard:

  - auto_trader   : the bot loop
  - sync_loop     : MT5 -> journal poller

On Linux VPS these run as systemd services (trading-auto-trader,
trading-sync-loop). The dashboard's process panel talks to systemd
via subprocess calls to systemctl/journalctl.

On Windows dev machines, falls back to direct subprocess spawning
with PID files (legacy behaviour).
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
_LOG_DIR = Path(os.path.expanduser(os.environ.get("LOG_DIR", "~/mcp/logs")))

# Detect platform: Linux with systemd vs Windows
_USE_SYSTEMD = sys.platform != "win32" and Path("/run/systemd/system").exists()


@dataclass(frozen=True)
class ProcessSpec:
    name: str
    script: str                 # filename relative to _MCP_ROOT
    default_args: list          # extra CLI args appended on every start
    description: str
    systemd_unit: str           # systemd service name on Linux


SPECS: dict[str, ProcessSpec] = {
    "auto_trader": ProcessSpec(
        name="auto_trader",
        script="auto_trader.py",
        default_args=["--interval", "300", "--risk-pct", "1.0", "--min-score", "70"],
        description="Loop principal del bot -- escanea, decide, opera",
        systemd_unit="trading-auto-trader",
    ),
    "sync_loop": ProcessSpec(
        name="sync_loop",
        script="sync_loop.py",
        default_args=["--interval", "60", "--lookback", "7"],
        description="Sincroniza deals MT5 al diario del dashboard",
        systemd_unit="trading-sync-loop",
    ),
}


# ============================================================================
# systemd backend (Linux VPS)
# ============================================================================

def _systemctl(action: str, unit: str, timeout: int = 10) -> dict:
    """Run a systemctl command. Returns {"ok": bool, ...}."""
    try:
        r = subprocess.run(
            ["sudo", "systemctl", action, unit],
            capture_output=True, text=True, timeout=timeout,
        )
        return {"ok": r.returncode == 0, "stdout": r.stdout.strip(),
                "stderr": r.stderr.strip()}
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": "TIMEOUT"}
    except FileNotFoundError:
        return {"ok": False, "reason": "SYSTEMCTL_NOT_FOUND"}
    except Exception as exc:
        return {"ok": False, "reason": "ERROR", "detail": str(exc)}


def _systemd_is_active(unit: str) -> bool:
    r = subprocess.run(
        ["systemctl", "is-active", unit],
        capture_output=True, text=True, timeout=5,
    )
    return r.stdout.strip() == "active"


def _systemd_status(spec: ProcessSpec) -> dict:
    unit = spec.systemd_unit
    alive = _systemd_is_active(unit)
    # Get MainPID
    pid = None
    try:
        r = subprocess.run(
            ["systemctl", "show", unit, "--property=MainPID", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        p = int(r.stdout.strip())
        if p > 0:
            pid = p
    except (ValueError, subprocess.TimeoutExpired):
        pass
    return {
        "ok": True,
        "name": spec.name,
        "pid": pid if alive else None,
        "alive": alive,
        "systemd_unit": unit,
        "log_file": f"journalctl -u {unit}",
    }


def _systemd_start(spec: ProcessSpec) -> dict:
    if _systemd_is_active(spec.systemd_unit):
        return {"ok": True, "already_running": True,
                "systemd_unit": spec.systemd_unit}
    res = _systemctl("start", spec.systemd_unit)
    if res["ok"]:
        log.info("systemd started %s", spec.systemd_unit)
        return {"ok": True, "started": True,
                "systemd_unit": spec.systemd_unit}
    return {"ok": False, "reason": "SYSTEMD_START_FAILED",
            "detail": res.get("stderr", "")}


def _systemd_stop(spec: ProcessSpec) -> dict:
    was_running = _systemd_is_active(spec.systemd_unit)
    if not was_running:
        return {"ok": True, "was_running": False}
    res = _systemctl("stop", spec.systemd_unit)
    if res["ok"]:
        log.info("systemd stopped %s", spec.systemd_unit)
        return {"ok": True, "was_running": True, "stopped": True}
    return {"ok": False, "reason": "SYSTEMD_STOP_FAILED",
            "detail": res.get("stderr", "")}


def _systemd_restart(spec: ProcessSpec) -> dict:
    res = _systemctl("restart", spec.systemd_unit)
    if res["ok"]:
        log.info("systemd restarted %s", spec.systemd_unit)
        return {"ok": True, "restarted": True,
                "systemd_unit": spec.systemd_unit}
    return {"ok": False, "reason": "SYSTEMD_RESTART_FAILED",
            "detail": res.get("stderr", "")}


def _systemd_tail_log(spec: ProcessSpec, lines: int = 50) -> dict:
    try:
        r = subprocess.run(
            ["journalctl", "-u", spec.systemd_unit, "--no-pager",
             "-n", str(lines), "--output=cat"],
            capture_output=True, timeout=10,
        )
        text = r.stdout.decode("utf-8", errors="replace")
        clean = [ln for ln in text.splitlines() if ln.strip()]
        return {"ok": True, "path": f"journalctl -u {spec.systemd_unit}",
                "lines": clean[-lines:]}
    except Exception as exc:
        return {"ok": False, "reason": "LOG_READ_FAILED",
                "detail": str(exc)}


# ============================================================================
# Subprocess/PID-file backend (Windows dev)
# ============================================================================

_MCP_PYTHON = _MCP_ROOT / ".venv" / "Scripts" / "python.exe"


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
                code = ctypes.c_ulong()
                kernel32.GetExitCodeProcess(h, ctypes.byref(code))
                return code.value == 259
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _win_status(spec: ProcessSpec) -> dict:
    pid = _read_pid(spec.name)
    alive = bool(pid and _is_alive(pid))
    return {
        "ok": True,
        "name": spec.name,
        "pid": pid if alive else None,
        "alive": alive,
        "log_file": str(_log_file(spec.name)),
    }


def _win_start(spec: ProcessSpec, extra_args: list | None = None) -> dict:
    if not _MCP_PYTHON.exists():
        return {"ok": False, "reason": "NO_VENV",
                "detail": f"venv not found at {_MCP_PYTHON}"}
    pid = _read_pid(spec.name)
    if pid and _is_alive(pid):
        return {"ok": True, "already_running": True, "pid": pid}
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = _log_file(spec.name)
    args = [str(_MCP_PYTHON), "-u", str(_MCP_ROOT / spec.script),
            *spec.default_args, *(extra_args or [])]
    creationflags = 0
    if sys.platform == "win32":
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
    _pid_file(spec.name).write_text(str(proc.pid), encoding="utf-8")
    log.info("started %s pid=%d args=%s", spec.name, proc.pid, args)
    return {"ok": True, "pid": proc.pid, "args": args}


def _win_stop(spec: ProcessSpec) -> dict:
    pid = _read_pid(spec.name)
    if not pid or not _is_alive(pid):
        if _pid_file(spec.name).exists():
            _pid_file(spec.name).unlink(missing_ok=True)
        return {"ok": True, "was_running": False}
    log.info("stopping %s pid=%d", spec.name, pid)
    try:
        if sys.platform == "win32":
            CTRL_BREAK_EVENT = 1
            try:
                os.kill(pid, CTRL_BREAK_EVENT)
            except OSError:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, check=False)
        else:
            os.kill(pid, signal.SIGTERM)
        import time
        for _ in range(20):
            if not _is_alive(pid):
                break
            time.sleep(0.25)
        if _is_alive(pid):
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                               capture_output=True, check=False)
            else:
                os.kill(pid, signal.SIGKILL)
    except Exception as exc:
        return {"ok": False, "reason": "KILL_FAILED",
                "detail": str(exc), "pid": pid}
    _pid_file(spec.name).unlink(missing_ok=True)
    return {"ok": True, "stopped_pid": pid}


def _win_tail_log(spec: ProcessSpec, lines: int = 50) -> dict:
    p = _log_file(spec.name)
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


# ============================================================================
# Public API (delegates to systemd or Windows backend)
# ============================================================================

def list_processes() -> dict:
    out = []
    for spec in SPECS.values():
        if _USE_SYSTEMD:
            s = _systemd_status(spec)
        else:
            s = _win_status(spec)
        out.append({
            "name": spec.name,
            "description": spec.description,
            "script": str(_MCP_ROOT / spec.script),
            "pid": s.get("pid"),
            "alive": s.get("alive", False),
            "log_file": s.get("log_file", str(_log_file(spec.name))),
            "backend": "systemd" if _USE_SYSTEMD else "subprocess",
        })
    return {"processes": out}


def status(name: str) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS", "name": name}
    if _USE_SYSTEMD:
        return _systemd_status(spec)
    return _win_status(spec)


def start(name: str, extra_args: list | None = None) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS", "name": name}
    if _USE_SYSTEMD:
        return _systemd_start(spec)
    return _win_start(spec, extra_args)


def stop(name: str) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS", "name": name}
    if _USE_SYSTEMD:
        return _systemd_stop(spec)
    return _win_stop(spec)


def restart(name: str, extra_args: list | None = None) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS", "name": name}
    if _USE_SYSTEMD:
        return _systemd_restart(spec)
    stop_res = _win_stop(spec)
    start_res = _win_start(spec, extra_args)
    return {"ok": start_res.get("ok", False),
            "stop": stop_res, "start": start_res}


def tail_log(name: str, lines: int = 50) -> dict:
    spec = SPECS.get(name)
    if spec is None:
        return {"ok": False, "reason": "UNKNOWN_PROCESS"}
    if _USE_SYSTEMD:
        return _systemd_tail_log(spec, lines)
    return _win_tail_log(spec, lines)
