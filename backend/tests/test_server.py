"""In-process tests for backend/server.py using TestClient + mongomock-motor.

These tests do NOT require Mongo nor a running server. They run on every CI
build to catch regressions before the integration suite (``backend_test.py``)
hits the deployed environment.
"""
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mongomock_motor import AsyncMongoMockClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import server  # noqa: E402


@pytest.fixture()
def client():
    mock = AsyncMongoMockClient()
    db = mock["test_dashboard"]
    server.state.mongo_client = mock
    server.state.db = db
    server.app.dependency_overrides[server.get_db] = lambda: db
    with TestClient(server.app) as c:
        yield c
    server.app.dependency_overrides.clear()
    server.state.mongo_client = None
    server.state.db = None


# ----- Plan endpoints -----

def test_root(client):
    r = client.get("/api/")
    assert r.status_code == 200
    body = r.json()
    # ``capital`` is now dynamic (live MT5 balance when reachable, else
    # falls back to plan_content.CAPITAL = 800). ``capital_source`` tells
    # the caller which path was taken.
    assert "capital" in body
    assert body["capital_source"] in {"mt5", "fallback"}


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_plan_data(client):
    r = client.get("/api/plan/data")
    assert r.status_code == 200
    d = r.json()
    # capital_target is the static $800 plan rule; capital is live.
    assert d["config"]["capital_target"] == 800
    assert d["config"]["capital_source"] in {"mt5", "fallback"}
    assert len(d["mcps"]) == 4
    assert len(d["strategies"]) == 6
    assert len(d["rules"]) == 20


def test_plan_markdown(client):
    r = client.get("/api/plan/markdown")
    assert r.status_code == 200
    assert "PLAN OPERATIVO" in r.text


# ----- Risk calc -----

