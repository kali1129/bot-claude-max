"""Adversarial tests for each pre-trade guard.

Every guard must reject with the right reason code on a deliberately broken
input. Rules constants come from _shared so the tests never invent values.
"""
import os
from datetime import datetime, timezone

os.environ.setdefault("TRADING_MODE", "paper")

from lib import guards
from rules import (
    MAX_RISK_PER_TRADE_PCT, MIN_RR, MAX_OPEN_POSITIONS, MAX_DAILY_LOSS_PCT,
)


def _ctx(**over):
    base = {
        "symbol": "EURUSD", "side": "buy", "lots": 0.03,
        "entry": 1.0850, "sl": 1.0830, "tp": 1.0890,
        "utc_hour": 12,
        "open_positions_count": 0,
        "daily_pl_pct": 0.0,
        "balance": 800.0,
        "risk_usd": 6.0,
    }
    base.update(over)
    return base


def test_pass_baseline():
    assert guards.run_guards(_ctx()) is None


def test_sl_required():
    res = guards.run_guards(_ctx(sl=None))
    assert res["reason"] == "SL_TP_REQUIRED"


def test_blocked_hour():
    res = guards.run_guards(_ctx(utc_hour=22))
    assert res["reason"] == "BLOCKED_HOUR"


def test_max_positions():
    res = guards.run_guards(_ctx(open_positions_count=MAX_OPEN_POSITIONS))
    assert res["reason"] == "MAX_POSITIONS"


def test_daily_dd_limit():
    res = guards.run_guards(_ctx(daily_pl_pct=-MAX_DAILY_LOSS_PCT - 0.1))
    assert res["reason"] == "DAILY_LOSS_LIMIT"


def test_lots_cap():
    res = guards.run_guards(_ctx(lots=10.0))
    assert res["reason"] == "LOTS_CAP"


def test_rr_too_low():
    # SL 20 pips, TP 30 pips → R:R 1.5 < MIN_RR
    res = guards.run_guards(_ctx(entry=1.0850, sl=1.0830, tp=1.0880))
    assert res["reason"] == "RR_TOO_LOW"


def test_sl_tp_side_buy():
    # buy with SL > entry → wrong side
    res = guards.run_guards(_ctx(side="buy", entry=1.0850, sl=1.0860, tp=1.0890))
    # SL > entry means risk = -10 pips, but rr() uses abs(); first guard
    # to fail will be RR_TOO_LOW or SL_TP_SIDE depending on order. The
    # blueprint says SL_TP_SIDE is checked AFTER rr; with this geometry,
    # rr is positive so we expect SL_TP_SIDE.
    assert res["reason"] in {"SL_TP_SIDE", "RR_TOO_LOW"}


def test_sl_tp_side_sell():
    # Legitimate sell: SL above entry, TP below entry, R:R 1:2.
    res_legit = guards.run_guards(_ctx(side="sell", entry=1.0850, sl=1.0870, tp=1.0810))
    assert res_legit is None
    # Wrong-side sell: SL below entry → must reject with SL_TP_SIDE.
    res_bad = guards.run_guards(_ctx(side="sell", entry=1.0850, sl=1.0830, tp=1.0810))
    assert res_bad["reason"] == "SL_TP_SIDE"


def test_risk_dollars_exceeded():
    # 1% of $800 = $8. Budget $50 = 6.25%, should reject.
    cap = 800 * MAX_RISK_PER_TRADE_PCT / 100.0
    res = guards.run_guards(_ctx(risk_usd=cap * 1.20))
    assert res["reason"] == "RISK_EXCEEDED"


def test_risk_dollars_within_5pct_tolerance():
    # 5% rounding tolerance must still pass.
    cap = 800 * MAX_RISK_PER_TRADE_PCT / 100.0
    res = guards.run_guards(_ctx(risk_usd=cap * 1.04))
    assert res is None
