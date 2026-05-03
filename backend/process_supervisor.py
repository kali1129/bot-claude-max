"""process_supervisor.py — spawn/monitor/kill del auto_trader.py per usuario.

FASE 3: cuando bot_supervisor.start_bot dice OK (slots/trial/creds), este
módulo spawnea un subprocess con:
  - WINEPREFIX = /opt/trading-bot/users/{id}/wine
  - LOG_DIR    = /opt/trading-bot/users/{id}/logs
  - STATE_DIR  = /opt/trading-bot/users/{id}/state (para capital_ledger,
    expectancy_tracker, position_state per user)
  - MT5_LOGIN  = el login del usuario
  - MT5_PASSWORD = descifrado en memoria, pasado via env
  - MT5_SERVER, MT5_PATH = del template
  - USER_ID    = identificador para audit/logs
  - TRADING_MODE = "demo" o "live" según user.is_demo
  - HALT_FILE  = /opt/trading-bot/users/{id}/state/.HALT

PIDs persistidos en ``state/process_supervisor.json``:
  {user_id: {pid, started_at, prefix}, ...}

Al reinicio del backend, se chequean los PIDs:
  - Si el proceso sigue vivo → reattach (mark as running).
  - Si murió → mark stopped con exit_reason="orphan_crash".

start_bot_process(user_id, mt5_creds, run_id) retorna {pid, started_at}.
stop_bot_process(user_id) → graceful TERM con timeout, luego KILL.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import wine_prefix_manager

log = logging.getLogger("process_supervisor")


PIDS_FILE = Path(os.environ.get(
    "PROCESS_SUPERVISOR_PIDS_FILE",
    "/opt/trading-bot/state/process_supervisor.json"
))

AUTO_TRADER_PATH = Path(os.environ.get(
    "AUTO_TRADER_SCRIPT",
    "/opt/trading-bot/app/mcp-scaffolds/trading-mt5-mcp/auto_trader.py"
))

DEFAULT_INTERVAL_SEC = 120
DEFAULT_RISK_PCT = 1.0
DEFAULT_MIN_SCORE = 60

GRACEFUL_STOP_TIMEOUT_SEC = 15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────── PID file persistence ───────────────────────

def _load_pids() -> dict:
    if not PIDS_FILE.exists():
        return {}
    try:
        return json.loads(PIDS_FILE.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_pids(data: dict) -> None:
    try:
        PIDS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = PIDS_FILE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str),
                        encoding="utf-8")
        os.replace(tmp, PIDS_FILE)
    except OSError as exc:
        log.warning("save_pids failed: %s", exc)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        # signal 0 = no-op pero raise si el PID no existe / no podemos
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ─────────────────────────── public API ───────────────────────────

def is_running(user_id: str) -> bool:
    """True si hay un proceso vivo asociado al user."""
    pids = _load_pids()
    rec = pids.get(user_id)
    if not rec:
        return False
    return _pid_alive(int(rec.get("pid") or 0))


def get_pid(user_id: str) -> Optional[int]:
    pids = _load_pids()
    rec = pids.get(user_id)
    if not rec:
        return None
    pid = int(rec.get("pid") or 0)
    return pid if _pid_alive(pid) else None


async def start_bot_process(
    *,
    user_id: str,
    run_id: str,
    mt5_login: int,
    mt5_password: str,
    mt5_server: str,
    is_demo: bool,
    interval_sec: int = DEFAULT_INTERVAL_SEC,
    risk_pct: float = DEFAULT_RISK_PCT,
    min_score: int = DEFAULT_MIN_SCORE,
) -> dict:
    """Lanza el subprocess auto_trader.py para el usuario. Asíncrono porque
    primero clona el Wine prefix si no existe (puede tardar 1-3 min).

    Retorna {pid, started_at, prefix, state_dir, logs_dir}."""
    if is_running(user_id):
        log.info("process already running for user=%s", user_id)
        return {"already_running": True, "pid": get_pid(user_id)}

    # 1. Clonar prefix si no existe (idempotente)
    if not wine_prefix_manager.has_user_prefix(user_id):
        log.info("clonando prefix template para user=%s ...", user_id)
        await wine_prefix_manager.clone_for_user(user_id)

    prefix = wine_prefix_manager.prefix_path(user_id)
    state_dir = wine_prefix_manager.state_path(user_id)
    logs_dir = wine_prefix_manager.logs_path(user_id)
    state_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    mt5_path = wine_prefix_manager.mt5_terminal_path_inside_prefix(user_id)
    if not mt5_path:
        raise RuntimeError(
            f"MT5 terminal no encontrado en prefix de {user_id} — "
            "template puede estar mal configurado"
        )

    # Halt file dedicado per-user
    halt_file = state_dir / ".HALT"

    # Asegurar que existe strategy_config.json en el state dir del user
    # con defaults (mode=auto, min_score=70). Si ya existe (porque el
    # user lo configuró), no lo tocamos. El bot lee este archivo cada
    # iteración, así cualquier cambio del usuario aplica en vivo.
    strategy_state = state_dir / "strategy_config.json"
    if not strategy_state.exists():
        try:
            import json as _j
            from datetime import datetime as _dt, timezone as _tz
            strategy_state.write_text(_j.dumps({
                "mode": "auto",
                "active_strategy": "trend_rider",
                "min_score": 70,
                "updated_at": _dt.now(_tz.utc).isoformat(),
                "note": "default — el usuario puede cambiar via /estrategias",
            }, indent=2), encoding="utf-8")
            log.info("seeded default strategy_config for user=%s", user_id)
        except OSError as exc:
            log.warning("could not seed strategy_config for %s: %s",
                        user_id, exc)

    # 2. Construir env. Pasamos secretos por env (no se persisten en disco).
    env = os.environ.copy()
    env.update({
        "WINEPREFIX": str(prefix),
        "WINEARCH": "win64",
        "DISPLAY": os.environ.get("DISPLAY", ":99"),
        "WINEDEBUG": "-all",
        # Per-user state + logs
        "LOG_DIR": str(logs_dir),
        "STATE_DIR": str(state_dir),
        # MT5 creds — descifradas en memoria, NO en .env
        "MT5_LOGIN": str(mt5_login),
        "MT5_PASSWORD": mt5_password,
        "MT5_SERVER": mt5_server,
        "MT5_PATH": mt5_path,
        # Modo trading
        "TRADING_MODE": "demo" if is_demo else "live",
        # Halt file dedicado
        "HALT_FILE": str(halt_file),
        # Identificador para audit
        "USER_ID": user_id,
        "RUN_ID": run_id,
        # Magic number único per user (deriva del user_id hash)
        "MT5_MAGIC": str(_magic_for_user(user_id)),
    })

    # 3. Spawn el subprocess. Wine Python ejecuta auto_trader.py.
    # Para que MT5 funcione, el script tiene que correr DENTRO de Wine —
    # lanzamos `wine python.exe auto_trader.py`.
    wine_python = (
        "C:\\Program Files\\Python311\\python.exe"
    )
    auto_trader_z = (
        f"Z:{str(AUTO_TRADER_PATH)}".replace("/", "\\")
    )
    cmd = [
        "wine",
        wine_python,
        auto_trader_z,
        "--interval", str(interval_sec),
        "--risk-pct", str(risk_pct),
        "--min-score", str(min_score),
    ]

    # Logs van a un archivo en el dir del usuario, append mode.
    stdout_log = logs_dir / "auto_trader.stdout.log"
    stderr_log = logs_dir / "auto_trader.stderr.log"

    log.info("spawn user-bot user=%s prefix=%s cmd=%s",
             user_id, prefix, " ".join(cmd))
    try:
        with open(stdout_log, "ab") as out_f, open(stderr_log, "ab") as err_f:
            proc = subprocess.Popen(
                cmd,
                cwd=str(AUTO_TRADER_PATH.parent),
                env=env,
                stdout=out_f,
                stderr=err_f,
                stdin=subprocess.DEVNULL,
                start_new_session=True,   # nuevo grupo → kill grupo entero
            )
    except Exception as exc:
        log.error("spawn failed for %s: %s", user_id, exc)
        raise

    # 4. Persistir PID
    pids = _load_pids()
    pids[user_id] = {
        "pid": proc.pid,
        "pgid": os.getpgid(proc.pid),
        "started_at": _now_iso(),
        "run_id": run_id,
        "prefix": str(prefix),
        "logs_dir": str(logs_dir),
    }
    _save_pids(pids)

    log.info("user-bot started: user=%s pid=%s run_id=%s",
             user_id, proc.pid, run_id)
    return {
        "pid": proc.pid,
        "started_at": pids[user_id]["started_at"],
        "prefix": str(prefix),
        "state_dir": str(state_dir),
        "logs_dir": str(logs_dir),
    }


async def stop_bot_process(user_id: str) -> dict:
    """Stop graceful (SIGTERM) → wait → SIGKILL si no muere."""
    pids = _load_pids()
    rec = pids.get(user_id)
    if not rec:
        return {"ok": False, "reason": "NOT_TRACKED"}
    pid = int(rec.get("pid") or 0)
    pgid = int(rec.get("pgid") or pid)
    if pid <= 0 or not _pid_alive(pid):
        # cleanup record viejo
        pids.pop(user_id, None)
        _save_pids(pids)
        return {"ok": True, "already_dead": True}

    log.info("stopping user-bot user=%s pid=%s pgid=%s", user_id, pid, pgid)
    # Killear todo el proceso group para llevarse Wine + Python juntos
    try:
        os.killpg(pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass

    # Esperar graceful
    deadline = asyncio.get_event_loop().time() + GRACEFUL_STOP_TIMEOUT_SEC
    while _pid_alive(pid) and asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(0.5)

    if _pid_alive(pid):
        log.warning("force kill user-bot user=%s pid=%s", user_id, pid)
        try:
            os.killpg(pgid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass

    pids.pop(user_id, None)
    _save_pids(pids)
    return {"ok": True, "stopped": True}


def reattach_on_startup() -> dict:
    """Al reiniciar el backend, chequea los PIDs persistidos.
    - Vivos → mantener record.
    - Muertos → limpiar (el bot_supervisor los marca como crashed).

    Retorna stats de re-attach."""
    pids = _load_pids()
    alive = []
    dead = []
    for user_id, rec in list(pids.items()):
        pid = int(rec.get("pid") or 0)
        if _pid_alive(pid):
            alive.append({"user_id": user_id, "pid": pid})
        else:
            dead.append({"user_id": user_id, "pid": pid})
            pids.pop(user_id, None)
    _save_pids(pids)
    log.info("reattach: alive=%d dead=%d", len(alive), len(dead))
    return {"alive": alive, "dead": dead}


def list_running() -> list:
    """Lista todos los procesos user-bot vivos."""
    pids = _load_pids()
    out = []
    for user_id, rec in pids.items():
        pid = int(rec.get("pid") or 0)
        if _pid_alive(pid):
            out.append({
                "user_id": user_id,
                "pid": pid,
                "started_at": rec.get("started_at"),
                "run_id": rec.get("run_id"),
            })
    return out


def _magic_for_user(user_id: str) -> int:
    """Deriva un magic number MT5 único per user a partir de su ID.
    Range: 30000000-39999999 (admin usa 20260427)."""
    import hashlib
    h = hashlib.sha1(user_id.encode("utf-8")).digest()
    n = int.from_bytes(h[:4], "big") % 10_000_000
    return 30_000_000 + n


def tail_log(user_id: str, *, lines: int = 200, which: str = "stdout") -> str:
    """Lee las últimas N líneas del log del user-bot."""
    logs_dir = wine_prefix_manager.logs_path(user_id)
    if which == "stderr":
        path = logs_dir / "auto_trader.stderr.log"
    else:
        path = logs_dir / "auto_trader.stdout.log"
    if not path.exists():
        return ""
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            # Read last ~64 KB para soportar lines hasta 1000.
            f.seek(max(0, size - 65536))
            data = f.read().decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-lines:])
    except OSError as exc:
        return f"[error reading log: {exc}]"