def test_risk_calc_basic(client):
    r = client.post("/api/risk/calc", json={
        "balance": 800, "risk_pct": 1, "entry": 1.0850, "stop_loss": 1.0830,
        "pip_value": 10, "pip_size": 0.0001,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["lots"] == 0.03
    assert d["risk_dollars"] == 6.0


def test_risk_calc_warning_exceeds_rule(client):
    r = client.post("/api/risk/calc", json={
        "balance": 800, "risk_pct": 2, "entry": 1.0850, "stop_loss": 1.0830,
        "pip_value": 10, "pip_size": 0.0001,
    })
    assert r.status_code == 200
    assert any("excede" in w.lower() for w in r.json()["warnings"])


def test_risk_calc_invalid_entry_eq_sl(client):
    r = client.post("/api/risk/calc", json={
        "balance": 800, "risk_pct": 1, "entry": 1.0850, "stop_loss": 1.0850,
        "pip_value": 10, "pip_size": 0.0001,
    })
    assert r.status_code == 422  # pydantic validation


def test_risk_calc_negative_balance(client):
    r = client.post("/api/risk/calc", json={
        "balance": -100, "risk_pct": 1, "entry": 1.08, "stop_loss": 1.07,
    })
    assert r.status_code == 422


def test_risk_calc_risk_pct_zero(client):
    r = client.post("/api/risk/calc", json={
        "balance": 800, "risk_pct": 0, "entry": 1.08, "stop_loss": 1.07,
    })
    assert r.status_code == 422


# Property: actual_risk_pct never exceeds requested risk_pct (within rounding).
@pytest.mark.parametrize("balance,risk_pct,entry,sl,pip_size,pip_value", [
    (800, 1.0, 1.0850, 1.0830, 0.0001, 10),
    (800, 0.5, 1.0850, 1.0810, 0.0001, 10),
    (1000, 1.0, 18000, 17970, 1.0, 1.0),
    (500, 0.75, 1.0850, 1.0790, 0.0001, 10),
])
def test_risk_calc_never_exceeds_requested(client, balance, risk_pct, entry, sl, pip_size, pip_value):
    r = client.post("/api/risk/calc", json={
        "balance": balance, "risk_pct": risk_pct, "entry": entry, "stop_loss": sl,
        "pip_value": pip_value, "pip_size": pip_size,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["risk_pct_actual"] <= risk_pct + 0.001


def test_risk_calc_refuses_when_below_min_lot(client):
    # 1% of $50 = $0.50 budget, SL 20 pips at $10/pip = $200 needed for 1 lot.
    # Min_lot 0.01 → $2 risk. Budget < min → refuse.
    r = client.post("/api/risk/calc", json={
        "balance": 50, "risk_pct": 1, "entry": 1.0850, "stop_loss": 1.0830,
        "pip_value": 10, "pip_size": 0.0001,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["lots"] == 0.0
    assert any("mínimo" in w.lower() or "minimo" in w.lower() for w in d["warnings"])


# ----- Journal CRUD -----

def _trade(**overrides):
    base = {
        "date": "2026-01-15", "symbol": "EURUSD", "side": "buy", "strategy": "orb",
        "entry": 1.0850, "exit": 1.0890, "sl": 1.0830, "tp": 1.0890,
        "lots": 0.03, "pnl_usd": 12.0, "r_multiple": 2.0, "status": "closed-win",
        "notes": "test",
    }
    base.update(overrides)
    return base


def test_journal_create_and_list(client):
    r = client.post("/api/journal", json=_trade())
    assert r.status_code == 200
    tid = r.json()["id"]

    r2 = client.get("/api/journal")
    assert r2.status_code == 200
    items = r2.json()
    assert any(t["id"] == tid for t in items)
    for t in items:
        assert "_id" not in t


def test_journal_idempotency(client):
    payload = _trade(client_id="mt5-deal-12345")
    r1 = client.post("/api/journal", json=payload)
    r2 = client.post("/api/journal", json=payload)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    items = client.get("/api/journal").json()
    assert sum(1 for t in items if t.get("client_id") == "mt5-deal-12345") == 1


def test_journal_update(client):
    tid = client.post("/api/journal", json=_trade(status="open", pnl_usd=0.0)).json()["id"]
    r = client.put(f"/api/journal/{tid}", json=_trade(status="closed-win", pnl_usd=15.0, exit=1.09))
    assert r.status_code == 200
    assert r.json()["pnl_usd"] == 15.0
    assert r.json()["status"] == "closed-win"


def test_journal_delete(client):
    tid = client.post("/api/journal", json=_trade()).json()["id"]
    r = client.delete(f"/api/journal/{tid}")
    assert r.status_code == 200
    r2 = client.delete(f"/api/journal/{tid}")
    assert r2.status_code == 404


def test_journal_validation_blocks_negative_entry(client):
    r = client.post("/api/journal", json=_trade(entry=-1))
    assert r.status_code == 422


def test_journal_validation_blocks_bad_date(client):
    r = client.post("/api/journal", json=_trade(date="15-01-2026"))
    assert r.status_code == 422


def test_journal_stats(client):
    client.post("/api/journal", json=_trade(symbol="A", pnl_usd=12, r_multiple=2.0, status="closed-win"))
    client.post("/api/journal", json=_trade(symbol="B", pnl_usd=-8, r_multiple=-1.0, status="closed-loss"))
    r = client.get("/api/journal/stats")
    assert r.status_code == 200
    d = r.json()
    assert d["total_trades"] == 2
    assert d["wins"] == 1
    assert d["losses"] == 1
    assert "today" in d
    assert "equity_curve" in d


# ----- Discipline -----

def test_discipline_score_clean(client):
    client.post("/api/journal", json=_trade(pnl_usd=12, r_multiple=2.0, status="closed-win"))
    client.post("/api/journal", json=_trade(pnl_usd=-8, r_multiple=-1.0, status="closed-loss"))
    r = client.get("/api/discipline/score")
    assert r.status_code == 200
    d = r.json()
    assert d["adherence_pct"] == 100.0
    assert d["violations"] == []


def test_discipline_score_detects_sl_runaway(client):
    client.post("/api/journal", json=_trade(pnl_usd=-25, r_multiple=-2.5, status="closed-loss"))
    r = client.get("/api/discipline/score")
    d = r.json()
    assert d["adherence_pct"] < 100
    assert any(v["rule"] == "SL_RUNAWAY" for v in d["violations"])


# ----- Checklist -----

def test_checklist_empty(client):
    r = client.get("/api/checklist/2030-01-01")
    assert r.status_code == 200
    assert r.json()["checked_ids"] == []


def test_checklist_invalid_date(client):
    r = client.get("/api/checklist/notadate")
    assert r.status_code == 400


def test_checklist_upsert(client):
    payload = {"date": "2030-12-30", "checked_ids": ["a", "b"]}
    r = client.post("/api/checklist", json=payload)
    assert r.status_code == 200
    r2 = client.get("/api/checklist/2030-12-30")
    assert set(r2.json()["checked_ids"]) == {"a", "b"}

    r3 = client.post("/api/checklist", json={"date": "2030-12-30", "checked_ids": ["c"]})
    assert r3.status_code == 200
    r4 = client.get("/api/checklist/2030-12-30")
    assert set(r4.json()["checked_ids"]) == {"c"}


# ----- Auth -----

def test_auth_blocks_writes_when_token_set(monkeypatch, client):
    monkeypatch.setattr(server, "DASHBOARD_TOKEN", "s3cr3t")
    r = client.post("/api/journal", json=_trade())
    assert r.status_code == 401
    r2 = client.post(
        "/api/journal", json=_trade(),
        headers={"Authorization": "Bearer s3cr3t"},
    )
    assert r2.status_code == 200


# ----- Docs -----

def test_docs_list(client):
    r = client.get("/api/docs")
    assert r.status_code == 200
    docs = r.json()["docs"]
    assert len(docs) >= 7
    ids = {d["id"] for d in docs}
    assert "00-overview" in ids
    assert "02-mcp-trading" in ids


def test_docs_get_existing(client):
    r = client.get("/api/docs/00-overview")
    assert r.status_code == 200
    assert "Arquitectura General" in r.text


def test_docs_get_unknown(client):
    r = client.get("/api/docs/999-missing")
    assert r.status_code == 404
