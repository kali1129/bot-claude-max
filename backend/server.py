"""Futures Trading Plan Dashboard — FastAPI backend.

Single-process API for the operations center: serves the static plan content,
the architecture docs, the trade journal, the daily checklist, the risk
calculator, and the live discipline-adherence score. The trade journal is
read-mostly: write endpoints expect an idempotency key (``client_id``) so the
MT5 sync poller can retry safely without duplicating records.
"""
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional
import json
import logging
import os
import sys
import secrets
import uuid

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.middleware.cors import CORSMiddleware

# CRÍTICO: load_dotenv ANTES de importar `auth` o cualquier módulo que lea
# env vars al import time. Antes auth.py leía JWT_SECRET / DASHBOARD_TOKEN
# en módulo-load → quedaban en None porque .env aún no estaba cargado.
ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

import auth as auth_mod  # noqa: E402  (relativa al WORKINGDIR del backend)
import broker_manager  # noqa: E402
import bot_supervisor  # noqa: E402
import crypto_box  # noqa: E402
import process_supervisor  # noqa: E402
import wine_prefix_manager  # noqa: E402

from plan_content import (
    CAPITAL,
    CHECKLIST_TEMPLATE,
    MAX_CONSECUTIVE_LOSSES,
    MAX_DAILY_LOSS_PCT,
    MAX_RISK_PER_TRADE_PCT,
    MCPS,
    MIN_RR,
    MINDSET_PRINCIPLES,
    SETUP_GUIDE,
    STRATEGIES,
    STRICT_RULES,
    build_markdown,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
log = logging.getLogger("trading-dashboard")


# ============ APP STATE ============

class _State:
    mongo_client: Optional[AsyncIOMotorClient] = None
    db = None


state = _State()


def get_db():
    """Resolve the active Mongo database. Tests override via ``app.dependency_overrides``."""
    if state.db is None:
        raise RuntimeError("database not initialised — lifespan did not run")
    return state.db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME", "trading_dashboard")
    if not mongo_url:
        log.warning("MONGO_URL not set — running without DB (tests should override get_db)")
    else:
        state.mongo_client = AsyncIOMotorClient(mongo_url)
        state.db = state.mongo_client[db_name]
        await state.db.trades.create_index("id", unique=True)
        await state.db.trades.create_index("client_id", unique=True, sparse=True)
        await state.db.checklists.create_index("date", unique=True)
        # FASE 1: bootstrap admin + crear índice unique en users.email
        await auth_mod.ensure_users_collection(state.db)
        await broker_manager.ensure_indexes(state.db)
        await bot_supervisor.ensure_indexes(state.db)
        log.info("connected to mongo db=%s", db_name)
    # FASE 3: re-attach a procesos huerfanos del backend anterior. Los
    # procesos auto_trader.py per-user que sobrevivieron al reinicio del
    # backend siguen corriendo (start_new_session). Limpiamos PID file
    # de los muertos y dejamos vivos los activos.
    try:
        reattach = process_supervisor.reattach_on_startup()
        log.info("process supervisor reattach: alive=%d dead=%d",
                 len(reattach.get("alive", [])),
                 len(reattach.get("dead", [])))
        # Para los que murieron, marcamos sus runs como crashed
        if state.db is not None and reattach.get("dead"):
            for d in reattach["dead"]:
                await bot_supervisor.reconcile_processes(state.db)
                break  # reconcile recorre todo, una llamada basta
    except Exception as exc:
        log.warning("reattach failed: %s", exc)

    # Background trial checker — cada 60s revisa si algún user-bot expiró
    # las 24h de trial y lo detiene automáticamente. También reconcilia
    # procesos muertos (si crashearon, marca el run como crashed).
    _start_trial_checker()
    _start_process_reconciler()
    # Background equity sampler — persiste samples cada N segundos para que
    # el chart del dashboard sobreviva refresh / cierre de tab. Sin esto, el
    # chart arrancaba desde cero en cada visita.
    _start_equity_sampler()
    yield
    _stop_trial_checker()
    _stop_process_reconciler()
    _stop_equity_sampler()
    if state.mongo_client is not None:
        state.mongo_client.close()
        log.info("mongo connection closed")


# ─────────────────────────── trial checker (asyncio bg task) ──────────────

import asyncio  # noqa: E402

_trial_task = None


def _start_trial_checker():
    global _trial_task
    if _trial_task is not None and not _trial_task.done():
        return

    async def _loop():
        while True:
            try:
                if state.db is not None:
                    await bot_supervisor.check_expired_trials(state.db)
            except Exception as exc:  # noqa: BLE001
                log.warning("trial_checker iteration failed: %s", exc)
            await asyncio.sleep(60)

    try:
        _trial_task = asyncio.create_task(_loop())
        log.info("trial checker started (interval=60s)")
    except Exception as exc:
        log.warning("failed to start trial checker: %s", exc)


def _stop_trial_checker():
    global _trial_task
    if _trial_task is not None:
        try:
            _trial_task.cancel()
        except Exception:
            pass
        _trial_task = None


# Reconciler: cada 90s revisa procesos vivos vs runs activos en Mongo.
# Si un proceso murió pero el run sigue activo, marca crashed.
_reconciler_task = None


def _start_process_reconciler():
    global _reconciler_task
    if _reconciler_task is not None and not _reconciler_task.done():
        return

    async def _loop():
        while True:
            try:
                if state.db is not None:
                    await bot_supervisor.reconcile_processes(state.db)
            except Exception as exc:  # noqa: BLE001
                log.warning("reconciler iteration failed: %s", exc)
            await asyncio.sleep(90)

    try:
        _reconciler_task = asyncio.create_task(_loop())
        log.info("process reconciler started (interval=90s)")
    except Exception as exc:
        log.warning("failed to start process reconciler: %s", exc)


def _stop_process_reconciler():
    global _reconciler_task
    if _reconciler_task is not None:
        try:
            _reconciler_task.cancel()
        except Exception:
            pass
        _reconciler_task = None


# ─────────────────────────── equity sampler thread ───────────────────────────

_sampler_thread = None


def _read_balance_for_sampler():
    """Callback para el SamplerThread: retorna (balance, equity) live de MT5,
    o None si no hay conexión / cuenta no inicializada."""
    try:
        bal, source = _live_balance(fallback=_capital_fallback())
        if source != "mt5":
            return None     # no muestreamos durante fallback (sin MT5 real)
        # equity = balance + unrealized_pnl si está disponible
        try:
            import mt5_bridge
            info = mt5_bridge.status()
            if info.get("connected") and info.get("account"):
                eq = info["account"].get("equity")
                if isinstance(eq, (int, float)):
                    return (float(bal), float(eq))
        except Exception:
            pass
        return (float(bal), float(bal))
    except Exception:
        return None


def _start_equity_sampler():
    global _sampler_thread
    if not _SHARED_AVAILABLE or _equity_sampler_mod is None:
        log.warning("equity_sampler not available — chart will be ephemeral")
        return
    if _sampler_thread is not None and _sampler_thread.is_alive():
        return
    try:
        _sampler_thread = _equity_sampler_mod.SamplerThread(
            read_callback=_read_balance_for_sampler,
            interval_sec=int(os.environ.get("EQUITY_SAMPLE_INTERVAL_SEC", "30")),
        )
        _sampler_thread.start()
        log.info("equity_sampler thread started (interval=%ds)",
                 _sampler_thread.interval)
    except Exception as exc:
        log.warning("failed to start equity_sampler: %s", exc)


def _stop_equity_sampler():
    global _sampler_thread
    if _sampler_thread is not None:
        try:
            _sampler_thread.stop()
        except Exception:
            pass
        _sampler_thread = None


app = FastAPI(title="Futures Trading Plan Dashboard", lifespan=lifespan)


# Reescribir validation errors de Pydantic (default 422) a 400 para matchear
# el contrato API documentado. El payload mantiene el detail estructurado
# de FastAPI con los campos que fallaron.
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request, exc):
    return JSONResponse(
        status_code=400,
        content={"detail": exc.errors(), "body": exc.body},
    )


api_router = APIRouter(prefix="/api")


# ============ AUTH ============
# Single-tenant local dashboard: optional bearer token on write endpoints.
# Set DASHBOARD_TOKEN in .env to enable. Empty/unset → auth disabled (dev mode).

DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "").strip()


# require_token: ALIAS LEGACY hacia auth.require_admin.
# Hasta esta versión, los 31 endpoints write usaban un solo token compartido
# (DASHBOARD_TOKEN en el bundle). Ahora aceptamos:
#   1. JWT con role=admin (login en el dashboard)
#   2. Bearer DASHBOARD_TOKEN (legacy — para sync_loop, telegram_notifier, etc.)
# El "require_admin" en `auth.py` maneja ambos. Mantenemos el nombre
# para no tener que cambiar 31 endpoints.
def require_token(authorization: Optional[str] = Header(default=None)):
    return auth_mod.require_admin(authorization)


def require_user_auth(authorization: Optional[str] = Header(default=None)):
    """Alias para endpoints que aceptan cualquier usuario autenticado."""
    return auth_mod.require_user(authorization)


# ============ MODELS ============

TradeStatus = Literal["open", "closed-win", "closed-loss", "closed-be"]


class TradeBase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    strategy: str = Field(min_length=1, max_length=64)
    entry: float = Field(gt=0)
    exit: Optional[float] = Field(default=None, gt=0)
    sl: float = Field(gt=0)
    tp: Optional[float] = Field(default=None, gt=0)
    lots: float = Field(gt=0, le=10)
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    status: TradeStatus = "open"
    notes: str = Field(default="", max_length=2000)


class TradeEntry(TradeBase):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_id: Optional[str] = None
    source: Literal["manual", "mt5-sync"] = "manual"
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TradeEntryCreate(TradeBase):
    client_id: Optional[str] = Field(default=None, max_length=64)
    source: Literal["manual", "mt5-sync"] = "manual"


class ChecklistState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    checked_ids: List[str] = []
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ChecklistUpdate(BaseModel):
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    checked_ids: List[str]


class RiskCalcInput(BaseModel):
    balance: float = Field(gt=0, le=10_000_000)
    risk_pct: float = Field(gt=0, le=100)
    entry: float = Field(gt=0)
    stop_loss: float = Field(gt=0)
    pip_value: float = Field(default=10.0, gt=0)
    pip_size: float = Field(default=0.0001, gt=0)
    lot_step: float = Field(default=0.01, gt=0)
    min_lot: float = Field(default=0.01, gt=0)
    max_lot: float = Field(default=0.5, gt=0)

    @model_validator(mode="after")
    def _validate(self):
        if self.entry == self.stop_loss:
            raise ValueError("entry y stop_loss no pueden ser iguales")
        if self.min_lot > self.max_lot:
            raise ValueError("min_lot > max_lot")
        return self


# ============ ENDPOINTS ============

def _resolve_capital() -> tuple[float, str]:
    """Same logic as _live_balance — exposed at module scope for /plan/data."""
    return _live_balance(fallback=_capital_fallback())


@api_router.get("/")
async def root():
    bal, source = _resolve_capital()
    return {"message": "Trading Plan API", "capital": bal, "capital_source": source}


@api_router.get("/health")
async def health():
    db_ok = state.db is not None
    return {"ok": True, "db": db_ok, "auth": bool(DASHBOARD_TOKEN)}


# ─────────────────────────── /api/auth/* ───────────────────────────
# Sistema multi-usuario: register/login con JWT. Reemplaza el modelo
# anterior de un solo `DASHBOARD_TOKEN` compartido en el bundle.
# Endpoints públicos read-only siguen sin auth; los writes requieren
# role=admin (Fase 1) o el legacy DASHBOARD_TOKEN.

@api_router.post("/auth/register")
async def auth_register(payload: auth_mod.RegisterPayload, db=Depends(get_db)):
    """Crea un usuario nuevo (role=user). En Fase 1 estos usuarios pueden
    LEER pero no modificar el bot — sus mods llegan en Fase 2 (per-user
    bot con su propio MT5)."""
    res = await auth_mod.register_handler(payload, db)
    return res.model_dump()


@api_router.post("/auth/login")
async def auth_login(payload: auth_mod.LoginPayload, db=Depends(get_db)):
    res = await auth_mod.login_handler(payload, db)
    return res.model_dump()


