from fastapi import FastAPI, APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Literal
import uuid
from datetime import datetime, timezone, date

from plan_content import (
    CAPITAL,
    MAX_RISK_PER_TRADE_PCT,
    MAX_DAILY_LOSS_PCT,
    MAX_CONSECUTIVE_LOSSES,
    MIN_RR,
    MCPS,
    STRATEGIES,
    STRICT_RULES,
    CHECKLIST_TEMPLATE,
    MINDSET_PRINCIPLES,
    SETUP_GUIDE,
    build_markdown,
)


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI(title="Futures Trading Plan Dashboard")
api_router = APIRouter(prefix="/api")


# ============ MODELS ============

class TradeEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: str  # YYYY-MM-DD
    symbol: str
    side: Literal["buy", "sell"]
    strategy: str
    entry: float
    exit: Optional[float] = None
    sl: float
    tp: Optional[float] = None
    lots: float
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    status: Literal["open", "closed-win", "closed-loss", "closed-be"] = "open"
    notes: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TradeEntryCreate(BaseModel):
    date: str
    symbol: str
    side: Literal["buy", "sell"]
    strategy: str
    entry: float
    exit: Optional[float] = None
    sl: float
    tp: Optional[float] = None
    lots: float
    pnl_usd: float = 0.0
    r_multiple: float = 0.0
    status: Literal["open", "closed-win", "closed-loss", "closed-be"] = "open"
    notes: str = ""


class ChecklistState(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    date: str  # YYYY-MM-DD
    checked_ids: List[str] = []
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ChecklistUpdate(BaseModel):
    date: str
    checked_ids: List[str]


class RiskCalcInput(BaseModel):
    balance: float
    risk_pct: float
    entry: float
    stop_loss: float
    pip_value: float = 10.0  # USD por pip por lote estándar (forex majors ~$10)
    pip_size: float = 0.0001  # 0.0001 forex, 0.01 JPY, 0.1 oro, 1.0 índices
    lot_step: float = 0.01
    min_lot: float = 0.01
    max_lot: float = 0.5


# ============ ENDPOINTS ============

@api_router.get("/")
async def root():
    return {"message": "Trading Plan API", "capital": CAPITAL}


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


# ----- Trade Journal -----

@api_router.post("/journal", response_model=TradeEntry)
async def create_trade(trade: TradeEntryCreate):
    obj = TradeEntry(**trade.model_dump())
    await db.trades.insert_one(obj.model_dump())
    return obj


@api_router.get("/journal", response_model=List[TradeEntry])
async def list_trades(limit: int = 200):
    items = await db.trades.find({}, {"_id": 0}).sort("created_at", -1).to_list(limit)
    return items


@api_router.delete("/journal/{trade_id}")
async def delete_trade(trade_id: str):
    res = await db.trades.delete_one({"id": trade_id})
    if res.deleted_count == 0:
        raise HTTPException(404, "trade not found")
    return {"ok": True}


@api_router.get("/journal/stats")
async def journal_stats():
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

    # Equity curve (ordered by created_at asc)
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

    # Today's stats
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


# ----- Checklist -----

@api_router.get("/checklist/{day}", response_model=ChecklistState)
async def get_checklist(day: str):
    doc = await db.checklists.find_one({"date": day}, {"_id": 0})
    if not doc:
        return ChecklistState(date=day, checked_ids=[])
    return doc


@api_router.post("/checklist", response_model=ChecklistState)
async def update_checklist(payload: ChecklistUpdate):
    obj = ChecklistState(date=payload.date, checked_ids=payload.checked_ids)
    doc = obj.model_dump()
    await db.checklists.update_one(
        {"date": payload.date},
        {"$set": doc},
        upsert=True,
    )
    return obj


# ----- Risk Calculator -----

@api_router.post("/risk/calc")
async def risk_calculate(inp: RiskCalcInput):
    if inp.balance <= 0 or inp.entry <= 0 or inp.stop_loss <= 0:
        raise HTTPException(400, "valores positivos requeridos")
    if inp.entry == inp.stop_loss:
        raise HTTPException(400, "entry y SL no pueden ser iguales")

    risk_dollars = inp.balance * (inp.risk_pct / 100.0)
    sl_distance = abs(inp.entry - inp.stop_loss)
    sl_pips = sl_distance / inp.pip_size if inp.pip_size > 0 else sl_distance
    if sl_pips <= 0 or inp.pip_value <= 0:
        raise HTTPException(400, "configuración de pip inválida")

    raw_lots = risk_dollars / (sl_pips * inp.pip_value)

    # Snap to lot_step
    steps = int(raw_lots / inp.lot_step)
    snapped = max(inp.min_lot, steps * inp.lot_step)
    snapped = round(snapped, 4)

    capped = min(snapped, inp.max_lot)
    capped = round(capped, 4)

    actual_risk = capped * sl_pips * inp.pip_value
    actual_risk_pct = actual_risk / inp.balance * 100

    warnings = []
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
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
