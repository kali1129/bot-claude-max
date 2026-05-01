"""bot_supervisor.py — gestión del ciclo de vida del bot por usuario.

Responsabilidades:
  - Slot management: cap MAX_CONCURRENT_USER_BOTS (env, default 10).
    Cuando se llega al cap, el siguiente /bot/start retorna 409 con
    motivo "SLOTS_FULL" y un timestamp estimado de cuándo se libera.
  - Trial 24h: cada usuario que arranca su bot tiene 24h de operación
    gratis. Tras 24h el supervisor auto-stoppea. Para extender, el admin
    debe darle ``paid_until`` futuro (FASE 4: pago real).
  - Admin exempt: el admin no consume slot ni tiene trial.

Estado en Mongo:
  - collection ``bot_runs``: cada documento es un "run" (start → stop).
    {
      _id, user_id, started_at, stopped_at: null o iso,
      trial_end_at: iso (24h después de start, o null si admin),
      exit_reason: "user_stop" | "trial_expired" | "admin_force_stop"
                   | "shutdown" | "crash" | null
    }
  - collection ``users``: campo ``paid_until`` (iso) opcional. Si presente
    y futuro, el bot puede correr sin trial expirando.

NOTA importante (FASE 3 pendiente):
  El supervisor HOY solo gestiona el RECORD del run (Mongo). NO spawnea
  realmente un proceso ``auto_trader.py`` por usuario — eso requiere un
  Wine prefix per user con MT5 instalado, que todavía no está montado.
  Cuando un usuario llama /bot/start, el supervisor:
    1. Verifica slots, trial, creds (todo OK)
    2. Crea record en bot_runs (started_at = now, trial_end_at = +24h)
    3. Devuelve {ok: true, run_id, status: "queued"}
  En FASE 3 se va a agregar el spawn real (subprocess + Wine prefix
  template + systemd template). El SCHEMA y los endpoints ya quedan
  preparados.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import broker_manager
import process_supervisor
import wine_prefix_manager

log = logging.getLogger("bot_supervisor")


MAX_CONCURRENT_USER_BOTS = int(
    os.environ.get("MAX_CONCURRENT_USER_BOTS", "10")
)
TRIAL_HOURS = int(os.environ.get("USER_BOT_TRIAL_HOURS", "24"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────── helpers ───────────────────────────

async def is_user_paid(db, user_id: str) -> bool:
    """True si el user tiene paid_until en el futuro."""
    if db is None:
        return False
    user = await db.users.find_one({"_id": user_id}, {"paid_until": 1})
    if not user:
        return False
    paid = user.get("paid_until")
    if not paid:
        return False
    try:
        d = datetime.fromisoformat(str(paid).replace("Z", "+00:00"))
        return d > _now()
    except (ValueError, TypeError):
        return False


async def is_admin_user(db, user_id: str) -> bool:
    if db is None:
        return False
    user = await db.users.find_one({"_id": user_id}, {"role": 1})
    return bool(user and user.get("role") == "admin")


async def active_run(db, user_id: str) -> Optional[dict]:
    """Retorna el run activo del user (started_at sin stopped_at), o None."""
    if db is None:
        return None
    return await db.bot_runs.find_one({
        "user_id": user_id,
        "stopped_at": None,
    })


async def count_active_user_bots(db, *, exclude_admins: bool = True) -> int:
    """Conteo de bots activos. Por default excluye admins (no usan slot)."""
    if db is None:
        return 0
    pipeline = [
        {"$match": {"stopped_at": None}},
        {"$lookup": {
            "from": "users", "localField": "user_id",
            "foreignField": "_id", "as": "user",
        }},
        {"$match": {
            "user.role": {"$ne": "admin" if exclude_admins else "__never__"}
        } if exclude_admins else {}},
    ]
    if not exclude_admins:
        # simpler path
        return await db.bot_runs.count_documents({"stopped_at": None})
    cursor = db.bot_runs.aggregate(pipeline)
    items = await cursor.to_list(length=10_000)
    return len(items)


# ─────────────────────────── lifecycle ───────────────────────────

class StartResult:
    OK = "started"
    SLOTS_FULL = "slots_full"
    NO_BROKER = "no_broker"
    ALREADY_RUNNING = "already_running"


async def start_bot(db, user_id: str) -> dict:
    """Intenta arrancar el bot del user. Retorna dict con ok + reason."""
    if db is None:
        return {"ok": False, "reason": "DB_UNAVAILABLE"}

    # 1. ¿Ya está corriendo?
    running = await active_run(db, user_id)
    if running:
        return {
            "ok": False, "reason": "ALREADY_RUNNING",
            "detail": "tu bot ya está activo",
            "run_id": str(running["_id"]),
            "started_at": running["started_at"],
            "trial_end_at": running.get("trial_end_at"),
        }

    # 2. ¿Tiene credenciales MT5?
    has_creds = await broker_manager.has_creds(db, user_id)
    is_admin = await is_admin_user(db, user_id)
    if not has_creds and not is_admin:
        return {
            "ok": False, "reason": "NO_BROKER",
            "detail": (
                "Conectá tu cuenta MT5 antes de arrancar el bot. "
                "Andá a Mi Cuenta → Conectar broker."
            ),
        }

    # 3. Slot check (admin exento)
    if not is_admin:
        active_count = await count_active_user_bots(db, exclude_admins=True)
        if active_count >= MAX_CONCURRENT_USER_BOTS:
            return {
                "ok": False, "reason": "SLOTS_FULL",
                "detail": (
                    f"Cupo lleno: {active_count}/{MAX_CONCURRENT_USER_BOTS} "
                    "usuarios operando ahora. Probá más tarde — los bots "
                    "se liberan al pasar las 24h de trial."
                ),
                "max_concurrent": MAX_CONCURRENT_USER_BOTS,
                "active_count": active_count,
            }

    # 4. Determinar trial_end_at
    paid = await is_user_paid(db, user_id) if not is_admin else True
    if is_admin:
        trial_end = None  # admins sin límite
    elif paid:
        # Usuario pagó — su límite es paid_until, no trial 24h
        user = await db.users.find_one({"_id": user_id}, {"paid_until": 1})
        trial_end = user.get("paid_until")
    else:
        # Trial: 24h desde now
        trial_end = (_now() + timedelta(hours=TRIAL_HOURS)).isoformat()

    # 5. Crear el run
    run_doc = {
        "user_id": user_id,
        "started_at": _now_iso(),
        "stopped_at": None,
        "trial_end_at": trial_end,
        "exit_reason": None,
        "is_admin": is_admin,
        "is_paid": bool(paid),
    }
    res = await db.bot_runs.insert_one(run_doc)
    run_id = str(res.inserted_id)

    log.info("bot started: user=%s run_id=%s admin=%s paid=%s "
             "trial_end=%s", user_id, run_id, is_admin, paid, trial_end)

    # FASE 3: spawn real del subprocess. El admin NO usa este path —
    # su bot global ya corre como systemd service trading-auto-trader.
    spawn_info = None
    spawn_error = None
    if not is_admin:
        if not wine_prefix_manager.has_template():
            spawn_error = (
                "Wine template no configurado. El admin debe correr "
                "scripts/setup-wine-template.sh --clone-from-admin"
            )
            log.warning("user=%s start FAILED: %s", user_id, spawn_error)
            # Marcar el run como crashed para que no quede en estado raro
            await db.bot_runs.update_one(
                {"_id": res.inserted_id},
                {"$set": {
                    "stopped_at": _now_iso(),
                    "exit_reason": "no_wine_template",
                }},
            )
            return {
                "ok": False,
                "reason": "NO_TEMPLATE",
                "detail": spawn_error,
            }
        # Descifrar password para pasarla por env al subprocess
        password = await broker_manager.get_decrypted_password(db, user_id)
        if not password:
            await db.bot_runs.update_one(
                {"_id": res.inserted_id},
                {"$set": {
                    "stopped_at": _now_iso(),
                    "exit_reason": "decrypt_failed",
                }},
            )
            return {
                "ok": False,
                "reason": "DECRYPT_FAILED",
                "detail": (
                    "no pudimos descifrar tu password — re-conectá tu broker"
                ),
            }
        creds = await broker_manager.get_creds(db, user_id)
        try:
            spawn_info = await process_supervisor.start_bot_process(
                user_id=user_id,
                run_id=run_id,
                mt5_login=creds["mt5_login"],
                mt5_password=password,
                mt5_server=creds["mt5_server"],
                is_demo=bool(creds.get("is_demo", True)),
            )
            await db.bot_runs.update_one(
                {"_id": res.inserted_id},
                {"$set": {
                    "pid": spawn_info.get("pid"),
                    "prefix": spawn_info.get("prefix"),
                    "logs_dir": spawn_info.get("logs_dir"),
                }},
            )
        except Exception as exc:
            log.error("spawn user-bot failed user=%s: %s", user_id, exc)
            await db.bot_runs.update_one(
                {"_id": res.inserted_id},
                {"$set": {
                    "stopped_at": _now_iso(),
                    "exit_reason": "spawn_failed",
                    "error": str(exc),
                }},
            )
            return {
                "ok": False,
                "reason": "SPAWN_FAILED",
                "detail": str(exc),
            }

    return {
        "ok": True, "reason": StartResult.OK,
        "run_id": run_id,
        "started_at": run_doc["started_at"],
        "trial_end_at": trial_end,
        "is_admin": is_admin,
        "is_paid": paid,
        "pid": (spawn_info or {}).get("pid"),
        "note": (
            "Bot global del admin. Sigue corriendo como systemd service."
            if is_admin
            else "Bot personal lanzado. Tu Wine prefix dedicado está activo."
        ),
    }


async def stop_bot(db, user_id: str, *, reason: str = "user_stop") -> dict:
    """Detiene el bot del user. Marca el run como stopped + kill subprocess."""
    if db is None:
        return {"ok": False, "reason": "DB_UNAVAILABLE"}

    running = await active_run(db, user_id)
    if not running:
        return {"ok": False, "reason": "NOT_RUNNING",
                "detail": "tu bot no está activo"}

    # FASE 3: si el subprocess está corriendo, killearlo (SIGTERM → SIGKILL).
    # Para admin no aplica — su bot es un systemd service.
    is_admin = bool(running.get("is_admin"))
    if not is_admin:
        try:
            kill_res = await process_supervisor.stop_bot_process(user_id)
            log.info("subprocess stop result user=%s: %s", user_id, kill_res)
        except Exception as exc:
            log.warning("subprocess stop failed user=%s: %s", user_id, exc)

    await db.bot_runs.update_one(
        {"_id": running["_id"]},
        {"$set": {
            "stopped_at": _now_iso(),
            "exit_reason": reason,
        }},
    )
    log.info("bot stopped: user=%s run_id=%s reason=%s",
             user_id, str(running["_id"]), reason)
    return {
        "ok": True,
        "run_id": str(running["_id"]),
        "exit_reason": reason,
    }


async def reconcile_processes(db) -> dict:
    """Revisa que los runs activos en Mongo correspondan a procesos vivos.
    Si un run está marcado como activo pero el proceso murió → marcar como
    crashed. Llamado periódicamente desde el background loop.

    Grace period: ignorar runs que empezaron hace < SPAWN_GRACE_SEC. La
    clonación del Wine prefix + spawn puede tardar 30-60s en la primera
    vez (cp -r de 2.7 GB). Sin grace, el reconciler mataría el run en
    pleno clone.
    """
    if db is None:
        return {"checked": 0, "marked_crashed": 0}
    SPAWN_GRACE_SEC = 180   # 3 min — más que suficiente para clone + spawn
    cutoff = _now() - timedelta(seconds=SPAWN_GRACE_SEC)
    cursor = db.bot_runs.find({"stopped_at": None, "is_admin": False})
    crashed = 0
    checked = 0
    async for run in cursor:
        checked += 1
        user_id = run.get("user_id")
        if not user_id:
            continue
        # Grace period — runs jovenes no se evalúan aún
        try:
            started = datetime.fromisoformat(
                str(run.get("started_at")).replace("Z", "+00:00")
            )
            if started > cutoff:
                continue   # demasiado joven, dale tiempo al spawn
        except (ValueError, TypeError):
            pass
        if not process_supervisor.is_running(user_id):
            await db.bot_runs.update_one(
                {"_id": run["_id"]},
                {"$set": {
                    "stopped_at": _now_iso(),
                    "exit_reason": "process_crashed",
                }},
            )
            crashed += 1
            log.warning("user-bot reconcile: process dead, marking crashed "
                        "user=%s run=%s", user_id, str(run["_id"]))
    return {"checked": checked, "marked_crashed": crashed}


async def status(db, user_id: str) -> dict:
    """Estado del bot del user — running / stopped / trial info."""
    if db is None:
        return {"ok": False, "reason": "DB_UNAVAILABLE"}

    running = await active_run(db, user_id)
    if not running:
        last = await db.bot_runs.find_one(
            {"user_id": user_id},
            sort=[("started_at", -1)],
        )
        return {
            "ok": True,
            "running": False,
            "last_run": (
                {
                    "started_at": last["started_at"],
                    "stopped_at": last.get("stopped_at"),
                    "exit_reason": last.get("exit_reason"),
                }
                if last
                else None
            ),
        }

    # Calcular tiempo restante de trial
    trial_end = running.get("trial_end_at")
    seconds_remaining = None
    expired = False
    if trial_end:
        try:
            d = datetime.fromisoformat(str(trial_end).replace("Z", "+00:00"))
            delta = (d - _now()).total_seconds()
            seconds_remaining = int(delta) if delta > 0 else 0
            expired = delta <= 0
        except (ValueError, TypeError):
            pass

    return {
        "ok": True,
        "running": True,
        "run_id": str(running["_id"]),
        "started_at": running["started_at"],
        "trial_end_at": trial_end,
        "trial_seconds_remaining": seconds_remaining,
        "trial_expired": expired,
        "is_admin": bool(running.get("is_admin")),
        "is_paid": bool(running.get("is_paid")),
    }


async def slot_info(db) -> dict:
    """Info global de slots — para mostrar en banner del frontend."""
    if db is None:
        return {"ok": False}
    active = await count_active_user_bots(db, exclude_admins=True)
    return {
        "ok": True,
        "max_concurrent": MAX_CONCURRENT_USER_BOTS,
        "active": active,
        "available": max(0, MAX_CONCURRENT_USER_BOTS - active),
        "trial_hours": TRIAL_HOURS,
    }


# ─────────────────────────── trial expiration check ──────────────────

async def check_expired_trials(db) -> dict:
    """Recorre los runs activos y stoppea los que expiraron su trial.
    Pensado para correr cada 60s desde un background task."""
    if db is None:
        return {"checked": 0, "stopped": 0}
    now = _now()
    cursor = db.bot_runs.find({
        "stopped_at": None,
        "trial_end_at": {"$ne": None},
    })
    stopped_count = 0
    checked_count = 0
    async for run in cursor:
        checked_count += 1
        trial_end = run.get("trial_end_at")
        if not trial_end:
            continue
        try:
            d = datetime.fromisoformat(str(trial_end).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if d < now:
            await db.bot_runs.update_one(
                {"_id": run["_id"]},
                {"$set": {
                    "stopped_at": _now_iso(),
                    "exit_reason": "trial_expired",
                }},
            )
            stopped_count += 1
            log.info("trial expired for user=%s run=%s",
                     run.get("user_id"), str(run["_id"]))
    return {"checked": checked_count, "stopped": stopped_count}


async def ensure_indexes(db) -> None:
    if db is None:
        return
    try:
        await db.bot_runs.create_index([("user_id", 1), ("stopped_at", 1)])
        await db.bot_runs.create_index("trial_end_at")
        await db.bot_runs.create_index("started_at")
    except Exception as exc:
        log.warning("bot_runs indexes failed: %s", exc)


# ─────────────────────────── admin actions ───────────────────────────

async def admin_force_stop(db, user_id: str) -> dict:
    """Admin force stop a un user — usa el mismo path pero con reason
    distinta para audit."""
    return await stop_bot(db, user_id, reason="admin_force_stop")


async def admin_extend_trial(db, user_id: str, *, days: int = 30) -> dict:
    """Admin manual de payment: setea ``user.paid_until = now + days``.
    Si el user tiene un run activo, también actualiza ``trial_end_at``."""
    if db is None:
        return {"ok": False, "reason": "DB_UNAVAILABLE"}
    if days <= 0:
        return {"ok": False, "reason": "BAD_DAYS"}
    new_paid = (_now() + timedelta(days=days)).isoformat()
    await db.users.update_one(
        {"_id": user_id},
        {"$set": {"paid_until": new_paid}},
    )
    # Si tiene run activo, extender también el trial_end_at
    running = await active_run(db, user_id)
    if running:
        await db.bot_runs.update_one(
            {"_id": running["_id"]},
            {"$set": {"trial_end_at": new_paid, "is_paid": True}},
        )
    return {"ok": True, "paid_until": new_paid}