@api_router.get("/auth/me")
async def auth_me(
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    return await auth_mod.me_handler(current, db)


@api_router.post("/auth/logout")
async def auth_logout():
    """Stateless logout — el cliente solo borra el JWT de localStorage.
    Devolvemos OK siempre. Para revocación real necesitaríamos lista negra
    de tokens (nice to have, no crítico)."""
    return {"ok": True}


@api_router.get("/auth/info")
async def auth_info(
    current=Depends(auth_mod.require_auth_optional),
):
    """Endpoint que SIEMPRE responde 200 (no requiere auth) — devuelve
    si el caller está autenticado y su role. Útil para que el frontend
    sepa qué mostrar (login vs dashboard) sin tener que hacer try/catch
    sobre /me."""
    if current is None:
        return {"authenticated": False, "role": None, "is_admin": False}
    return {
        "authenticated": True,
        "user_id": current.id,
        "email": current.email,
        "role": current.role,
        "is_admin": current.is_admin,
        "legacy_token": current.legacy_admin,
    }


# ─────────────────────────── /api/admin/* ───────────────────────────
# Panel de administración. SOLO accesible con role=admin (o legacy token).
# Permite listar usuarios, ver detalles, modificar roles, banear, etc.
# En FASE 2 también verá: cuenta MT5 conectada por user, su bot status,
# sus trades, sus configs.

def _is_admin_systemd_running() -> bool:
    """Detecta si el bot global del admin (systemd service
    ``trading-auto-trader``) está activo. Esto NO usa bot_runs porque el
    bot del admin no usa el supervisor per-user — corre como service.

    Estrategia: chequear si hay algún proceso ``auto_trader.py`` corriendo
    con un parent que NO sea uno de nuestros children registrados (porque
    los children registrados son user-bots). Como heurística más simple
    y robusta, vemos si systemd reporta active.
    """
    import subprocess
    try:
        res = subprocess.run(
            ["systemctl", "is-active", "trading-auto-trader"],
            capture_output=True, text=True, timeout=2,
        )
        return res.stdout.strip() == "active"
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        # systemctl no disponible (Windows dev) — fallback: ver si hay
        # auto_trader.py en la lista de procesos del supervisor
        return False


@api_router.get("/admin/users")
async def admin_list_users(
    _admin=Depends(auth_mod.require_admin),
    db=Depends(get_db),
):
    """Lista usuarios + broker connected + bot running + trial info.
    Versión enriquecida multi-cuenta — el frontend muestra todo en tabla.

    Nuevo: campo ``broker_accounts`` array con todas las cuentas (demo+real
    si las dos). Mantenemos campos legacy ``broker_login`` etc. apuntando
    a la cuenta ACTIVA para compat con UIs viejos.
    """
    if db is None:
        raise HTTPException(503, "DB no disponible")
    cursor = db.users.find({}, {"password_hash": 0}).sort("created_at", -1)
    users = await cursor.to_list(length=10_000)
    admin_systemd_running = _is_admin_systemd_running()
    out = []
    for u in users:
        uid = str(u.pop("_id", u.get("id", "")))
        u["id"] = uid
        is_admin = u.get("role") == "admin"
        # Enrich con broker (lista) + bot
        accounts = await broker_manager.list_creds(db, uid)
        active = next((a for a in accounts if a.get("is_active")), None)
        bot = await bot_supervisor.status(db, uid)

        u["broker_accounts"] = accounts            # nuevo: lista completa
        u["broker_connected"] = len(accounts) > 0
        u["broker_count"] = len(accounts)
        # Legacy fields apuntan a la activa para que UIs viejos no rompan
        u["broker_demo"] = active.get("is_demo") if active else None
        u["broker_login"] = active.get("mt5_login") if active else None
        u["broker_server"] = active.get("mt5_server") if active else None
        u["broker_active_is_demo"] = (
            active.get("is_demo") if active else None
        )
        # bot_running: para admin, mirar systemd (no bot_runs)
        if is_admin:
            u["bot_running"] = admin_systemd_running
            u["bot_systemd"] = True   # señal al UI: este bot es global
        else:
            u["bot_running"] = bool(bot.get("running"))
            u["bot_systemd"] = False
        u["trial_seconds_remaining"] = bot.get("trial_seconds_remaining")
        u["trial_expired"] = bool(bot.get("trial_expired"))
        out.append(u)
    return {
        "ok": True,
        "count": len(out),
        "users": out,
        "admin_systemd_running": admin_systemd_running,
    }


@api_router.get("/admin/users/{user_id}")
async def admin_get_user(
    user_id: str,
    _admin=Depends(auth_mod.require_admin),
    db=Depends(get_db),
):
    """Detalle de un usuario + broker (multi-cuenta) + bot status + trial."""
    if db is None:
        raise HTTPException(503, "DB no disponible")
    user = await db.users.find_one({"_id": user_id}, {"password_hash": 0})
    if not user:
        raise HTTPException(404, "usuario no existe")
    user["id"] = str(user.pop("_id"))

    accounts = await broker_manager.list_creds(db, user_id)
    active = next((a for a in accounts if a.get("is_active")), None)
    bot = await bot_supervisor.status(db, user_id)

    # Trades count (placeholder hasta FASE 3 — MT5 real per user)
    trades_count = await db.trades.count_documents({"user_id": user_id})

    # Para admin, override running con systemd
    is_admin = user.get("role") == "admin"
    if is_admin:
        bot["running_systemd"] = _is_admin_systemd_running()

    return {
        "ok": True,
        "user": user,
        "broker_accounts": accounts,       # lista (puede tener 0,1,2)
        "broker_active": active,           # la que el bot usaría
        "broker": active,                  # legacy alias
        "bot": bot,                        # running/last_run/trial info
        "trades_count": trades_count,
    }


class AdminUserUpdatePayload(BaseModel):
    """Solo permite cambiar role y display_name por ahora.
    Email/password se manejan por el usuario en FASE 2."""
    role: Optional[Literal["admin", "user"]] = None
    display_name: Optional[str] = Field(default=None, max_length=64)


@api_router.patch("/admin/users/{user_id}",
                   dependencies=[Depends(auth_mod.require_admin)])
async def admin_update_user(
    user_id: str,
    payload: AdminUserUpdatePayload,
    db=Depends(get_db),
):
    """Modifica role o display_name de un usuario. NO permite cambiar
    email ni password — eso es responsabilidad del usuario."""
    if db is None:
        raise HTTPException(503, "DB no disponible")
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    if not updates:
        raise HTTPException(400, "nada para actualizar")
    res = await db.users.update_one({"_id": user_id}, {"$set": updates})
    if res.matched_count == 0:
        raise HTTPException(404, "usuario no existe")
    user = await db.users.find_one({"_id": user_id}, {"password_hash": 0})
    user["id"] = str(user.pop("_id"))
    return {"ok": True, "user": user}


@api_router.delete("/admin/users/{user_id}",
                    dependencies=[Depends(auth_mod.require_admin)])
async def admin_delete_user(
    user_id: str,
    db=Depends(get_db),
):
    """Elimina un usuario completamente: cuenta + broker creds + bot run +
    Wine prefix + state + logs. NO se puede eliminar al último admin."""
    if db is None:
        raise HTTPException(503, "DB no disponible")
    user = await db.users.find_one({"_id": user_id})
    if not user:
        raise HTTPException(404, "usuario no existe")
    if user.get("role") == "admin":
        admin_count = await db.users.count_documents({"role": "admin"})
        if admin_count <= 1:
            raise HTTPException(409,
                "no podés eliminar el último admin del sistema")

    # 1. Si bot está corriendo, killearlo primero
    try:
        await bot_supervisor.stop_bot(db, user_id, reason="user_deleted")
    except Exception as exc:
        log.warning("stop_bot during delete failed for %s: %s", user_id, exc)

    # 2. Borrar credenciales broker (cifradas)
    try:
        await broker_manager.delete_creds(db, user_id)
    except Exception as exc:
        log.warning("delete_creds failed for %s: %s", user_id, exc)

    # 3. Borrar Wine prefix + state + logs (filesystem cleanup)
    try:
        cleanup = wine_prefix_manager.delete_user_prefix(user_id, keep_logs=False)
        log.info("filesystem cleanup for %s: %s", user_id, cleanup)
    except Exception as exc:
        log.warning("prefix cleanup failed for %s: %s", user_id, exc)

    # 4. Borrar el usuario y sus runs
    await db.bot_runs.delete_many({"user_id": user_id})
    await db.users.delete_one({"_id": user_id})

    return {"ok": True, "deleted_id": user_id}


# ─────────────────────────── /api/users/me/broker ───────────────────────
# FASE 2 (multi-cuenta): cada usuario puede conectar UNA cuenta DEMO + UNA
# cuenta REAL al mismo tiempo. Solo UNA es la "activa" — la que el bot usa.
# Las credenciales se cifran con AES-GCM antes de persistir. El password
# en plain NUNCA viaja al cliente — solo nuestro proceso server lo descifra
# al iniciar la conexión MT5.

class BrokerCredsPayload(BaseModel):
    mt5_login: int = Field(gt=0, lt=10**12)
    mt5_password: str = Field(min_length=4, max_length=128)
    mt5_server: str = Field(min_length=2, max_length=100)
    mt5_path: Optional[str] = Field(default=None, max_length=500)
    is_demo: bool = True


class BrokerTestPayload(BrokerCredsPayload):
    """Mismo shape pero el endpoint /test no persiste."""


class BrokerSwitchPayload(BaseModel):
    """Switch entre la cuenta DEMO y la REAL del usuario."""
    is_demo: bool
    confirm_real: bool = False  # requerido si is_demo=False (pasar a real)


@api_router.get("/users/me/broker")
async def get_my_broker(
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    """Retorna lista de cuentas conectadas (demo + real si las dos), con
    indicador de cuál está activa.

    Schema de respuesta:
      {
        "ok": True,
        "has_creds": bool,
        "accounts": [{...demo...}, {...real...}],  # 0, 1 o 2 elementos
        "active": {...la que el bot usa...} | None
      }
    """
    accounts = await broker_manager.list_creds(db, current.id)
    active = await broker_manager.get_active_creds(db, current.id)
    return {
        "ok": True,
        "has_creds": len(accounts) > 0,
        "accounts": accounts,
        "active": active,
    }


@api_router.post("/users/me/broker")
async def post_my_broker(
    payload: BrokerCredsPayload,
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    """Guarda/actualiza la cuenta MT5 del tipo (demo|real) indicado en
    ``is_demo``. Encripta password.

    - Si el usuario aún no tiene NINGUNA cuenta: ésta queda activa.
    - Si ya tiene OTRA cuenta activa: ésta queda inactiva (el usuario
      tiene que llamar /switch explícitamente para activarla).
    - Si ya existe cuenta del MISMO tipo (mismo is_demo): la sobreescribe.
    """
    if current.legacy_admin:
        # Legacy DASHBOARD_TOKEN no tiene user_id de verdad
        raise HTTPException(400, "usá un JWT con login real para conectar broker")
    saved = await broker_manager.save_creds(
        db, current.id,
        mt5_login=payload.mt5_login,
        mt5_password=payload.mt5_password,
        mt5_server=payload.mt5_server,
        mt5_path=payload.mt5_path,
        is_demo=payload.is_demo,
        set_active=True,  # solo aplica si no había ninguna activa
    )
    return {"ok": True, "account": saved}


@api_router.post("/users/me/broker/switch")
async def switch_my_broker(
    payload: BrokerSwitchPayload,
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    """Cambia cuál cuenta usa el bot (demo ↔ real).

    Si pasa a REAL, requiere ``confirm_real=True`` como protección extra
    (el frontend ya muestra modal — esto es la última red).

    Si el bot estaba corriendo con la otra cuenta, lo detiene y arranca
    con la nueva. El usuario ve transición limpia: no quedan trades de
    la cuenta vieja en la nueva.
    """
    if current.legacy_admin:
        raise HTTPException(400, "usá un JWT con login real")

    # Validación: si pasa a REAL, exigir confirmación explícita
    if not payload.is_demo and not payload.confirm_real:
        raise HTTPException(
            400,
            "Para activar la cuenta REAL tenés que confirmar el riesgo. "
            "Volvé al modal y tickeá 'entiendo que opero con dinero real'."
        )

    # ¿Existe la cuenta del tipo solicitado?
    target = await broker_manager.get_creds(db, current.id, is_demo=payload.is_demo)
    if not target:
        kind = "demo" if payload.is_demo else "real"
        raise HTTPException(
            404,
            f"No tenés cuenta {kind.upper()} conectada. Conectala primero "
            "en Mi Cuenta → Conectar broker."
        )

    # ¿Ya estaba activa? No-op
    if target.get("is_active"):
        return {
            "ok": True,
            "no_op": True,
            "active": target,
            "detail": "esa cuenta ya estaba activa",
        }

    # Detect: ¿el bot estaba corriendo? Si sí, hay que reiniciarlo
    bot_state = await bot_supervisor.status(db, current.id)
    was_running = bool(bot_state.get("running"))

    # Stop bot si corría con la cuenta vieja
    if was_running:
        await bot_supervisor.stop_bot(
            db, current.id, reason="broker_switch"
        )

    # Switch
    new_active = await broker_manager.set_active(
        db, current.id, is_demo=payload.is_demo
    )

    # Re-arranque del bot con la nueva cuenta (si estaba running)
    restart_result = None
    if was_running:
        restart_result = await bot_supervisor.start_bot(db, current.id)

    return {
        "ok": True,
        "active": new_active,
        "was_running": was_running,
        "restarted": bool(restart_result and restart_result.get("ok")),
        "restart_error": (
            restart_result.get("detail")
            if restart_result and not restart_result.get("ok")
            else None
        ),
        "detail": (
            f"Activada cuenta {'DEMO' if payload.is_demo else 'REAL'}. "
            + ("Bot reiniciado con la nueva cuenta." if was_running else
               "Bot estaba detenido — andá a la sección del bot para arrancarlo.")
        ),
    }


@api_router.delete("/users/me/broker")
async def delete_my_broker(
    is_demo: Optional[bool] = None,
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    """Elimina una cuenta específica (?is_demo=true|false) o todas las
    cuentas del usuario (sin query param).

    Si la cuenta borrada era la activa y queda otra, el supervisor de
    broker_manager auto-promueve la otra a activa. Si no queda ninguna,
    el bot queda sin creds y un próximo /bot/start fallaría con NO_BROKER.

    Si el bot está corriendo con la cuenta que estamos borrando, lo
    detiene primero.
    """
    # Detect si la cuenta a borrar es la activa (para decidir si parar bot)
    active = await broker_manager.get_active_creds(db, current.id)
    is_active_being_deleted = (
        active is not None and (
            is_demo is None or  # borra todo
            bool(active.get("is_demo")) == bool(is_demo)
        )
    )
    if is_active_being_deleted:
        await bot_supervisor.stop_bot(
            db, current.id, reason="broker_disconnected"
        )

    deleted = await broker_manager.delete_creds(db, current.id, is_demo=is_demo)
    return {"ok": True, **deleted}


@api_router.post("/users/me/broker/test")
async def test_my_broker(
    payload: BrokerTestPayload,
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    """Test connection (sin guardar). Persiste el resultado del test
    contra la cuenta del tipo (is_demo) si ya está guardada."""
    res = await broker_manager.test_connection_live(
        mt5_login=payload.mt5_login,
        mt5_password=payload.mt5_password,
        mt5_server=payload.mt5_server,
        mt5_path=payload.mt5_path,
    )
    # Si user ya tiene la cuenta del mismo tipo guardada, persiste el resultado
    existing = await broker_manager.get_creds(
        db, current.id, is_demo=payload.is_demo
    )
    if existing:
        await broker_manager.record_test_result(
            db, current.id,
            is_demo=payload.is_demo,
            ok=bool(res.get("ok")),
            error=res.get("error"),
        )
    return res


# ─────────────────────────── /api/users/me/bot ───────────────────────
# Lifecycle del bot per-user. Slot cap + trial 24h + admin exempt.

@api_router.get("/users/me/bot")
async def get_my_bot(
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    return await bot_supervisor.status(db, current.id)


@api_router.post("/users/me/bot/start")
async def start_my_bot(
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    if current.legacy_admin:
        raise HTTPException(400, "usá un JWT con login real para arrancar bot")
    res = await bot_supervisor.start_bot(db, current.id)
    if not res.get("ok"):
        # Mapeo a HTTP code según reason
        reason = res.get("reason", "")
        if reason == "ALREADY_RUNNING":
            raise HTTPException(409, res.get("detail") or "ya está corriendo")
        if reason == "NO_BROKER":
            raise HTTPException(412, res.get("detail") or "conectá tu broker primero")
        if reason == "SLOTS_FULL":
            raise HTTPException(503, res.get("detail") or "slots llenos")
        raise HTTPException(400, res.get("detail") or reason)
    return res


@api_router.post("/users/me/bot/stop")
async def stop_my_bot(
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    if current.legacy_admin:
        raise HTTPException(400, "usá un JWT con login real")
    res = await bot_supervisor.stop_bot(db, current.id, reason="user_stop")
    if not res.get("ok"):
        raise HTTPException(404, res.get("detail") or "no estaba corriendo")
    return res


@api_router.get("/users/me/bot/slots")
async def my_bot_slots(
    current=Depends(auth_mod.require_user),
    db=Depends(get_db),
):
    """Info global de slots para mostrar en el banner: cuántos hay activos
    y cuántos quedan disponibles. Cualquier usuario lo puede consultar."""
    return await bot_supervisor.slot_info(db)


@api_router.get("/users/me/bot/logs")
async def my_bot_logs(
    lines: int = 100,
    which: str = "stdout",
    current=Depends(auth_mod.require_user),
):
    """Tail de los logs del bot del usuario. ``which`` ∈ {stdout, stderr}."""
    if current.legacy_admin:
        return {"ok": False, "reason": "legacy", "logs": ""}
    lines = max(10, min(1000, int(lines)))
    if which not in ("stdout", "stderr"):
        which = "stdout"
    text = process_supervisor.tail_log(current.id, lines=lines, which=which)
    return {
        "ok": True,
        "lines": lines,
        "which": which,
        "is_running": process_supervisor.is_running(current.id),
        "pid": process_supervisor.get_pid(current.id),
        "logs": text,
    }


# ─────────────────────────── /api/admin/wine-template ───────────────────

@api_router.get("/admin/wine-template")
async def admin_wine_template_status(
    _admin=Depends(auth_mod.require_admin),
):
    """Estado del Wine prefix template: existe, tamaño, has Python/MT5."""
    return {
        "ok": True,
        "template": wine_prefix_manager.template_health(),
        "stats": wine_prefix_manager.stats(),
        "running_processes": process_supervisor.list_running(),
    }


# ─────────────────────────── /api/admin/* enriquecidos ───────────────

@api_router.get("/admin/stats")
async def admin_stats(
    _admin=Depends(auth_mod.require_admin),
    db=Depends(get_db),
):
    """Stats agregadas: users, admins, registros recientes, slots, trades."""
    if db is None:
        raise HTTPException(503, "DB no disponible")
    total_users = await db.users.count_documents({})
    admins = await db.users.count_documents({"role": "admin"})
    users = await db.users.count_documents({"role": "user"})
    from datetime import timedelta as _td
    cutoff = (datetime.now(timezone.utc) - _td(days=7)).isoformat()
    recent = await db.users.count_documents({"created_at": {"$gte": cutoff}})
    slots = await bot_supervisor.slot_info(db)
    return {
        "ok": True,
        "users": {
            "total": total_users,
            "admins": admins,
            "regular": users,
            "registered_last_7d": recent,
        },
        "slots": slots,
        "trades": {
            "total": await db.trades.count_documents({}),
        },
    }


# ─────────────────────────── admin actions on user ────────────────────

class AdminExtendTrialPayload(BaseModel):
    days: int = Field(gt=0, le=365)


@api_router.post(
    "/admin/users/{user_id}/extend-trial",
    dependencies=[Depends(auth_mod.require_admin)],
)
async def admin_extend_trial_endpoint(
    user_id: str,
    payload: AdminExtendTrialPayload,
    db=Depends(get_db),
):
    """Extiende el trial de un usuario por N días. Equivalente a "marca
    como pagado hasta now+N días". Hasta que haya integración Stripe
    real (FASE 4), esto es la única forma de extender."""
    res = await bot_supervisor.admin_extend_trial(db, user_id, days=payload.days)
    if not res.get("ok"):
        raise HTTPException(400, res.get("reason", "error"))
    return res


@api_router.post(
    "/admin/users/{user_id}/force-stop-bot",
    dependencies=[Depends(auth_mod.require_admin)],
)
async def admin_force_stop_endpoint(
    user_id: str,
    db=Depends(get_db),
):
    """Force stop del bot de un usuario. El run queda registrado con
    exit_reason=admin_force_stop."""
    res = await bot_supervisor.admin_force_stop(db, user_id)
    if not res.get("ok"):
        raise HTTPException(404, res.get("detail", "no estaba corriendo"))
    return res


# ───────────────────────── capital ledger ─────────────────────────
# Importa los módulos compartidos. Si falla (ej. en tests), endpoints
# devuelven 503.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent /
                           "mcp-scaffolds" / "_shared"))
    from common import capital_ledger as _capital_ledger_mod
    from common import expectancy_tracker as _expectancy_mod
    from common import regime as _regime_mod
    from common import user_settings as _user_settings_mod
    from common import equity_sampler as _equity_sampler_mod
    _SHARED_AVAILABLE = True
except ImportError as exc:
    log.warning("shared modules not importable: %s", exc)
    _capital_ledger_mod = None  # type: ignore
    _expectancy_mod = None  # type: ignore
    _regime_mod = None  # type: ignore
    _user_settings_mod = None  # type: ignore
    _equity_sampler_mod = None  # type: ignore
    _SHARED_AVAILABLE = False


@api_router.get("/capital")
async def get_capital():
    """Snapshot del capital ledger + meta del usuario.

    El ``target_capital_usd`` se lee primero de ``user_settings.goal_usd``
    (la meta que el usuario configuró). Si no hay setting, fallback al
    valor del ledger (default 800 del env TARGET_CAPITAL_USD).
    """
    if not _SHARED_AVAILABLE or _capital_ledger_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE"}
    try:
        bal, source = _live_balance(fallback=_capital_fallback())
        m = _capital_ledger_mod.metrics(current_balance=bal)
        # Override target_capital con el goal del usuario si lo configuró
        if _user_settings_mod is not None:
            try:
                user_goal = _user_settings_mod.get_goal_usd()
                if user_goal is not None and user_goal > 0:
                    m["target_capital_usd"] = round(float(user_goal), 2)
                    # Recalcular pl_target_remaining_usd con el nuevo target
                    cur = m.get("current_balance_usd") or 0.0
                    m["pl_target_remaining_usd"] = round(
                        m["target_capital_usd"] - cur, 2
                    )
            except Exception:
                pass
        m["balance_source"] = source
        m["ok"] = True
        return m
    except Exception as exc:
        return {"ok": False, "reason": "LEDGER_ERROR", "detail": str(exc)}


class CapitalResetPayload(BaseModel):
    """Payload para POST /api/capital/reset — declara nuevo starting_balance."""
    starting_balance: float = Field(gt=0, le=10_000_000)
    note: str = Field(default="", max_length=200)


@api_router.post("/capital/reset", dependencies=[Depends(require_token)])
async def post_capital_reset(payload: CapitalResetPayload):
    """``/api/capital/reset`` — establece un nuevo punto de partida.

    Usar cuando recargás cuenta demo o después de un cashout en live.
    También archiva los equity samples viejos para que el chart arranque
    limpio desde el nuevo starting_balance."""
    if not _SHARED_AVAILABLE or _capital_ledger_mod is None:
        raise HTTPException(503, "shared modules not available")
    ledger = _capital_ledger_mod.reset(payload.starting_balance,
                                        note=payload.note or "via api")
    if _equity_sampler_mod is not None:
        try:
            _equity_sampler_mod.reset(archive=True)
        except Exception:
            pass
    return {"ok": True, "ledger": ledger}


class CapitalEventPayload(BaseModel):
    amount: float = Field(gt=0, le=10_000_000)
    note: str = Field(default="", max_length=200)


@api_router.post("/capital/deposit", dependencies=[Depends(require_token)])
async def post_capital_deposit(payload: CapitalEventPayload):
    if not _SHARED_AVAILABLE or _capital_ledger_mod is None:
        raise HTTPException(503, "shared modules not available")
    bal, _ = _live_balance(fallback=_capital_fallback())
    ledger = _capital_ledger_mod.record_deposit(payload.amount,
                                                  balance_after=bal,
                                                  note=payload.note or "via api")
    if _equity_sampler_mod is not None:
        try:
            _equity_sampler_mod.reset(archive=True)
        except Exception:
            pass
    return {"ok": True, "ledger": ledger}


@api_router.post("/capital/withdrawal", dependencies=[Depends(require_token)])
async def post_capital_withdrawal(payload: CapitalEventPayload):
    if not _SHARED_AVAILABLE or _capital_ledger_mod is None:
        raise HTTPException(503, "shared modules not available")
    bal, _ = _live_balance(fallback=_capital_fallback())
    ledger = _capital_ledger_mod.record_withdrawal(payload.amount,
                                                     balance_after=bal,
                                                     note=payload.note or "via api")
    if _equity_sampler_mod is not None:
        try:
            _equity_sampler_mod.reset(archive=True)
        except Exception:
            pass
    return {"ok": True, "ledger": ledger}


# ───────────────────────── equity samples ─────────────────────────

@api_router.get("/equity/samples")
async def get_equity_samples(hours: float = 24.0, max_n: int = 500):
    """Series temporal de equity persistida en disco.

    El chart del dashboard consume este endpoint al montarse para tener
    el histórico desde que el bot arrancó (no desde que el usuario abrió
    el browser). Frontend luego puede append-ear samples nuevas en memoria.

    Args:
      hours: ventana hacia atrás (default 24h, max 720h = 30 días).
      max_n: cap de samples retornadas (default 500). Si hay más se hace
        downsample uniforme.
    """
    if not _SHARED_AVAILABLE or _equity_sampler_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE", "samples": []}
    hours = max(0.0, min(720.0, float(hours)))
    max_n = max(10, min(5000, int(max_n)))
    samples = _equity_sampler_mod.get_samples(hours=hours, max_n=max_n)
    return {
        "ok": True,
        "samples": samples,
        "count": len(samples),
        "hours": hours,
        "max_n": max_n,
    }


@api_router.get("/equity/stats")
async def get_equity_stats():
    """Diagnóstico del sampler: file size, count, primer/último sample."""
    if not _SHARED_AVAILABLE or _equity_sampler_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE"}
    return {"ok": True, **_equity_sampler_mod.stats()}


@api_router.post("/equity/reset", dependencies=[Depends(require_token)])
async def post_equity_reset():
    """Limpia el archivo de samples (archiva el viejo). Útil para empezar
    chart limpio sin tener que hacer reset de balance."""
    if not _SHARED_AVAILABLE or _equity_sampler_mod is None:
        raise HTTPException(503, "shared modules not available")
    return _equity_sampler_mod.reset(archive=True)


# ───────────────────────── expectancy ─────────────────────────

@api_router.get("/expectancy")
async def get_expectancy(min_n: int = 0):
    """Lista combos (strategy:symbol) ordenados por expectancy descendente."""
    if not _SHARED_AVAILABLE or _expectancy_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE"}
    return {"ok": True, "combos": _expectancy_mod.list_combos(min_n=min_n)}


@api_router.get("/expectancy/edge")
async def get_expectancy_edge(strategy_id: str, symbol: str):
    """Verdict (PROVEN/UNCERTAIN/NEGATIVE) para un combo."""
    if not _SHARED_AVAILABLE or _expectancy_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE"}
    return {"ok": True, **_expectancy_mod.edge_status(strategy_id, symbol)}


@api_router.get("/expectancy/heatmap")
async def get_expectancy_heatmap(strategy_id: str, symbol: str):
    """Heatmap por hora UTC para un (strategy, symbol)."""
    if not _SHARED_AVAILABLE or _expectancy_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE"}
    return {"ok": True, "heatmap": _expectancy_mod.hour_heatmap(strategy_id, symbol)}


# ───────────────────────── user settings ─────────────────────────
# Mode (novato/experto) + goal + style + sessions + telegram + onboarding.
# Estos endpoints son la PUERTA del usuario para configurar el bot sin
# tocar archivos .env ni código. El frontend los consume desde el wizard
# de onboarding y desde la sección "Configuración".

@api_router.get("/settings")
async def get_settings():
    """Snapshot de settings + presets disponibles para el dashboard."""
    if not _SHARED_AVAILABLE or _user_settings_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE"}
    snap = _user_settings_mod.snapshot()
    snap["ok"] = True
    return snap


class UserSettingsPayload(BaseModel):
    """Payload completo o parcial de user settings."""
    model_config = ConfigDict(extra="allow")
    mode: Optional[Literal["novato", "experto"]] = None
    goal_usd: Optional[float] = Field(default=None, gt=0, le=10_000_000)
    style: Optional[Literal["conservativo", "balanceado", "agresivo"]] = None
    sessions: Optional[List[str]] = None
    telegram_chat_ids: Optional[List[int]] = None
    telegram_enabled: Optional[bool] = None


@api_router.put("/settings", dependencies=[Depends(require_token)])
async def put_settings(payload: UserSettingsPayload):
    """Actualiza settings (merge parcial — solo los campos provistos).

    Devuelve el SNAPSHOT completo (no solo la settings bare) para que el
    frontend pueda actualizar `active_style_preset` y `available_styles`
    sin un round-trip extra a GET. Sin esto, después de un PUT el contexto
    quedaba con presets indefinidos y la UI mostraba "— posición(es)" y
    cards sin valores en risk/RR/max_pos.
    """
    if not _SHARED_AVAILABLE or _user_settings_mod is None:
        raise HTTPException(503, "shared modules not available")
    current = _user_settings_mod.load()
    updates = payload.model_dump(exclude_unset=True, exclude_none=True)
    current.update(updates)
    try:
        _user_settings_mod.save(current)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "settings": _user_settings_mod.snapshot()}


@api_router.post("/settings/onboarding/complete",
                  dependencies=[Depends(require_token)])
async def post_onboarding_complete():
    """Marca el wizard como completado. Devuelve snapshot completo."""
    if not _SHARED_AVAILABLE or _user_settings_mod is None:
        raise HTTPException(503, "shared modules not available")
    _user_settings_mod.mark_onboarded()
    return {"ok": True, "settings": _user_settings_mod.snapshot()}


@api_router.get("/settings/styles")
async def get_styles():
    """Presets de estilo disponibles."""
    if not _SHARED_AVAILABLE or _user_settings_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE"}
    return {"ok": True, "styles": _user_settings_mod.list_styles()}


@api_router.get("/settings/sessions")
async def get_sessions():
    """Sesiones de mercado disponibles."""
    if not _SHARED_AVAILABLE or _user_settings_mod is None:
        return {"ok": False, "reason": "SHARED_NOT_AVAILABLE"}
    return {"ok": True, "sessions": _user_settings_mod.list_sessions()}


class TelegramChatPayload(BaseModel):
    chat_id: int


@api_router.post("/settings/telegram/add",
                  dependencies=[Depends(require_token)])
async def post_telegram_add(payload: TelegramChatPayload):
    if not _SHARED_AVAILABLE or _user_settings_mod is None:
        raise HTTPException(503, "shared modules not available")
    _user_settings_mod.add_telegram_chat(payload.chat_id)
    return {"ok": True, "settings": _user_settings_mod.snapshot()}


@api_router.post("/settings/telegram/remove",
                  dependencies=[Depends(require_token)])
async def post_telegram_remove(payload: TelegramChatPayload):
    if not _SHARED_AVAILABLE or _user_settings_mod is None:
        raise HTTPException(503, "shared modules not available")
    _user_settings_mod.remove_telegram_chat(payload.chat_id)
    return {"ok": True, "settings": _user_settings_mod.snapshot()}


@api_router.get("/plan/data")
async def get_plan_data():
    bal, source = _resolve_capital()
    return {
        "config": {
            "capital": bal,
            "capital_source": source,
            "capital_target": CAPITAL,  # the $800 target from plan_content
            "max_risk_per_trade_pct": MAX_RISK_PER_TRADE_PCT,
            "max_daily_loss_pct": MAX_DAILY_LOSS_PCT,
            "max_consecutive_losses": MAX_CONSECUTIVE_LOSSES,
            "min_rr": MIN_RR,
        },
        "mcps": MCPS,
        "strategies": STRATEGIES,
        "rules": STRICT_RULES,
        "checklist": CHECKLIST_TEMPLATE,
        "mindset": MINDSET_PRINCIPLES,
        "setup_guide": SETUP_GUIDE,
    }


@api_router.get("/plan/markdown", response_class=PlainTextResponse)
async def get_plan_markdown():
    return build_markdown()


# ----- Architecture docs (READMEs) -----

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

DOCS_META = [
    {"id": "00-overview", "file": "00-OVERVIEW.md", "title": "Arquitectura General", "kind": "overview", "order": 0},
    {"id": "01-mcp-news", "file": "01-MCP-NEWS.md", "title": "MCP de Noticias & Calendario", "kind": "mcp", "order": 1},
    {"id": "02-mcp-trading", "file": "02-MCP-TRADING.md", "title": "MCP de Trading (MT5)", "kind": "mcp", "order": 2},
    {"id": "03-mcp-analysis", "file": "03-MCP-ANALYSIS.md", "title": "MCP de Análisis Técnico", "kind": "mcp", "order": 3},
    {"id": "04-mcp-risk", "file": "04-MCP-RISK.md", "title": "MCP de Gestión de Riesgo", "kind": "mcp", "order": 4},
    {"id": "05-dashboard", "file": "05-DASHBOARD.md", "title": "Dashboard Web (este sitio)", "kind": "system", "order": 5},
    {"id": "06-setup", "file": "06-SETUP-WSL-MT5-CLAUDE.md", "title": "Setup completo WSL + MT5 + Claude", "kind": "guide", "order": 6},
    {"id": "07-mt5-sync", "file": "07-MT5-SYNC.md", "title": "MT5 → Journal Sync", "kind": "system", "order": 7},
    {"id": "08-discipline", "file": "08-DISCIPLINE-METRICS.md", "title": "Métricas de adherencia", "kind": "system", "order": 8},
    {"id": "09-shared-rules", "file": "09-SHARED-RULES.md", "title": "Módulo de reglas compartidas", "kind": "system", "order": 9},
    {"id": "10-kill-switch", "file": "10-KILL-SWITCH.md", "title": "Kill-switch y modos de trading", "kind": "system", "order": 10},
]


@api_router.get("/docs")
async def list_docs():
    items = []
    for d in DOCS_META:
        path = DOCS_DIR / d["file"]
        size = path.stat().st_size if path.exists() else 0
        items.append({**d, "size_bytes": size, "exists": path.exists()})
    return {"docs": items}


@api_router.get("/docs/{doc_id}", response_class=PlainTextResponse)
async def get_doc(doc_id: str):
    meta = next((m for m in DOCS_META if m["id"] == doc_id), None)
    if not meta:
        raise HTTPException(404, "doc not found")
    path = DOCS_DIR / meta["file"]
    if not path.exists():
        raise HTTPException(404, "file missing on disk")
    return path.read_text(encoding="utf-8")


# ----- Trade Journal -----

@api_router.post("/journal", response_model=TradeEntry, dependencies=[Depends(require_token)])
async def create_trade(payload: TradeEntryCreate, db=Depends(get_db)):
    if payload.client_id:
        existing = await db.trades.find_one({"client_id": payload.client_id}, {"_id": 0})
        if existing:
            return existing
    obj = TradeEntry(**payload.model_dump())
    await db.trades.insert_one(obj.model_dump())
    return obj


@api_router.get("/journal", response_model=List[TradeEntry])
async def list_trades(limit: int = 200, db=Depends(get_db)):
    items = await db.trades.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return items


@api_router.put("/journal/{trade_id}", response_model=TradeEntry, dependencies=[Depends(require_token)])
async def update_trade(trade_id: str, payload: TradeEntryCreate, db=Depends(get_db)):
    existing = await db.trades.find_one({"id": trade_id}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "trade not found")
    merged = {**existing, **payload.model_dump(exclude_none=True)}
    obj = TradeEntry(**merged)
    obj_dict = obj.model_dump()
    obj_dict["id"] = trade_id
    await db.trades.update_one({"id": trade_id}, {"$set": obj_dict})
    return obj_dict


@api_router.delete("/journal/{trade_id}", dependencies=[Depends(require_token)])
async def delete_trade(trade_id: str, db=Depends(get_db)):
    res = await db.trades.delete_one({"id": trade_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "trade not found")
    return {"ok": True}


def _capital_fallback() -> float:
    """The number we show when MT5 is unreachable.

    Defaults to ``CAPITAL_FALLBACK_USD`` env var so the operator can match
    it to whatever the broker account currently holds — useful when the
    real account hasn't been funded yet (set it to 0). Falls back to
    ``plan_content.CAPITAL`` ($800) when the env var isn't set.
    """
    raw = os.environ.get("CAPITAL_FALLBACK_USD")
    if raw is not None and raw.strip() != "":
        try:
            return float(raw)
        except ValueError:
            pass
    return float(CAPITAL)


def _live_balance(fallback: float) -> tuple[float, str]:
    """Return (balance, source). Source ∈ {'mt5', 'fallback'}.

    Reads the real current balance from MetaTrader if reachable so the
    dashboard reflects whatever account is loaded (real or demo, $0 or
    $80k). Falls back to ``_capital_fallback`` when MT5 is offline.
    """
    try:
        import mt5_bridge
        info = mt5_bridge.status()
        if info.get("connected") and info.get("account"):
            bal = info["account"].get("balance")
            if isinstance(bal, (int, float)):
                return float(bal), "mt5"
    except Exception:  # noqa: BLE001 — never let stats endpoint crash on MT5
        pass
    return float(fallback), "fallback"


@api_router.get("/journal/stats")
async def journal_stats(db=Depends(get_db)):
    items = await db.trades.find({}, {"_id": 0}).to_list(1000)
    closed = [t for t in items if t["status"] != "open"]
    total = len(closed)
    wins = [t for t in closed if t["pnl_usd"] > 0]
    losses = [t for t in closed if t["pnl_usd"] < 0]
    total_pnl = sum(t["pnl_usd"] for t in closed)
    win_rate = (len(wins) / total * 100) if total else 0.0
    avg_r = (sum(t["r_multiple"] for t in closed) / total) if total else 0.0
    avg_win_r = (sum(t["r_multiple"] for t in wins) / len(wins)) if wins else 0.0
    avg_loss_r = (sum(t["r_multiple"] for t in losses) / len(losses)) if losses else 0.0
    expectancy = (
        (len(wins) / total) * avg_win_r + (len(losses) / total) * avg_loss_r
        if total else 0.0
    )

    balance, balance_source = _live_balance(fallback=_capital_fallback())
    # Equity curve baseline: on the live path we run the journal pnls
    # forward starting from the *current* MT5 balance MINUS the realised pnl
    # so the latest tick lands exactly on the broker's balance number.
    if balance_source == "mt5":
        starting_equity = balance - total_pnl
    else:
        starting_equity = balance

    closed_sorted = sorted(closed, key=lambda t: t["created_at"])
    equity = []
    running = starting_equity
    for t in closed_sorted:
        running += t["pnl_usd"]
        equity.append({
            "date": t["date"],
            "pnl": round(t["pnl_usd"], 2),
            "equity": round(running, 2),
            "symbol": t["symbol"],
        })

    today_str = date.today().isoformat()
    today_trades = [t for t in items if t["date"] == today_str]
    today_closed = [t for t in today_trades if t["status"] != "open"]
    today_pnl = sum(t["pnl_usd"] for t in today_closed)
    today_pnl_pct = (today_pnl / balance * 100) if balance else 0.0
    today_consecutive_losses = 0
    for t in sorted(today_closed, key=lambda x: x["created_at"], reverse=True):
        if t["pnl_usd"] < 0:
            today_consecutive_losses += 1
        else:
            break

    can_trade_today = (
        today_pnl_pct > -MAX_DAILY_LOSS_PCT
        and today_consecutive_losses < MAX_CONSECUTIVE_LOSSES
        and len(today_trades) < 5
    )

    open_count = len([t for t in items if t["status"] == "open"])

    return {
        "total_trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_r": round(avg_r, 2),
        "expectancy": round(expectancy, 2),
        "total_pnl_usd": round(total_pnl, 2),
        "current_equity": round(balance, 2),
        "balance_source": balance_source,
        "today": {
            "trades_count": len(today_trades),
            "pnl_usd": round(today_pnl, 2),
            "pnl_pct": round(today_pnl_pct, 2),
            "consecutive_losses": today_consecutive_losses,
            "can_trade": can_trade_today,
            "open_positions": open_count,
        },
        "equity_curve": equity,
    }


# ----- Discipline adherence -----

@api_router.get("/research/trades")
async def research_trades(limit: int = 50):
    """Per-trade research log — every trade the bot opened, with full setup
    snapshot (scoring breakdown, ATR, market context), management events
    (BE/trail), and final close (pnl, r_multiple, MAE/MFE, exit_reason).

    Reads ~/mcp/logs/trade_research.jsonl and groups events by ticket.
    Returns most recent trades first.
    """
    from pathlib import Path as _P
    log_file = _P(os.path.expanduser(
        os.environ.get("LOG_DIR", "/opt/trading-bot/logs"))) / "trade_research.jsonl"

    if not log_file.exists():
        return {"trades": [], "total": 0, "log_file": str(log_file)}

    by_ticket: dict[int, dict] = {}
    try:
        for line in log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ticket = rec.get("ticket")
            if ticket is None:
                continue
            t = by_ticket.setdefault(int(ticket), {
                "ticket": int(ticket), "open": None, "manage": [], "close": None,
            })
            ev = rec.get("event")
            if ev == "open":
                t["open"] = rec
            elif ev == "manage":
                t["manage"].append(rec)
            elif ev == "close":
                t["close"] = rec
    except OSError as exc:
        return {"trades": [], "total": 0, "error": str(exc)}

    trades = list(by_ticket.values())

    # Helper: sort key — close ts if closed, otherwise open ts, otherwise 0
    def _sort_key(t):
        c = t.get("close") or {}
        o = t.get("open") or {}
        return c.get("ts") or o.get("ts") or ""

    trades.sort(key=_sort_key, reverse=True)
    total = len(trades)
    if limit and limit > 0:
        trades = trades[:limit]
    return {"trades": trades, "total": total, "returned": len(trades)}


@api_router.get("/research/summary")
async def research_summary():
    """Pre-computed aggregates over the research log: win rate by score
    bucket / symbol / hour, expectancy, MFE/MAE distribution, time-to-1R.

    Designed for one-glance post-test analysis: "where is the bot losing?
    where is it winning? what's its actual edge?". The frontend can consume
    this directly without any client-side number crunching.
    """
    from pathlib import Path as _P
    log_file = _P(os.path.expanduser(
        os.environ.get("LOG_DIR", "/opt/trading-bot/logs"))) / "trade_research.jsonl"

    if not log_file.exists():
        return {"empty": True, "log_file": str(log_file)}

    # Group events by ticket
    by_ticket: dict[int, dict] = {}
    try:
        for line in log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ticket = rec.get("ticket")
            if ticket is None:
                continue
            t = by_ticket.setdefault(int(ticket), {
                "open": None, "manage": [], "close": None,
            })
            ev = rec.get("event")
            if ev == "open":
                t["open"] = rec
            elif ev == "manage":
                t["manage"].append(rec)
            elif ev == "close":
                t["close"] = rec
    except OSError as exc:
        return {"error": str(exc)}

    closed = [t for t in by_ticket.values() if t.get("close")]
    n = len(closed)
    if n == 0:
        return {"empty": True, "n_total": len(by_ticket), "n_closed": 0}

    # Helpers
    def _safe(d, *keys, default=None):
        for k in keys:
            if d is None:
                return default
            d = d.get(k) if isinstance(d, dict) else None
        return d if d is not None else default

    def _bucket(score):
        if score is None:
            return "no_score"
        try:
            s = int(score)
        except (TypeError, ValueError):
            return "no_score"
        if s >= 80: return "80+"
        if s >= 70: return "70-79"
        if s >= 60: return "60-69"
        if s >= 50: return "50-59"
        if s >= 40: return "40-49"
        return "<40"

    wins = []
    losses = []
    by_score: dict = {}
    by_symbol: dict = {}
    by_hour: dict = {}
    by_exit_reason: dict = {}
    pnls = []
    rs = []
    mfes = []
    maes = []
    times_to_mfe = []
    spreads_pct_r = []

    for t in closed:
        c = t["close"] or {}
        o = t.get("open") or {}
        pnl = float(c.get("pnl_usd") or 0)
        r = float(c.get("r_multiple") or 0)
        mfe = c.get("mfe_r")
        mae = c.get("mae_r")
        ttm = c.get("time_to_mfe_seconds")
        sym = c.get("symbol") or o.get("symbol") or "?"
        score = o.get("score")
        hour = _safe(o, "context", "utc_hour")
        reason = c.get("exit_reason", "UNKNOWN")
        spread_r = _safe(o, "spread_pct_of_r")

        pnls.append(pnl)
        rs.append(r)
        if mfe is not None: mfes.append(float(mfe))
        if mae is not None: maes.append(float(mae))
        if ttm is not None: times_to_mfe.append(int(ttm))
        if spread_r is not None: spreads_pct_r.append(float(spread_r))

        if pnl > 0: wins.append(t)
        elif pnl < 0: losses.append(t)

        # Score bucket
        b = _bucket(score)
        bs = by_score.setdefault(b, {"n": 0, "wins": 0, "pnl": 0.0, "r_sum": 0.0})
        bs["n"] += 1; bs["pnl"] += pnl; bs["r_sum"] += r
        if pnl > 0: bs["wins"] += 1

        # Symbol
        bsy = by_symbol.setdefault(sym, {"n": 0, "wins": 0, "pnl": 0.0, "r_sum": 0.0})
        bsy["n"] += 1; bsy["pnl"] += pnl; bsy["r_sum"] += r
        if pnl > 0: bsy["wins"] += 1

        # Hour
        if hour is not None:
            try:
                h = int(hour)
                bh = by_hour.setdefault(h, {"n": 0, "wins": 0, "pnl": 0.0})
                bh["n"] += 1; bh["pnl"] += pnl
                if pnl > 0: bh["wins"] += 1
            except (TypeError, ValueError):
                pass

        # Exit reason
        br = by_exit_reason.setdefault(reason, {"n": 0, "wins": 0, "pnl": 0.0})
        br["n"] += 1; br["pnl"] += pnl
        if pnl > 0: br["wins"] += 1

    def _stat(arr):
        if not arr: return None
        a = sorted(arr)
        return {
            "n": len(a),
            "min": round(min(a), 4),
            "max": round(max(a), 4),
            "mean": round(sum(a) / len(a), 4),
            "median": round(a[len(a)//2], 4),
        }

    # Compute win-rate fields
    for d in (by_score, by_symbol, by_hour, by_exit_reason):
        for k, v in d.items():
            v["win_rate_pct"] = round(v["wins"] / max(v["n"], 1) * 100, 1)
            v["pnl"] = round(v["pnl"], 2)
            if "r_sum" in v:
                v["avg_r"] = round(v["r_sum"] / max(v["n"], 1), 2)

    win_r = [r for r, p in zip(rs, pnls) if p > 0]
    loss_r = [r for r, p in zip(rs, pnls) if p < 0]
    expectancy_r = round(sum(rs) / len(rs), 3) if rs else 0.0

    # ── Phase 1: Pro Metrics ──────────────────────────────────────────
    import math as _math
    from collections import defaultdict as _defaultdict
    from datetime import datetime as _dt

    # Daily P&L for Sharpe/Sortino/equity curve
    daily_pnl = _defaultdict(float)
    daily_r = _defaultdict(float)
    for tk, tdata in by_ticket.items():
        o, c = tdata["open"], tdata["close"]
        if not o or not c:
            continue
        close_ts = c.get("ts") or c.get("timestamp")
        if not close_ts:
            continue
        try:
            day_key = _dt.fromisoformat(str(close_ts).replace("Z", "+00:00")).strftime("%Y-%m-%d")
        except Exception:
            try:
                day_key = _dt.utcfromtimestamp(float(close_ts)).strftime("%Y-%m-%d")
            except Exception:
                continue
        pnl_val = c.get("pnl_usd", 0.0) or 0.0
        r_val = c.get("r_multiple", 0.0) or 0.0
        daily_pnl[day_key] += pnl_val
        daily_r[day_key] += r_val

    daily_returns = [v for _, v in sorted(daily_pnl.items())]
    daily_r_returns = [v for _, v in sorted(daily_r.items())]

    # Sharpe Ratio (annualized, 252 trading days)
    def _sharpe(returns, rf_daily=0.0):
        if len(returns) < 2:
            return None
        mean_r = sum(returns) / len(returns) - rf_daily
        std_r = (sum((x - sum(returns)/len(returns))**2 for x in returns) / (len(returns) - 1)) ** 0.5
        if std_r == 0:
            return None
        return round(mean_r / std_r * (252 ** 0.5), 3)

    # Sortino Ratio (only downside deviation)
    def _sortino(returns, rf_daily=0.0):
        if len(returns) < 2:
            return None
        mean_r = sum(returns) / len(returns) - rf_daily
        downside = [min(0, x - rf_daily)**2 for x in returns]
        dd = (sum(downside) / len(downside)) ** 0.5
        if dd == 0:
            return None
        return round(mean_r / dd * (252 ** 0.5), 3)

    # SQN (System Quality Number — Van Tharp)
    def _sqn(r_multiples):
        if len(r_multiples) < 10:
            return None
        mean_r = sum(r_multiples) / len(r_multiples)
        std_r = (sum((x - mean_r)**2 for x in r_multiples) / (len(r_multiples) - 1)) ** 0.5
        if std_r == 0:
            return None
        return round(mean_r / std_r * min(len(r_multiples), 100) ** 0.5, 3)

    # Profit Factor
    gross_profit = sum(p for p in pnls if p > 0)
    gross_loss = abs(sum(p for p in pnls if p < 0))
    profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else None

    # Max Drawdown (on equity curve)
    equity_curve = []
    cumulative = 0.0
    for day_key in sorted(daily_pnl.keys()):
        cumulative += daily_pnl[day_key]
        equity_curve.append({"date": day_key, "equity": round(cumulative, 2)})

    peak = 0.0
    max_dd = 0.0
    max_dd_pct = 0.0
    for pt in equity_curve:
        eq = pt["equity"]
        if eq > peak:
            peak = eq
        dd = peak - eq
        if dd > max_dd:
            max_dd = dd
        if peak > 0:
            dd_pct = dd / peak * 100
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

    # Calmar Ratio (annualized return / max drawdown)
    n_days = len(daily_returns) if daily_returns else 1
    total_return = sum(daily_returns) if daily_returns else 0
    annualized_return = total_return / max(n_days, 1) * 252
    calmar = round(annualized_return / max_dd, 3) if max_dd > 0 else None

    # Consecutive wins/losses streaks
    max_consec_wins = 0
    max_consec_losses = 0
    cur_wins = 0
    cur_losses = 0
    for p in pnls:
        if p > 0:
            cur_wins += 1
            cur_losses = 0
            if cur_wins > max_consec_wins:
                max_consec_wins = cur_wins
        elif p < 0:
            cur_losses += 1
            cur_wins = 0
            if cur_losses > max_consec_losses:
                max_consec_losses = cur_losses
        else:
            cur_wins = 0
            cur_losses = 0

    # Daily P&L heatmap data (for calendar view)
    daily_pnl_heatmap = [{"date": k, "pnl": round(v, 2)} for k, v in sorted(daily_pnl.items())]

    # Per-strategy breakdown
    by_strategy = {}
    for tk, tdata in by_ticket.items():
        o, c = tdata["open"], tdata["close"]
        if not o or not c:
            continue
        sid = o.get("strategy_id") or o.get("strategy") or "unknown"
        s = by_strategy.setdefault(sid, {"n": 0, "wins": 0, "pnl": 0.0, "r_sum": 0.0})
        pnl_val = c.get("pnl_usd", 0.0) or 0.0
        r_val = c.get("r_multiple", 0.0) or 0.0
        s["n"] += 1
        s["pnl"] += pnl_val
        s["r_sum"] += r_val
        if pnl_val > 0:
            s["wins"] += 1
    for v in by_strategy.values():
        v["win_rate_pct"] = round(v["wins"] / max(v["n"], 1) * 100, 1)
        v["avg_r"] = round(v["r_sum"] / max(v["n"], 1), 3)
        v["pnl"] = round(v["pnl"], 2)

    pro_metrics = {
        "sharpe_ratio": _sharpe(daily_returns),
        "sortino_ratio": _sortino(daily_returns),
        "sqn": _sqn(rs),
        "profit_factor": profit_factor,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "max_drawdown_usd": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "calmar_ratio": calmar,
        "max_consecutive_wins": max_consec_wins,
        "max_consecutive_losses": max_consec_losses,
        "n_trading_days": len(daily_returns),
        "avg_daily_pnl": round(sum(daily_returns) / max(len(daily_returns), 1), 2),
    }
    # ── End Phase 1 Pro Metrics ─────────────────────────────────────

    return {
        "empty": False,
        "log_file": str(log_file),
        "n_closed": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(len(wins) / n * 100, 1),
        "expectancy_r": expectancy_r,
        "total_pnl_usd": round(sum(pnls), 2),
        "by_score_bucket": by_score,
        "by_symbol": by_symbol,
        "by_hour_utc": by_hour,
        "by_exit_reason": by_exit_reason,
        "by_strategy": by_strategy,
        "pro_metrics": pro_metrics,
        "equity_curve": equity_curve,
        "daily_pnl_heatmap": daily_pnl_heatmap,
        "stats": {
            "pnl_usd": _stat(pnls),
            "r_multiple": _stat(rs),
            "mfe_r": _stat(mfes),
            "mae_r": _stat(maes),
            "time_to_mfe_s": _stat(times_to_mfe),
            "spread_pct_of_r_at_entry": _stat(spreads_pct_r),
            "win_r_avg": round(sum(win_r) / len(win_r), 2) if win_r else 0.0,
            "loss_r_avg": round(sum(loss_r) / len(loss_r), 2) if loss_r else 0.0,
        },
    }


@api_router.get("/discipline/score")
async def discipline_score(db=Depends(get_db), window: int = 30):
    """Adherence score: % of the last ``window`` closed trades that obey ALL
    discipline rules.

    Rules checked, per trade:
      - SL_RUNAWAY        — losing trade with r_multiple < -1.05 (SL slipped
                            beyond plan; broker stop-out or no SL set).
      - NO_SL             — trade missing or zero SL.
      - WEAK_RR           — closed-win/loss with R:R below MIN_RR (the bot
                            should have rejected this setup pre-trade).
      - REVENGE           — opened ≤ 5 min after a previous loss on the
                            same symbol (anti-tilt).
      - OVERTRADING_DAY   — trade is the (MAX_TRADES_PER_DAY+1)-th of its
                            UTC day or later.

    Returns:
      - adherence_pct: 0.0..100.0 over ``window`` trades
      - eligible_for_live: True iff score ≥ 95% AND checked ≥ window
      - violations: list of {trade_id, rule, detail}
      - checked: count of trades evaluated
      - per_rule_counts: how many trades broke each rule
    """
    # CLAUDE.md non-negotiable: live trading needs ≥95% over last 30
    LIVE_THRESHOLD_PCT = 95.0
    REVENGE_MINUTES = 5
    MIN_RR_RULE = 2.0
    MAX_TRADES_DAY = 5

    items = await db.trades.find({}, {"_id": 0}).to_list(2000)
    closed = [t for t in items if t.get("status", "open") != "open"]
    # Sort newest first (date string YYYY-MM-DD then created_at)
    closed.sort(key=lambda t: (t.get("date", ""), t.get("created_at", "")),
                reverse=True)
    sample = closed[:window]
    if not sample:
        return {
            "adherence_pct": 100.0,
            "eligible_for_live": False,
            "violations": [],
            "checked": 0,
            "window": window,
            "per_rule_counts": {},
            "verdict": "INSUFFICIENT_DATA",
            "live_threshold_pct": LIVE_THRESHOLD_PCT,
        }

    # For REVENGE + OVERTRADING_DAY we need chronological order
    chrono = sorted(sample, key=lambda t: (t.get("date", ""), t.get("created_at", "")))

    last_loss_per_symbol: dict = {}  # symbol → (date, created_at_iso)
    trades_per_day: dict = {}        # YYYY-MM-DD → count

    rule_counts = {
        "SL_RUNAWAY": 0, "NO_SL": 0, "WEAK_RR": 0,
        "REVENGE": 0, "OVERTRADING_DAY": 0,
    }
    violations = []
    bad_trade_ids: set = set()

    def _flag(t, rule, detail):
        rule_counts[rule] += 1
        bad_trade_ids.add(t.get("id"))
        violations.append({"trade_id": t.get("id"), "rule": rule,
                           "detail": detail, "symbol": t.get("symbol")})

    for t in chrono:
        sl = float(t.get("sl") or 0)
        rmul = float(t.get("r_multiple") or 0)
        pnl = float(t.get("pnl_usd") or 0)
        sym = (t.get("symbol") or "").upper()
        day = (t.get("date") or "")[:10]

        # Day count
        trades_per_day[day] = trades_per_day.get(day, 0) + 1
        if trades_per_day[day] > MAX_TRADES_DAY:
            _flag(t, "OVERTRADING_DAY",
                  f"trade {trades_per_day[day]} del {day} (cap {MAX_TRADES_DAY})")

        # SL presence
        if sl <= 0:
            _flag(t, "NO_SL", "SL ausente o cero")

        # SL runaway
        if pnl < 0 and rmul < -1.05:
            _flag(t, "SL_RUNAWAY", f"r_multiple {rmul:.2f} < -1.05")

        # Weak RR — only meaningful for trades with both entry and tp set
        try:
            entry = float(t.get("entry") or 0)
            tp = float(t.get("tp") or 0)
            if entry > 0 and sl > 0 and tp > 0:
                risk_d = abs(entry - sl)
                reward_d = abs(tp - entry)
                rr_planned = (reward_d / risk_d) if risk_d > 0 else 0
                if rr_planned > 0 and rr_planned < MIN_RR_RULE:
                    _flag(t, "WEAK_RR",
                          f"R:R planeado {rr_planned:.2f} < {MIN_RR_RULE}")
        except (TypeError, ValueError):
            pass

        # Revenge trade — same symbol, ≤ 5 min after a loss
        prev = last_loss_per_symbol.get(sym)
        if prev is not None:
            try:
                prev_dt = datetime.fromisoformat(prev.replace("Z", "+00:00"))
                cur_iso = t.get("created_at") or t.get("date") + "T00:00:00+00:00"
                cur_dt = datetime.fromisoformat(cur_iso.replace("Z", "+00:00"))
                delta_min = (cur_dt - prev_dt).total_seconds() / 60.0
                if 0 <= delta_min <= REVENGE_MINUTES:
                    _flag(t, "REVENGE",
                          f"{sym} reabrió {delta_min:.1f}min después de pérdida")
            except (ValueError, TypeError):
                pass
        if pnl < 0:
            last_loss_per_symbol[sym] = (
                t.get("created_at") or (t.get("date") + "T23:59:59+00:00"))

    clean_count = len(sample) - len(bad_trade_ids)
    adherence_pct = round(clean_count / len(sample) * 100.0, 1)
    eligible = (adherence_pct >= LIVE_THRESHOLD_PCT) and (len(sample) >= window)

    if eligible:
        verdict = "ELIGIBLE_FOR_LIVE"
    elif len(sample) < window:
        verdict = "INSUFFICIENT_DATA"
    elif adherence_pct >= 80:
        verdict = "GOOD_BUT_NOT_LIVE"
    else:
        verdict = "POOR"

    return {
        "adherence_pct": adherence_pct,
        "eligible_for_live": eligible,
        "violations": violations,
        "checked": len(sample),
        "clean_trades": clean_count,
        "window": window,
        "per_rule_counts": rule_counts,
        "verdict": verdict,
        "live_threshold_pct": LIVE_THRESHOLD_PCT,
    }


# ----- Checklist -----

@api_router.get("/checklist/{day}", response_model=ChecklistState)
async def get_checklist(day: str, db=Depends(get_db)):
    if not _valid_date(day):
        raise HTTPException(400, "fecha inválida (YYYY-MM-DD)")
    doc = await db.checklists.find_one({"date": day}, {"_id": 0})
    if not doc:
        return ChecklistState(date=day, checked_ids=[])
    return doc


@api_router.post("/checklist", response_model=ChecklistState, dependencies=[Depends(require_token)])
async def update_checklist(payload: ChecklistUpdate, db=Depends(get_db)):
    obj = ChecklistState(date=payload.date, checked_ids=payload.checked_ids)
    doc = obj.model_dump()
    await db.checklists.update_one(
        {"date": payload.date},
        {"$set": doc},
        upsert=True,
    )
    return obj


def _valid_date(day: str) -> bool:
    try:
        datetime.strptime(day, "%Y-%m-%d")
        return True
    except ValueError:
        return False


# ----- Risk Calculator -----

@api_router.post("/risk/calc")
async def risk_calculate(inp: RiskCalcInput):
    risk_dollars = inp.balance * (inp.risk_pct / 100.0)
    sl_distance = abs(inp.entry - inp.stop_loss)
    sl_pips = sl_distance / inp.pip_size
    if sl_pips <= 0:
        raise HTTPException(400, "sl_pips inválido")

    raw_lots = risk_dollars / (sl_pips * inp.pip_value)

    warnings = []
    # If even the minimum lot would exceed the risk budget, refuse to size.
    # Forcing min_lot would silently break the 1% rule.
    if raw_lots < inp.min_lot:
        warnings.append(
            f"Riesgo solicitado (${round(risk_dollars,2)}) < lotaje mínimo "
            f"({inp.min_lot} = ${round(inp.min_lot * sl_pips * inp.pip_value,2)}). "
            "Aleja el SL, sube balance o salta el trade."
        )
        return {
            "lots": 0.0,
            "risk_dollars": 0.0,
            "risk_pct_actual": 0.0,
            "sl_distance": round(sl_distance, 5),
            "sl_pips": round(sl_pips, 2),
            "warnings": warnings,
        }

    steps = int(raw_lots / inp.lot_step)
    snapped = round(max(inp.min_lot, steps * inp.lot_step), 4)
    capped = round(min(snapped, inp.max_lot), 4)

    actual_risk = capped * sl_pips * inp.pip_value
    actual_risk_pct = actual_risk / inp.balance * 100

    if capped < snapped:
        warnings.append(f"Lotaje recortado de {snapped} a {capped} (cap de seguridad {inp.max_lot})")
    if inp.risk_pct > MAX_RISK_PER_TRADE_PCT:
        warnings.append(f"⚠️ Riesgo {inp.risk_pct}% excede tu regla de {MAX_RISK_PER_TRADE_PCT}%")
    if sl_pips < 5:
        warnings.append("SL muy cerca: revisa que no sea ruido. Stops < 5 pips suelen sacar.")

    return {
        "lots": capped,
        "risk_dollars": round(actual_risk, 2),
        "risk_pct_actual": round(actual_risk_pct, 3),
        "sl_distance": round(sl_distance, 5),
        "sl_pips": round(sl_pips, 2),
        "warnings": warnings,
    }


# ----- Control Panel (MT5 status + Kill-switch + Sync trigger) -----

import mt5_bridge  # noqa: E402

# ============================================================================
# Strategy engine endpoints (v3)
# ============================================================================

# Import strategy engine (lives in the trading-mt5-mcp tree)
import importlib.util as _ilu
_strat_path = Path(__file__).resolve().parent.parent / "mcp-scaffolds" / "trading-mt5-mcp"
if str(_strat_path) not in sys.path:
    sys.path.insert(0, str(_strat_path))
# Pre-load analysis libs needed by strategies
_analysis_dir = Path(__file__).resolve().parent.parent / "mcp-scaffolds" / "analysis-mcp" / "lib"
if "analysis_lib" not in sys.modules:
    import importlib
    _apkg = importlib.util.module_from_spec(
        importlib.util.spec_from_loader("analysis_lib", loader=None, is_package=True))
    _apkg.__path__ = [str(_analysis_dir)]
    sys.modules["analysis_lib"] = _apkg
    for _mn in ("indicators", "structure"):
        _mpath = _analysis_dir / f"{_mn}.py"
        if _mpath.exists():
            _mspec = importlib.util.spec_from_file_location(f"analysis_lib.{_mn}", _mpath)
            _mmod = importlib.util.module_from_spec(_mspec)
            sys.modules[f"analysis_lib.{_mn}"] = _mmod
            _mspec.loader.exec_module(_mmod)

try:
    import strategies as strat_engine
    _STRAT_AVAILABLE = True
except ImportError as _e:
    logging.warning("Strategy engine not available: %s", _e)
    _STRAT_AVAILABLE = False


@app.get("/api/strategies")
async def api_strategies():
    """List all available strategies with theoretical + real performance."""
    if not _STRAT_AVAILABLE:
        return {"strategies": [], "error": "engine_not_loaded"}

    strategies = strat_engine.list_strategies()
    active = strat_engine.get_active_strategy()

    # Compute real stats per strategy from research log
    log_path = Path(os.path.expanduser(
        os.environ.get("LOG_DIR", "/opt/trading-bot/logs"))) / "trade_research.jsonl"
    real_stats = {}
    if log_path.exists():
        try:
            events = {}
            with open(log_path, "r") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                        evt = rec.get("event")
                        if evt == "open":
                            ticket = rec.get("ticket")
                            events[ticket] = {"open": rec, "close": None}
                        elif evt == "close":
                            ticket = rec.get("ticket")
                            if ticket in events:
                                events[ticket]["close"] = rec
                    except (json.JSONDecodeError, ValueError):
                        pass

            # Group closed trades by strategy_id
            by_strat = {}
            for ticket, data in events.items():
                if not data.get("close"):
                    continue
                sid = data["open"].get("strategy_id", "score_v2_legacy")
                if sid not in by_strat:
                    by_strat[sid] = {"wins": 0, "losses": 0, "total_r": 0.0,
                                     "total_pnl": 0.0, "trades": []}
                c = data["close"]
                pnl = float(c.get("pnl_usd", 0))
                r = float(c.get("r_multiple", 0))
                by_strat[sid]["total_r"] += r
                by_strat[sid]["total_pnl"] += pnl
                if pnl > 0:
                    by_strat[sid]["wins"] += 1
                elif pnl < 0:
                    by_strat[sid]["losses"] += 1
                by_strat[sid]["trades"].append({
                    "ticket": ticket,
                    "symbol": data["open"].get("symbol"),
                    "pnl": pnl,
                    "r": r,
                })

            for sid, stats in by_strat.items():
                n = stats["wins"] + stats["losses"]
                real_stats[sid] = {
                    "trades": n,
                    "wins": stats["wins"],
                    "losses": stats["losses"],
                    "win_rate": round(stats["wins"] / n * 100, 1) if n > 0 else 0,
                    "avg_r": round(stats["total_r"] / n, 3) if n > 0 else 0,
                    "total_pnl": round(stats["total_pnl"], 2),
                    "expectancy": round(stats["total_r"] / n, 3) if n > 0 else 0,
                }
        except Exception as e:
            logging.warning("Strategy stats computation failed: %s", e)

    # Merge real stats into strategy dicts
    for s in strategies:
        sid = s["id"]
        s["real"] = real_stats.get(sid, {
            "trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0, "avg_r": 0, "total_pnl": 0, "expectancy": 0,
        })
        s["active"] = (active.id == sid)

    # Include legacy trades (before strategy engine) under a special key
    legacy = real_stats.get("score_v2_legacy", real_stats.get("unknown", None))
    if legacy:
        strategies.append({
            "id": "score_v2_legacy",
            "name": "Score v2 (Legacy)",
            "description": "Sistema original antes del motor multi-estrategia.",
            "type": "trend",
            "color": "gray",
            "theoretical": {"win_rate": 30, "rr": 2.5, "expectancy": -0.10},
            "params": {"min_score": 70, "sl_atr_mult": 1.0, "tp_atr_mult": 2.5},
            "real": legacy,
            "active": False,
        })

    return {"strategies": strategies, "active": active.id}


@app.post("/api/strategies/{strategy_id}/activate")
async def api_activate_strategy(strategy_id: str, _=Depends(require_token)):
    """Switch the active trading strategy."""
    if not _STRAT_AVAILABLE:
        raise HTTPException(503, "Strategy engine not loaded")
    result = strat_engine.set_active_strategy(strategy_id)
    if not result.get("ok"):
        raise HTTPException(400, result.get("reason", "unknown error"))
    return result


import bot_bridge  # noqa: E402
import process_manager  # noqa: E402
import telegram_notifier  # noqa: E402

# Capa 5 (legacy ports) — reduced backend libraries
from bot_lib.backtest.engine import run_backtest as _run_backtest  # noqa: E402
from bot_lib.telegram_control import (  # noqa: E402
    CommandRequest as _CommandRequest,
    dispatch as _dispatch_command,
    make_stub_handlers as _stub_handlers,
)
from bot_lib.monitoring.quality_assessment import (  # noqa: E402
    build_report as _build_quality_report,
    make_check as _quality_check,
    score_category as _score_quality_category,
)
from bot_lib.selfcheck import run_selfcheck as _run_selfcheck  # noqa: E402



class HaltPayload(BaseModel):
    reason: str = Field(default="manual halt from dashboard", max_length=500)


class SyncPayload(BaseModel):
    lookback_days: int = Field(default=7, ge=1, le=90)


class ScanPayload(BaseModel):
    symbols: Optional[List[str]] = None


class ExecuteTradePayload(BaseModel):
    symbol: str = Field(min_length=1, max_length=32)
    side: Literal["buy", "sell"]
    sl: float = Field(gt=0)
    tp: float = Field(gt=0)
    risk_pct: float = Field(default=1.0, gt=0, le=10)
    lots: Optional[float] = Field(default=None, gt=0, le=10)
    client_order_id: Optional[str] = Field(default=None, max_length=64)


class BotConfigPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    updates: dict = Field(default_factory=dict)


class MT5CredsPayload(BaseModel):
    login: str = Field(min_length=1, max_length=20)
    password: str = Field(min_length=1, max_length=200)
    server: str = Field(min_length=1, max_length=100)
    path: Optional[str] = Field(default=None, max_length=500)


class ProcessStartPayload(BaseModel):
    extra_args: Optional[List[str]] = None


@api_router.get("/halt")
async def halt_get():
    """Estado actual del kill-switch. Devuelve {ok, halted, halted_at, reason, path}."""
    res = mt5_bridge.halt_status() or {}
    return {"ok": True, **res}


@api_router.post("/halt", dependencies=[Depends(require_token)])
async def halt_post(payload: HaltPayload):
    """Activa el kill-switch. Devuelve {ok, halted, halted_at, reason, path}.

    Antes devolvía solo el dict crudo de mt5_bridge (sin `ok`). El frontend
    asumía la presencia de `ok` para feedback visual; ahora normalizamos.
    """
    res = mt5_bridge.halt_set(payload.reason) or {}
    try:
        telegram_notifier.notify_halt(payload.reason)
    except Exception:  # noqa: BLE001 — never let TG error break the API
        pass
    return {"ok": True, **res}


@api_router.delete("/halt", dependencies=[Depends(require_token)])
async def halt_delete():
    """Desactiva el kill-switch. Devuelve {ok, halted: false, ...}."""
    res = mt5_bridge.halt_clear() or {}
    try:
        telegram_notifier.notify_resume()
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, **res}


@api_router.get("/mt5/status")
async def mt5_status():
    return mt5_bridge.status()


@api_router.post("/mt5/sync", dependencies=[Depends(require_token)])
async def mt5_sync(payload: SyncPayload = SyncPayload()):
    return mt5_bridge.trigger_sync(payload.lookback_days)


@api_router.get("/system/health")
async def system_health():
    """Rollup health: backend + DB + MT5 + halt status."""
    db_ok = state.db is not None
    mt5_info = mt5_bridge.status()
    halt = mt5_bridge.halt_status()
    bot = bot_bridge.status()
    return {
        "backend": True,
        "database": db_ok,
        "mt5": bool(mt5_info.get("connected")),
        "mt5_account": mt5_info.get("account", {}).get("login") if mt5_info.get("connected") else None,
        "trading_halted": halt.get("halted", False),
        "halt_reason": halt.get("reason"),
        "bot_alive": bot.get("alive", False),
        "auth_required": bool(DASHBOARD_TOKEN),
    }


# ----- Bot endpoints (status / scan / execute / log / config) -----

@api_router.get("/bot/status")
async def bot_status():
    return bot_bridge.status()


@api_router.get("/bot/log")
async def bot_log(n: int = 50):
    return bot_bridge.log_tail(min(max(n, 1), 500))


@api_router.post("/bot/scan", dependencies=[Depends(require_token)])
async def bot_scan(payload: ScanPayload = ScanPayload()):
    """Run an on-demand scan — returns every candidate setup with score."""
    return bot_bridge.scan_now(payload.symbols)


@api_router.post("/bot/execute", dependencies=[Depends(require_token)])
async def bot_execute(payload: ExecuteTradePayload):
    """Place an order through the MCP. Same guards as the auto-trader."""
    return bot_bridge.execute_trade(
        symbol=payload.symbol, side=payload.side,
        sl=payload.sl, tp=payload.tp, risk_pct=payload.risk_pct,
        lots=payload.lots, client_order_id=payload.client_order_id,
    )


@api_router.get("/bot/config")
async def bot_config_get():
    return bot_bridge.get_config()


@api_router.post("/bot/config", dependencies=[Depends(require_token)])
async def bot_config_set(payload: BotConfigPayload):
    updates = payload.updates
    if not updates:
        extras = payload.model_extra or {}
        # Handle {"key": "K", "value": "V"} shorthand
        if "key" in extras and "value" in extras and len(extras) == 2:
            updates = {str(extras["key"]): str(extras["value"])}
        elif extras:
            updates = {k: str(v) for k, v in extras.items()}
    if not updates:
        return {"ok": False, "reason": "NO_UPDATES",
                "detail": "Send {\"updates\": {\"KEY\": \"VALUE\"}} or flat {\"KEY\": \"VALUE\"}"}
    return bot_bridge.set_config(updates)


# ----- MT5 credentials (write to .env, gitignored) -----

@api_router.post("/mt5/credentials/test")
async def mt5_credentials_test(payload: MT5CredsPayload):
    """Try to authenticate without saving the .env. Surfaces broker errors."""
    return bot_bridge.test_mt5_credentials(
        login=payload.login, password=payload.password,
        server=payload.server, path=payload.path,
    )


@api_router.post("/mt5/credentials", dependencies=[Depends(require_token)])
async def mt5_credentials_set(payload: MT5CredsPayload):
    return bot_bridge.set_mt5_credentials(
        login=payload.login, password=payload.password,
        server=payload.server, path=payload.path,
    )


# ----- Process control (auto_trader / sync_loop) -----

@api_router.get("/process/list")
async def process_list():
    return process_manager.list_processes()


@api_router.get("/process/{name}")
async def process_status(name: str):
    return process_manager.status(name)


@api_router.post("/process/{name}/start", dependencies=[Depends(require_token)])
async def process_start(name: str, payload: ProcessStartPayload = ProcessStartPayload()):
    return process_manager.start(name, extra_args=payload.extra_args)


@api_router.post("/process/{name}/stop", dependencies=[Depends(require_token)])
async def process_stop(name: str):
    return process_manager.stop(name)


@api_router.post("/process/{name}/restart", dependencies=[Depends(require_token)])
async def process_restart(name: str, payload: ProcessStartPayload = ProcessStartPayload()):
    return process_manager.restart(name, extra_args=payload.extra_args)


@api_router.get("/process/{name}/log")
async def process_log(name: str, lines: int = 50):
    return process_manager.tail_log(name, min(max(lines, 1), 500))


# ----- Supervisor (scheduled task on Claude side) -----

@api_router.get("/supervisor")
async def supervisor_status():
    return bot_bridge.supervisor_status()


# ----- Telegram notifications -----

class TelegramTestPayload(BaseModel):
    text: Optional[str] = Field(default=None, max_length=1000)


@api_router.get("/telegram/status")
async def telegram_status():
    return telegram_notifier.status()


@api_router.post("/telegram/test", dependencies=[Depends(require_token)])
async def telegram_test(payload: TelegramTestPayload = TelegramTestPayload()):
    msg = payload.text or (
        "✅ *Test desde el dashboard*\n"
        "Si ves este mensaje, las notificaciones del bot de trading "
        "están conectadas correctamente."
    )
    return telegram_notifier.send(msg)


@api_router.post("/telegram/summary", dependencies=[Depends(require_token)])
async def telegram_summary():
    """Send a one-shot summary of the current bot state to Telegram."""
    mt5_info = mt5_bridge.status()
    bot = bot_bridge.status()
    if not mt5_info.get("connected"):
        return telegram_notifier.notify_alert("MT5 no conectado en este momento.")
    acc = mt5_info["account"]
    today = mt5_info["today"]
    return telegram_notifier.notify_summary(
        balance=acc.get("balance", 0),
        equity=acc.get("equity", 0),
        today_pnl=today.get("total_pl_usd", 0),
        today_pct=today.get("total_pl_pct", 0),
        open_count=bot.get("open_count", 0),
        wins=bot.get("wins", 0),
        losses=bot.get("losses", 0),
        total_pnl=bot.get("total_pnl_usd", 0),
        currency=acc.get("currency", "USD"),
    )




# ============================================================================
# Capa 5 endpoints (legacy ports)
# ============================================================================


class BacktestRunPayload(BaseModel):
    """Inputs for POST /api/backtest/run."""

    ohlcv: List[dict] = Field(..., description="List of OHLCV bar dicts.")
    config: Optional[dict] = Field(default=None, description="BacktestConfig override.")
    # `signal_spec` chooses how to derive signals during backtest:
    #   {"kind": "always_long"} → trivial demo callback (LONG every bar)
    #   {"kind": "always_flat"} → no entries (sanity)
    #   {"kind": "atr_threshold", "atr_pct_min": 0.001} → enter LONG when atr/close >= threshold
    # In production wiring, callers can replace this with a richer spec
    # (e.g. {"kind": "mcp", "strategy": "ema_rsi_trend"}) and the server
    # would proxy to analysis-mcp.
    signal_spec: Optional[dict] = Field(default=None)

    model_config = ConfigDict(extra="forbid")


def _signal_fn_from_spec(spec: Optional[dict]):
    """Build a backtest signal_fn from a JSON-safe spec.

    Defaults to always_flat to avoid unintended trades.
    """
    spec = spec or {"kind": "always_flat"}
    kind = str(spec.get("kind", "always_flat")).lower()

    if kind == "always_long":
        def _fn(ohlcv):
            if len(ohlcv) < 2:
                return {"direction": "FLAT", "atr": 0.0}
            last_close = float(ohlcv[-1].get("close", 0.0))
            return {"direction": "LONG", "atr": last_close * 0.005, "score": 1.0}
        return _fn

    if kind == "atr_threshold":
        atr_pct_min = float(spec.get("atr_pct_min", 0.001))
        def _fn(ohlcv):
            if len(ohlcv) < 2:
                return {"direction": "FLAT", "atr": 0.0}
            last_close = float(ohlcv[-1].get("close", 0.0))
            atr = last_close * 0.005
            atr_pct = (atr / last_close) if last_close else 0.0
            if atr_pct < atr_pct_min:
                return {"direction": "FLAT", "atr": 0.0}
            return {"direction": "LONG", "atr": atr, "score": 1.0}
        return _fn

    # Strategy-based signals (Phase 2)
    if kind == "strategy":
        strategy_id = str(spec.get("strategy_id", "trend_rider"))
        try:
            from bot_lib.backtest.adapter import strategy_signal_fn
            return strategy_signal_fn(strategy_id)
        except Exception as exc:
            import logging
            logging.getLogger("backtest").warning("strategy signal_fn failed: %s", exc)
            pass

    # Default: always_flat
    def _flat(ohlcv):
        return {"direction": "FLAT", "atr": 0.0}
    return _flat


@api_router.post("/backtest/run", dependencies=[Depends(require_token)])
def backtest_run(payload: BacktestRunPayload):
    """Run a deterministic backtest and return metrics + trades.

    Auth-gated. The signal callback is chosen by `signal_spec` so the
    endpoint does NOT execute arbitrary user code.
    """
    signal_fn = _signal_fn_from_spec(payload.signal_spec)
    return _run_backtest(
        ohlcv=payload.ohlcv,
        signal_fn=signal_fn,
        config=payload.config,
    )


@api_router.get("/backtest/strategies")
async def list_backtest_strategies():
    """List available strategies for backtesting with their default configs."""
    try:
        from bot_lib.backtest.adapter import BACKTEST_STRATEGIES
        return {"strategies": BACKTEST_STRATEGIES}
    except ImportError:
        return {"strategies": {
            "trend_rider": {"name": "Trend Rider", "default_config": {"sl_atr_mult": 1.5, "tp_atr_mult": 3.0}},
            "mean_reverter": {"name": "Mean Reverter", "default_config": {"sl_atr_mult": 1.0, "tp_atr_mult": 2.0}},
            "breakout_hunter": {"name": "Breakout Hunter", "default_config": {"sl_atr_mult": 2.0, "tp_atr_mult": 4.0}},
            "score_v3": {"name": "Score v3", "default_config": {"sl_atr_mult": 1.5, "tp_atr_mult": 2.5}},
        }}


@api_router.post("/backtest/strategy", dependencies=[Depends(require_token)])
async def backtest_with_strategy(payload: dict):
    """Convenience endpoint: run backtest with a named strategy + synthetic data.

    Accepts: strategy_id, symbol (optional), bars (optional), config (optional).
    Generates synthetic OHLCV if no data provided.
    """
    strategy_id = payload.get("strategy_id", "trend_rider")
    bars_count = int(payload.get("bars", 1000))
    symbol = payload.get("symbol", "EURUSD")
    user_config = payload.get("config", {})

    # Try to get strategy defaults
    try:
        from bot_lib.backtest.adapter import BACKTEST_STRATEGIES, strategy_signal_fn
        strat_info = BACKTEST_STRATEGIES.get(strategy_id)
        if not strat_info:
            return JSONResponse(status_code=400, content={
                "error": "Unknown strategy: {}".format(strategy_id),
                "available": list(BACKTEST_STRATEGIES.keys()),
            })
        defaults = strat_info["default_config"]
    except ImportError:
        defaults = {"sl_atr_mult": 1.5, "tp_atr_mult": 2.5, "min_score": 0.5}
        from bot_lib.backtest.adapter import strategy_signal_fn

    # Generate synthetic OHLCV
    import random
    random.seed(42 + hash(strategy_id) % 1000)
    base_price = 1.0800
    if "JPY" in symbol:
        base_price = 150.0
    elif "GBP" in symbol:
        base_price = 1.2600
    elif "XAU" in symbol:
        base_price = 2350.0
    elif "BTC" in symbol:
        base_price = 63000.0

    price = base_price
    ohlcv = []
    for idx in range(bars_count):
        volatility = price * 0.0008
        o = price
        h = o + abs(random.gauss(0, volatility))
        l = o - abs(random.gauss(0, volatility))
        c = o + random.gauss(0, volatility * 0.5)
        price = c
        hour = idx % 24
        day = idx // 24
        ohlcv.append({
            "time": "2026-01-{:02d}T{:02d}:00:00+00:00".format(max(1, day % 28 + 1), hour),
            "open": round(o, 5),
            "high": round(max(o, h, c), 5),
            "low": round(min(o, l, c), 5),
            "close": round(c, 5),
            "volume": random.randint(100, 5000),
        })

    # Merge config
    from bot_lib.backtest.engine import BacktestConfig
    cfg = BacktestConfig(
        initial_balance=float(user_config.get("initial_balance", 800.0)),
        risk_per_trade_pct=float(user_config.get("risk_per_trade_pct", 1.0)),
        sl_atr_mult=float(user_config.get("sl_atr_mult", defaults.get("sl_atr_mult", 1.5))),
        tp_atr_mult=float(user_config.get("tp_atr_mult", defaults.get("tp_atr_mult", 2.5))),
        commission_per_trade=float(user_config.get("commission", 0.10)),
        slippage_pct=float(user_config.get("slippage_pct", 0.0001)),
        warmup_bars=55,
        max_open_positions=1,
        min_score=float(user_config.get("min_score", defaults.get("min_score", 0.5))),
    )

    signal_fn = strategy_signal_fn(strategy_id)
    result = _run_backtest(ohlcv=ohlcv, signal_fn=signal_fn, config=cfg)

    # Add equity curve
    if result.get("ok") and result.get("trades"):
        equity = cfg.initial_balance
        eq_curve = [{"trade": 0, "equity": equity}]
        for i, t in enumerate(result["trades"]):
            equity += t["pnl"]
            eq_curve.append({"trade": i + 1, "equity": round(equity, 2)})
        result["equity_curve"] = eq_curve

    result["strategy"] = strategy_id
    result["symbol"] = symbol
    result["data_source"] = "synthetic"
    return result


class TelegramCommandPayload(BaseModel):
    """Inputs for POST /api/telegram/command."""

    name: str = Field(..., description="Slash-command name, e.g. /status.")
    user_id: Optional[str] = Field(default=None, description="Telegram user id.")
    args: dict = Field(default_factory=dict)
    confirm: bool = Field(default=False, description="Required True for state-mutating commands.")

    model_config = ConfigDict(extra="forbid")


@api_router.post("/telegram/command", dependencies=[Depends(require_token)])
async def telegram_command(payload: dict, db=Depends(get_db)):
    """Handle interactive Telegram commands: /status, /profit, /daily, /forcesell."""
    cmd = payload.get("command", "").strip().lower()

    if cmd in ("/status", "status"):
        items = await db.trades.find({"status": "open"}, {"_id": 0}).to_list(50)
        total_pnl = sum(t.get("pnl_usd", 0) or 0 for t in items)
        msg_lines = [
            "\U0001f4ca *Estado del Bot*",
            "Posiciones abiertas: `{}`".format(len(items)),
            "P&L flotante: `${:+.2f}`".format(total_pnl),
        ]
        for t in items[:5]:
            sym = t.get("symbol", "?")
            side = t.get("side", "?")
            pnl = t.get("pnl_usd", 0) or 0
            msg_lines.append("  \u2022 `{}` {} \u2192 ${:+.2f}".format(sym, side, pnl))
        msg = "\n".join(msg_lines)
        telegram_notifier.send(msg)
        return {"ok": True, "message": msg}

    elif cmd in ("/profit", "profit"):
        items = await db.trades.find({}, {"_id": 0}).to_list(2000)
        closed = [t for t in items if t.get("status") != "open"]
        total_pnl = sum(t.get("pnl_usd", 0) or 0 for t in closed)
        wins = len([t for t in closed if (t.get("pnl_usd", 0) or 0) > 0])
        losses = len([t for t in closed if (t.get("pnl_usd", 0) or 0) < 0])
        wr = (wins / len(closed) * 100) if closed else 0
        msg = "\U0001f4b0 *Resumen de Profit*\nTotal trades: `{}`\nWins: `{}` | Losses: `{}`\nWin Rate: `{:.1f}%`\nP&L Total: *${:+.2f}*".format(
            len(closed), wins, losses, wr, total_pnl
        )
        telegram_notifier.send(msg)
        return {"ok": True, "message": msg}

    elif cmd in ("/daily", "daily"):
        from datetime import datetime as _dt2, timezone as _tz2
        today = _dt2.now(_tz2.utc).strftime("%Y-%m-%d")
        items = await db.trades.find({"date": today}, {"_id": 0}).to_list(100)
        closed = [t for t in items if t.get("status") != "open"]
        today_pnl = sum(t.get("pnl_usd", 0) or 0 for t in closed)
        wins = len([t for t in closed if (t.get("pnl_usd", 0) or 0) > 0])
        losses = len([t for t in closed if (t.get("pnl_usd", 0) or 0) < 0])
        msg = "\U0001f4c5 *P&L de Hoy* ({})\nTrades cerrados: `{}`\nWins: `{}` | Losses: `{}`\nP&L Hoy: *${:+.2f}*".format(
            today, len(closed), wins, losses, today_pnl
        )
        telegram_notifier.send(msg)
        return {"ok": True, "message": msg}

    elif cmd.startswith(("/forcesell", "forcesell")):
        parts = cmd.split()
        if len(parts) < 2:
            return {"ok": False, "error": "Uso: /forcesell <ticket>"}
        ticket = parts[1]
        msg = "\u26a0\ufe0f Force-sell del ticket `{}` solicitado.".format(ticket)
        telegram_notifier.send(msg)
        return {"ok": True, "message": msg, "ticket": ticket, "action": "force_close_requested"}

    else:
        available = ["/status", "/profit", "/daily", "/forcesell <ticket>"]
        return {"ok": False, "error": "Comando desconocido: {}".format(cmd), "available": available}




# ═══════════════════════════════════════════════════════════════════
# Phase 3: Optimization, Walk-Forward, Monte Carlo
# ═══════════════════════════════════════════════════════════════════

@api_router.post("/optimize/run", dependencies=[Depends(require_token)])
async def optimize_run(payload: dict):
    """Run Optuna hyperparameter optimization for a strategy.

    Accepts: strategy_id, bars (optional, default 2000), n_trials (optional, default 50),
    metric (optional: expectancy|sharpe|profit_factor|total_pnl|win_rate)
    """
    import asyncio
    from bot_lib.backtest.optimizer import optimize_strategy

    strategy_id = payload.get("strategy_id", "trend_rider")
    bars_count = int(payload.get("bars", 2000))
    n_trials = min(int(payload.get("n_trials", 50)), 200)
    metric = payload.get("metric", "expectancy")

    # Generate synthetic OHLCV
    ohlcv = _generate_ohlcv(payload.get("symbol", "EURUSD"), bars_count)

    # Run in thread pool to not block event loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: optimize_strategy(strategy_id, ohlcv, n_trials=n_trials, metric=metric)
    )
    return result


@api_router.post("/optimize/walkforward", dependencies=[Depends(require_token)])
async def walk_forward_endpoint(payload: dict):
    """Run walk-forward analysis for a strategy.

    Accepts: strategy_id, bars (optional, default 3000), n_splits (optional, default 5)
    """
    import asyncio
    from bot_lib.backtest.optimizer import walk_forward

    strategy_id = payload.get("strategy_id", "trend_rider")
    bars_count = int(payload.get("bars", 3000))
    n_splits = min(int(payload.get("n_splits", 5)), 10)

    ohlcv = _generate_ohlcv(payload.get("symbol", "EURUSD"), bars_count)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: walk_forward(strategy_id, ohlcv, n_splits=n_splits)
    )
    return result


@api_router.post("/optimize/montecarlo", dependencies=[Depends(require_token)])
async def monte_carlo_endpoint(payload: dict):
    """Run Monte Carlo simulation on trade history.

    Accepts: n_simulations (default 1000), n_trades (optional), initial_balance (default 800)
    If no trade data provided, reads from research log.
    """
    from bot_lib.backtest.optimizer import monte_carlo
    from pathlib import Path as _P

    n_sims = min(int(payload.get("n_simulations", 1000)), 5000)
    n_trades = payload.get("n_trades")
    if n_trades is not None:
        n_trades = int(n_trades)
    initial_balance = float(payload.get("initial_balance", 800.0))

    # Get trade P&Ls from research log
    trade_pnls = []
    log_file = _P(os.path.expanduser(
        os.environ.get("LOG_DIR", "/opt/trading-bot/logs"))) / "trade_research.jsonl"

    if log_file.exists():
        for line in log_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("event") == "close":
                    pnl = rec.get("pnl_usd")
                    if pnl is not None:
                        trade_pnls.append(float(pnl))
            except Exception:
                continue

    # If provided in payload, use those
    if payload.get("trade_pnls"):
        trade_pnls = [float(p) for p in payload["trade_pnls"]]

    if len(trade_pnls) < 3:
        return {"error": "Need at least 3 closed trades for Monte Carlo. Currently: {}".format(len(trade_pnls))}

    result = monte_carlo(
        trade_pnls=trade_pnls,
        n_simulations=n_sims,
        n_trades=n_trades,
        initial_balance=initial_balance,
    )
    return result


def _generate_ohlcv(symbol: str = "EURUSD", bars: int = 1000) -> list:
    """Generate synthetic OHLCV data for backtesting/optimization."""
    import random as _rng
    _rng.seed(42 + hash(symbol) % 1000)
    base_price = 1.0800
    if "JPY" in symbol:
        base_price = 150.0
    elif "GBP" in symbol:
        base_price = 1.2600
    elif "XAU" in symbol:
        base_price = 2350.0
    elif "BTC" in symbol:
        base_price = 63000.0

    price = base_price
    ohlcv = []
    for idx in range(bars):
        volatility = price * 0.0008
        o = price
        h = o + abs(_rng.gauss(0, volatility))
        l = o - abs(_rng.gauss(0, volatility))
        c = o + _rng.gauss(0, volatility * 0.5)
        price = c
        hour = idx % 24
        day = idx // 24
        ohlcv.append({
            "time": "2026-01-{:02d}T{:02d}:00:00+00:00".format(max(1, day % 28 + 1), hour),
            "open": round(o, 5),
            "high": round(max(o, h, c), 5),
            "low": round(min(o, l, c), 5),
            "close": round(c, 5),
            "volume": _rng.randint(100, 5000),
        })
    return ohlcv


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
