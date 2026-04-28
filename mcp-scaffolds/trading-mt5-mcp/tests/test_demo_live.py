"""Live integration tests against the connected MT5 demo account.

Skipped automatically when MT5 isn't reachable. Each test exercises one
read tool against real broker data + one paper-mode write to verify the
full place_order pipeline (guards + idempotency + logger) without ever
calling order_send.
"""
import os
from datetime import datetime, timezone

import pytest

import server  # the MCP module — loads .env, sets MODE=paper via conftest


# ----- skip the suite if MT5 isn't reachable -----

def _ensure_or_skip():
    res = server.connection.ensure()
    if not res.get("connected"):
        pytest.skip(f"MT5 not reachable: {res.get('error')}")
    return res


@pytest.fixture(scope="module", autouse=True)
def mt5_session():
    info = _ensure_or_skip()
    yield info


# ============ Read-only tools ============

def test_health_reports_paper_mode():
    h = server.health()
    assert h["mode"] == "paper"
    assert h["version"] == server.__version__
    assert h["connected"] is True


def test_account_info_returns_demo_account():
    acc = server.get_account_info()
    assert acc["balance"] >= 0  # demo can have any balance, just sanity
    assert acc["currency"]
    assert acc["server"]
    assert isinstance(acc["trade_allowed"], bool)


def test_get_open_positions_is_a_list():
    res = server.get_open_positions()
    assert "positions" in res
    assert isinstance(res["positions"], list)


def test_get_rates_eurusd_m15():
    res = server.get_rates("EURUSD", "M15", 50)
    if "ok" in res and res["ok"] is False:
        pytest.skip(f"EURUSD not in MarketWatch: {res.get('detail')}")
    assert "bars" in res
    assert len(res["bars"]) > 0
    bar = res["bars"][0]
    for k in ("time", "open", "high", "low", "close", "volume"):
        assert k in bar


def test_get_rates_rejects_bad_timeframe():
    res = server.get_rates("EURUSD", "ZZZ", 10)
    assert res["ok"] is False
    assert res["reason"] == "BAD_TIMEFRAME"


def test_get_tick_eurusd():
    res = server.get_tick("EURUSD")
    if "ok" in res and res["ok"] is False:
        pytest.skip(f"EURUSD tick unavailable: {res.get('detail')}")
    assert res["bid"] > 0
    assert res["ask"] >= res["bid"]


def test_get_trade_history_is_a_list():
    res = server.get_trade_history(7)
    assert "deals" in res
    assert isinstance(res["deals"], list)


def test_calculate_lot_size_eurusd():
    res = server.calculate_lot_size("EURUSD", sl_pips=20, risk_pct=1.0)
    if "ok" in res and res["ok"] is False:
        pytest.skip(f"EURUSD sizing unavailable: {res.get('detail')}")
    assert res["lots"] > 0
    assert res["risk_dollars"] > 0


# ============ Paper-mode place_order (full pipeline, MT5 untouched) ============
#
# These tests isolate place_order from the *current* state of the demo
# account: if you happen to have an open position right now, the
# MAX_POSITIONS guard would (correctly) reject any new order. We monkeypatch
# the position lookup to return an empty list so the pipeline can be
# exercised end-to-end. The kill-switch and the live MT5 read tools above
# are NOT mocked.

@pytest.fixture
def isolated_place_order(monkeypatch, tmp_path):
    server.idempotency.reset()
    # Redirect HALT_FILE to a non-existent tmp path so a real .HALT from
    # prior trading doesn't bleed into unit tests.
    monkeypatch.setattr(server.halt_mod, "HALT_FILE", str(tmp_path / ".HALT"))
    # Fix UTC hour to 12 so the blackout guard (22:00-07:00) never fires.
    monkeypatch.setattr(server, "_utc_hour", lambda: 12)
    monkeypatch.setattr(server, "_open_positions", lambda: [])
    monkeypatch.setattr(server, "_paper_open_positions", lambda: [])
    monkeypatch.setattr(server, "_account_state", lambda: {
        "balance": 800.0, "equity": 800.0, "daily_pl_usd": 0.0,
        "daily_pl_pct": 0.0, "currency": "USD", "server": "test",
        "login": 0, "leverage": 30, "margin": 0.0, "margin_free": 800.0,
        "margin_level": 0.0, "profit": 0.0, "trade_allowed": True,
    })
    yield


def test_place_order_paper_happy_path(isolated_place_order):
    tick = server.get_tick("EURUSD")
    if "ok" in tick and tick["ok"] is False:
        pytest.skip("EURUSD tick unavailable")
    entry = tick["ask"]
    sl = round(entry - 0.0020, 5)   # 20 pips SL
    tp = round(entry + 0.0040, 5)   # 40 pips TP → R:R 1:2
    coid = "test-paper-happy-001"
    res = server.place_order(
        symbol="EURUSD", side="buy", lots=0.01,
        sl=sl, tp=tp, comment="test", client_order_id=coid,
    )
    assert res["ok"] is True, res
    assert res["mode"] == "paper"
    assert res["ticket"]


def test_place_order_idempotent_replay(isolated_place_order):
    tick = server.get_tick("EURUSD")
    if "ok" in tick and tick["ok"] is False:
        pytest.skip("EURUSD tick unavailable")
    entry = tick["ask"]
    sl = round(entry - 0.0020, 5)
    tp = round(entry + 0.0040, 5)
    coid = "test-idempotent-001"
    r1 = server.place_order("EURUSD", "buy", 0.01, sl, tp, "test", coid)
    r2 = server.place_order("EURUSD", "buy", 0.01, sl, tp, "test", coid)
    assert r1["ok"] is True
    assert r2["ok"] is True
    assert r1["ticket"] == r2["ticket"]
    assert r2.get("idempotent_replay") is True


def test_place_order_rejects_low_rr(isolated_place_order):
    tick = server.get_tick("EURUSD")
    if "ok" in tick and tick["ok"] is False:
        pytest.skip("EURUSD tick unavailable")
    entry = tick["ask"]
    sl = round(entry - 0.0020, 5)
    tp = round(entry + 0.0020, 5)  # 1:1, below MIN_RR
    res = server.place_order("EURUSD", "buy", 0.01, sl, tp, "test", "test-rr-001")
    assert res["ok"] is False
    assert res["reason"] == "RR_TOO_LOW"


def test_place_order_rejects_when_halted(monkeypatch, tmp_path):
    server.idempotency.reset()
    fake_halt = tmp_path / ".HALT"
    fake_halt.write_text('{"reason": "test halt"}')
    monkeypatch.setattr(server.halt_mod, "HALT_FILE", str(fake_halt))
    tick = server.get_tick("EURUSD")
    if "ok" in tick and tick["ok"] is False:
        pytest.skip("EURUSD tick unavailable")
    entry = tick["ask"]
    sl = round(entry - 0.0020, 5)
    tp = round(entry + 0.0040, 5)
    res = server.place_order("EURUSD", "buy", 0.01, sl, tp, "test", "test-halt-001")
    assert res["ok"] is False
    assert res["reason"] == "HALTED"
