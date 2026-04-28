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
        os.environ.get("LOG_DIR", "~/mcp/logs"))) / "trade_research.jsonl"

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
        os.environ.get("LOG_DIR", "~/mcp/logs"))) / "trade_research.jsonl"

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
    return mt5_bridge.halt_status()


@api_router.post("/halt", dependencies=[Depends(require_token)])
async def halt_post(payload: HaltPayload):
    res = mt5_bridge.halt_set(payload.reason)
    try:
        telegram_notifier.notify_halt(payload.reason)
    except Exception:  # noqa: BLE001 — never let TG error break the API
        pass
    return res


@api_router.delete("/halt", dependencies=[Depends(require_token)])
async def halt_delete():
    res = mt5_bridge.halt_clear()
    try:
        telegram_notifier.notify_resume()
    except Exception:  # noqa: BLE001
        pass
    return res


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
    return bot_bridge.set_config(payload.updates)


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


class TelegramCommandPayload(BaseModel):
    """Inputs for POST /api/telegram/command."""

    name: str = Field(..., description="Slash-command name, e.g. /status.")
    user_id: Optional[str] = Field(default=None, description="Telegram user id.")
    args: dict = Field(default_factory=dict)
    confirm: bool = Field(default=False, description="Required True for state-mutating commands.")

    model_config = ConfigDict(extra="forbid")


@api_router.post("/telegram/command", dependencies=[Depends(require_token)])
def telegram_command(payload: TelegramCommandPayload):
    """Dispatch a Telegram-style operator command through the policy gate.

    Allowed user IDs come from env `TELEGRAM_ALLOWED_USER_IDS` (comma-separated).
    Handlers default to safe stubs; a production wiring step replaces them with
    real bridges to risk-mcp / trading-mt5-mcp.
    """
    allowed_raw = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
    allowed = tuple(s.strip() for s in allowed_raw.split(",") if s.strip())

    request = _CommandRequest.from_mapping(payload.model_dump())
    return _dispatch_command(
        request,
        handlers=_stub_handlers(),
        allowed_user_ids=allowed,
    )


@api_router.get("/quality/score")
def quality_score():
    """Return a unified quality / readiness report from selfcheck.

    Useful for the dashboard: aggregates env, rules, kill-switch, and
    backend bind checks into one rating with traffic-light status.
    """
    return _run_selfcheck()


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)
