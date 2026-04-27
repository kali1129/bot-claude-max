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
import logging
import os
import secrets
import uuid

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.responses import PlainTextResponse
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.middleware.cors import CORSMiddleware

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


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

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
        log.info("connected to mongo db=%s", db_name)
    yield
    if state.mongo_client is not None:
        state.mongo_client.close()
        log.info("mongo connection closed")


app = FastAPI(title="Futures Trading Plan Dashboard", lifespan=lifespan)
api_router = APIRouter(prefix="/api")


# ============ AUTH ============
# Single-tenant local dashboard: optional bearer token on write endpoints.
# Set DASHBOARD_TOKEN in .env to enable. Empty/unset → auth disabled (dev mode).

DASHBOARD_TOKEN = os.environ.get("DASHBOARD_TOKEN", "").strip()


def require_token(authorization: Optional[str] = Header(default=None)):
    if not DASHBOARD_TOKEN:
        return
    expected = f"Bearer {DASHBOARD_TOKEN}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, "missing or invalid bearer token")


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

@api_router.get("/")
async def root():
    return {"message": "Trading Plan API", "capital": CAPITAL}


@api_router.get("/health")
async def health():
    db_ok = state.db is not None
    return {"ok": True, "db": db_ok, "auth": bool(DASHBOARD_TOKEN)}


@api_router.get("/plan/data")
async def get_plan_data():
    return {
        "config": {
            "capital": CAPITAL,
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

    closed_sorted = sorted(closed, key=lambda t: t["created_at"])
    equity = []
    running = CAPITAL
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
    today_pnl_pct = (today_pnl / CAPITAL * 100) if CAPITAL else 0.0
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
        "current_equity": round(CAPITAL + total_pnl, 2),
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

@api_router.get("/discipline/score")
async def discipline_score(db=Depends(get_db)):
    """Adherence score: percentage of closed trades that obey hard rules.

    Penalises: r_multiple < -1.0 (sl runaway), risk > MAX_RISK_PER_TRADE_PCT
    (inferred via lots * sl distance vs balance — proxy: r_multiple of losers
    must be ≥ -1.05). Rule-of-thumb metric, not authoritative.
    """
    items = await db.trades.find({}, {"_id": 0}).to_list(2000)
    closed = [t for t in items if t["status"] != "open"]
    if not closed:
        return {"adherence_pct": 100.0, "violations": [], "checked": 0}
    violations = []
    for t in closed:
        if t["pnl_usd"] < 0 and t["r_multiple"] < -1.05:
            violations.append({"id": t["id"], "rule": "SL_RUNAWAY", "r": t["r_multiple"]})
    pct = round((1 - len(violations) / len(closed)) * 100, 1)
    return {"adherence_pct": pct, "violations": violations, "checked": len(closed)}


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


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
