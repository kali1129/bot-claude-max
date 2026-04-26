"""Backend API tests for Futures Trading Plan Dashboard."""
import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://futures-capital-80.preview.emergentagent.com").rstrip("/")
# Try frontend env if not set
if not BASE_URL or "preview" not in BASE_URL:
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().rstrip("/")
    except Exception:
        pass

API = f"{BASE_URL}/api"


@pytest.fixture(scope="session")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ============ Plan/Root ============
class TestPlanEndpoints:
    def test_root(self, client):
        r = client.get(f"{API}/")
        assert r.status_code == 200
        d = r.json()
        assert d["capital"] == 800
        assert "message" in d

    def test_plan_data(self, client):
        r = client.get(f"{API}/plan/data")
        assert r.status_code == 200
        d = r.json()
        assert d["config"]["capital"] == 800
        assert len(d["mcps"]) == 4
        assert len(d["strategies"]) == 6
        assert len(d["rules"]) == 20
        assert len(d["mindset"]) == 6
        assert len(d["setup_guide"]) == 9
        # checklist with 3 sections
        cl = d["checklist"]
        assert "pre_market" in cl and "during_market" in cl and "post_market" in cl
        assert len(cl["pre_market"]) == 7
        assert len(cl["during_market"]) == 6
        assert len(cl["post_market"]) == 5

    def test_plan_markdown(self, client):
        r = client.get(f"{API}/plan/markdown")
        assert r.status_code == 200
        text = r.text
        assert "PLAN OPERATIVO" in text
        assert "ARQUITECTURA DE MCPs" in text
        assert "ESTRATEGIAS" in text
        assert "CHECKLIST" in text


# ============ Risk Calc ============
class TestRiskCalc:
    def test_risk_calc_basic(self, client):
        payload = {
            "balance": 800, "risk_pct": 1, "entry": 1.0850, "stop_loss": 1.0830,
            "pip_value": 10, "pip_size": 0.0001, "lot_step": 0.01, "min_lot": 0.01, "max_lot": 0.5,
        }
        r = client.post(f"{API}/risk/calc", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert d["lots"] == 0.03
        assert d["risk_dollars"] == 6.0
        assert d["risk_pct_actual"] == 0.75
        assert d["sl_pips"] == 20.0

    def test_risk_calc_warning_exceeds_rule(self, client):
        payload = {
            "balance": 800, "risk_pct": 2, "entry": 1.0850, "stop_loss": 1.0830,
            "pip_value": 10, "pip_size": 0.0001, "lot_step": 0.01, "min_lot": 0.01, "max_lot": 0.5,
        }
        r = client.post(f"{API}/risk/calc", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert any("excede" in w.lower() or "1%" in w for w in d["warnings"])

    def test_risk_calc_invalid_entry_eq_sl(self, client):
        payload = {
            "balance": 800, "risk_pct": 1, "entry": 1.0850, "stop_loss": 1.0850,
            "pip_value": 10, "pip_size": 0.0001,
        }
        r = client.post(f"{API}/risk/calc", json=payload)
        assert r.status_code == 400


# ============ Journal ============
class TestJournal:
    created_ids = []

    def test_create_trade(self, client):
        payload = {
            "date": "2026-01-15", "symbol": "TEST_EURUSD", "side": "buy", "strategy": "orb",
            "entry": 1.0850, "exit": 1.0890, "sl": 1.0830, "tp": 1.0890,
            "lots": 0.03, "pnl_usd": 12.0, "r_multiple": 2.0, "status": "closed-win",
            "notes": "test trade",
        }
        r = client.post(f"{API}/journal", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert d["symbol"] == "TEST_EURUSD"
        assert "id" in d
        TestJournal.created_ids.append(d["id"])

    def test_list_trades_no_mongo_id(self, client):
        r = client.get(f"{API}/journal")
        assert r.status_code == 200
        items = r.json()
        assert isinstance(items, list)
        for it in items:
            assert "_id" not in it

    def test_create_second_trade_for_stats(self, client):
        payload = {
            "date": "2026-01-15", "symbol": "TEST_NAS100", "side": "sell", "strategy": "ema-pullback",
            "entry": 17000, "exit": 16980, "sl": 17030, "tp": 16940,
            "lots": 0.1, "pnl_usd": -8.0, "r_multiple": -1.0, "status": "closed-loss",
            "notes": "test loss",
        }
        r = client.post(f"{API}/journal", json=payload)
        assert r.status_code == 200
        TestJournal.created_ids.append(r.json()["id"])

    def test_journal_stats(self, client):
        r = client.get(f"{API}/journal/stats")
        assert r.status_code == 200
        d = r.json()
        assert "win_rate" in d
        assert "expectancy" in d
        assert "equity_curve" in d
        assert "today" in d
        assert "can_trade" in d["today"]
        assert isinstance(d["equity_curve"], list)
        assert d["total_trades"] >= 2

    def test_delete_trade(self, client):
        if not TestJournal.created_ids:
            pytest.skip("no created trades")
        for tid in TestJournal.created_ids:
            r = client.delete(f"{API}/journal/{tid}")
            assert r.status_code == 200

    def test_delete_nonexistent(self, client):
        r = client.delete(f"{API}/journal/non-existing-id-12345")
        assert r.status_code == 404


# ============ Checklist ============
class TestChecklist:
    def test_get_empty_checklist(self, client):
        r = client.get(f"{API}/checklist/2030-12-31")
        assert r.status_code == 200
        d = r.json()
        assert d["checked_ids"] == []
        assert d["date"] == "2030-12-31"

    def test_post_and_get_checklist(self, client):
        payload = {"date": "2030-12-30", "checked_ids": ["pm1", "pm2", "dm1"]}
        r = client.post(f"{API}/checklist", json=payload)
        assert r.status_code == 200
        d = r.json()
        assert set(d["checked_ids"]) == {"pm1", "pm2", "dm1"}

        r2 = client.get(f"{API}/checklist/2030-12-30")
        assert r2.status_code == 200
        d2 = r2.json()
        assert set(d2["checked_ids"]) == {"pm1", "pm2", "dm1"}

    def test_upsert_checklist(self, client):
        payload = {"date": "2030-12-30", "checked_ids": ["po1"]}
        r = client.post(f"{API}/checklist", json=payload)
        assert r.status_code == 200
        r2 = client.get(f"{API}/checklist/2030-12-30")
        assert set(r2.json()["checked_ids"]) == {"po1"}
