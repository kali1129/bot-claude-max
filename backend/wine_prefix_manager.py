"""wine_prefix_manager.py — gestión de Wine prefixes per usuario.

FASE 3: cuando un usuario arranca su bot por primera vez, clonamos el
template Wine prefix (que tiene Python + MT5 instalados) a un directorio
dedicado: ``/opt/trading-bot/users/{user_id}/wine``. Este prefix es
persistente — cada usuario mantiene su sesión MT5, configuración del
terminal, etc.

Operaciones:
  - has_template() → bool
  - has_user_prefix(user_id) → bool
  - clone_for_user(user_id) → async, lanza WinePrefixError si falla
  - delete_user_prefix(user_id) → cleanup tras eliminar usuario
  - prefix_path(user_id) → str
  - mt5_terminal_path(user_id) → str (path .exe en formato Z:\ Wine)

Estado:
  - Template: ``/opt/trading-bot/wine_template``
  - Usuarios: ``/opt/trading-bot/users/{user_id}/wine``
  - Logs: ``/opt/trading-bot/users/{user_id}/logs``
  - State: ``/opt/trading-bot/users/{user_id}/state``

Notas operacionales:
  - Cada prefix son ~2.8 GB. Con disco de 100 GB → cabe ~30 users.
  - cp -r toma 1-3 min. Hacer la clonación async para no bloquear el
    endpoint /bot/start.
  - Cada Wine instance levanta su propio wineserver. Cuidar concurrencia.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger("wine_prefix_manager")


TEMPLATE_PREFIX = Path(os.environ.get(
    "WINE_TEMPLATE_PREFIX", "/opt/trading-bot/wine_template"
))
USERS_BASE = Path(os.environ.get(
    "USERS_BASE_DIR", "/opt/trading-bot/users"
))
ADMIN_PREFIX = Path(os.environ.get(
    "WINEPREFIX", "/opt/trading-bot/wine"
))


class WinePrefixError(Exception):
    """Error en operaciones del Wine prefix."""


# ─────────────────────────── helpers ───────────────────────────

def has_template() -> bool:
    """True si el template prefix existe y es funcional."""
    if not TEMPLATE_PREFIX.exists():
        return False
    if not (TEMPLATE_PREFIX / "drive_c").is_dir():
        return False
    # Verificar que tiene Python311 instalado
    if not (TEMPLATE_PREFIX / "drive_c" / "Program Files" / "Python311").is_dir():
        return False
    return True


def template_health() -> dict:
    """Diagnóstico del template para mostrar al admin."""
    if not TEMPLATE_PREFIX.exists():
        return {
            "ok": False,
            "exists": False,
            "reason": "template no creado",
            "fix": "correr: bash /opt/trading-bot/app/scripts/setup-wine-template.sh --clone-from-admin",
        }
    has_python = (TEMPLATE_PREFIX / "drive_c" / "Program Files" / "Python311").is_dir()
    has_mt5 = any(
        "mt5" in p.name.lower() or "metatrader" in p.name.lower()
        for p in (TEMPLATE_PREFIX / "drive_c" / "Program Files").iterdir()
    ) if (TEMPLATE_PREFIX / "drive_c" / "Program Files").is_dir() else False
    try:
        size_bytes = sum(
            f.stat().st_size for f in TEMPLATE_PREFIX.rglob("*") if f.is_file()
        )
    except OSError:
        size_bytes = 0
    return {
        "ok": has_python and has_mt5,
        "exists": True,
        "has_python": has_python,
        "has_mt5": has_mt5,
        "path": str(TEMPLATE_PREFIX),
        "size_mb": round(size_bytes / (1024 * 1024), 1),
    }


def user_dir(user_id: str) -> Path:
    """Base directory del usuario: prefix + state + logs."""
    safe = "".join(c for c in user_id if c.isalnum() or c in ("-", "_"))
    if not safe:
        raise WinePrefixError(f"user_id inválido: {user_id!r}")
    return USERS_BASE / safe


def prefix_path(user_id: str) -> Path:
    return user_dir(user_id) / "wine"


def state_path(user_id: str) -> Path:
    return user_dir(user_id) / "state"


def logs_path(user_id: str) -> Path:
    return user_dir(user_id) / "logs"


def has_user_prefix(user_id: str) -> bool:
    return prefix_path(user_id).is_dir() and \
        (prefix_path(user_id) / "drive_c").is_dir()


def mt5_terminal_path_inside_prefix(user_id: str) -> Optional[str]:
    """Path del terminal64.exe dentro del prefix del usuario, en formato
    Z:\ que entiende Wine Python (ej. 'Z:\\opt\\trading-bot\\users\\u-X\\wine\\drive_c\\...').

    El template tiene XM Global MT5 instalado; mantenemos esa ruta.
    """
    base = prefix_path(user_id) / "drive_c" / "Program Files" / "XM Global MT5"
    exe = base / "terminal64.exe"
    if not exe.exists():
        return None
    # Wine Z:\ mapea a Linux /
    return f"Z:{str(exe)}".replace("/", "\\")


# ─────────────────────────── clone / delete ───────────────────────────

async def clone_for_user(user_id: str) -> dict:
    """Clona el template a un prefix dedicado del usuario. Async (corre
    cp -r en thread pool para no bloquear el event loop).

    Si ya existe un prefix INCOMPLETO (e.g., un clone previo se cortó por
    crash), lo borra y re-clona. Solo skipea si has_user_prefix(user_id)
    devuelve True (drive_c presente).
    """
    if not has_template():
        raise WinePrefixError(
            "template no existe. Admin: corré "
            "scripts/setup-wine-template.sh --clone-from-admin"
        )
    udir = user_dir(user_id)
    pfx = prefix_path(user_id)

    # Si ya existe Y está completo, no re-clone.
    if has_user_prefix(user_id):
        log.info("user prefix ya existe y está completo para %s", user_id)
        return {"cloned": False, "reason": "already_exists",
                "prefix": str(pfx)}

    # Si existe pero está incompleto (clone abortado), borrar antes de
    # re-clonar — sino el próximo cp tira "destino exists".
    if pfx.is_dir():
        log.warning("user prefix incompleto para %s — borrando para re-clone",
                    user_id)
        try:
            shutil.rmtree(pfx)
        except OSError as exc:
            log.error("rmtree de prefix incompleto falló: %s", exc)

    log.info("cloning template prefix → %s", pfx)
    try:
        udir.mkdir(parents=True, exist_ok=True)
        state_path(user_id).mkdir(parents=True, exist_ok=True)
        logs_path(user_id).mkdir(parents=True, exist_ok=True)

        # Clone template al prefix del user. CRÍTICO: preservar symlinks.
        # El template tiene dosdevices/z: → / (symlink al rootfs Linux). Si
        # lo seguimos, copytree copia TODO el rootfs (~80 GB) dentro del
        # prefix del user. Ya pasó: un user dejó el disco al 100%.
        # Usamos `cp -a` que preserva symlinks/perms/timestamps con un
        # flag, y es ~3x más rápido que copytree (kernel-level).
        loop = asyncio.get_event_loop()

        def _do_clone():
            import subprocess
            res = subprocess.run(
                ["cp", "-a", str(TEMPLATE_PREFIX) + "/.", str(pfx) + "/"],
                capture_output=True, text=True, timeout=600,
            )
            if res.returncode != 0:
                raise OSError(
                    f"cp -a failed (rc={res.returncode}): {res.stderr[:500]}"
                )
            return True

        Path(pfx).mkdir(parents=True, exist_ok=True)
        await loop.run_in_executor(None, _do_clone)

        log.info("clone OK for user=%s", user_id)
        return {
            "cloned": True,
            "prefix": str(pfx),
            "state_dir": str(state_path(user_id)),
            "logs_dir": str(logs_path(user_id)),
        }
    except Exception as exc:
        log.error("clone failed for %s: %s", user_id, exc)
        # Cleanup partial copy
        if pfx.is_dir():
            try:
                shutil.rmtree(pfx)
            except Exception:
                pass
        raise WinePrefixError(f"clone failed: {exc}") from exc


def delete_user_prefix(user_id: str, *, keep_logs: bool = False) -> dict:
    """Elimina el prefix del usuario. Por default también borra state +
    logs. Si ``keep_logs=True``, conserva logs/ (útil para post-mortem)."""
    udir = user_dir(user_id)
    if not udir.exists():
        return {"deleted": False, "reason": "no_dir"}
    pfx = prefix_path(user_id)
    state = state_path(user_id)
    logs = logs_path(user_id)
    deleted = []
    try:
        if pfx.is_dir():
            shutil.rmtree(pfx)
            deleted.append("wine")
        if state.is_dir():
            shutil.rmtree(state)
            deleted.append("state")
        if logs.is_dir() and not keep_logs:
            shutil.rmtree(logs)
            deleted.append("logs")
        # Si todo está vacío, borrar también el dir base
        if not any(udir.iterdir()):
            udir.rmdir()
            deleted.append("user_dir")
    except OSError as exc:
        log.warning("delete partial for %s: %s", user_id, exc)
    return {"deleted": True, "removed": deleted}


# ─────────────────────────── stats ───────────────────────────

def stats() -> dict:
    """Diagnóstico global: cuántos prefixes hay, total disk usage."""
    info = {
        "template": template_health(),
        "users_base": str(USERS_BASE),
        "user_count": 0,
        "total_size_mb": 0,
    }
    if not USERS_BASE.exists():
        return info
    user_dirs = [p for p in USERS_BASE.iterdir() if p.is_dir()]
    info["user_count"] = len(user_dirs)
    try:
        size_bytes = sum(
            f.stat().st_size for f in USERS_BASE.rglob("*") if f.is_file()
        )
        info["total_size_mb"] = round(size_bytes / (1024 * 1024), 1)
    except OSError:
        pass
    return info
