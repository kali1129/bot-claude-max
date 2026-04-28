"""Tests for capa 5 ports: backtest engine, telegram_control, quality_assessment,
selfcheck.

These exercise the lib modules directly — not via FastAPI endpoints — so
the test surface stays focused on the port logic. Endpoint wiring is
tested elsewhere in backend/tests/test_server.py (pre-existing).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

UTC = timezone.utc

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
_REPO = _BACKEND.parent
_LIB = _BACKEND / "lib"

# Ensure backend/lib AND analysis-mcp are importable before any port import
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_REPO / "mcp-scaffolds" / "analysis-mcp"))
sys.path.insert(0, str(_REPO / "mcp-scaffolds"))

from bot_lib.backtest.engine import BacktestConfig, run_backtest  # noqa: E402
from bot_lib.telegram_control import (  # noqa: E402
    DEFAULT_COMMANDS,
    CommandRequest,
    dispatch,
    make_stub_handlers,
)
from bot_lib.monitoring.quality_assessment import (  # noqa: E402
    build_report,
    determine_overall_rating,
    determine_unattended_readiness,
    make_check,
    score_category,
)
from bot_lib.selfcheck import run_selfcheck  # noqa: E402


# =================== backtest ===================


def _bars_uptrend(n: int = 200, start: float = 100.0) -> list[dict]:
    """Synthetic upward-drifting OHLCV at 1-minute cadence."""
    base = datetime(2026, 4, 28, 9, 0, tzinfo=UTC)
    bars = []
    prev = start
    for i in range(n):
        c = start + i * 0.10
        o = prev
        h = max(o, c) * 1.0008
        l = min(o, c) * 0.9992
        bars.append({
            "time": (base + timedelta(minutes=i)).isoformat().replace("+00:00", "Z"),
            "open": o, "high": h, "low": l, "close": c, "spread": 1.0,
        })
        prev = c
    return bars


def _always_long_signal(ohlcv):
    """Trivial signal: always go LONG with a tiny ATR."""
    if len(ohlcv) < 2:
        return {"direction": "FLAT", "atr": 0.0}
    last_close = float(ohlcv[-1]["close"])
    return {"direction": "LONG", "atr": last_close * 0.005, "score": 1.0}


def _always_flat_signal(ohlcv):
    return {"direction": "FLAT", "atr": 0.0}


def _alternating_signal(ohlcv):
    """LONG on even bars, FLAT on odd — a basic stress test."""
    if len(ohlcv) < 2:
        return {"direction": "FLAT", "atr": 0.0}
    if len(ohlcv) % 2 == 0:
        last_close = float(ohlcv[-1]["close"])
        return {"direction": "LONG", "atr": last_close * 0.005, "score": 1.0}
    return {"direction": "FLAT", "atr": 0.0}


def test_backtest_rejects_too_few_bars():
    out = run_backtest(
        ohlcv=_bars_uptrend(20),
        signal_fn=_always_flat_signal,
        config={"warmup_bars": 50},
    )
    assert out["ok"] is False
    assert out["reason"] == "INSUFFICIENT_BARS"


def test_backtest_flat_signal_no_trades():
    out = run_backtest(
        ohlcv=_bars_uptrend(200),
        signal_fn=_always_flat_signal,
        config={"warmup_bars": 30},
    )
    assert out["ok"] is True
    assert out["metrics"]["trades"] == 0


def test_backtest_runs_clean_with_signal():
    out = run_backtest(
        ohlcv=_bars_uptrend(200),
        signal_fn=_always_long_signal,
        config={"warmup_bars": 30, "initial_balance": 1000.0},
    )
    assert out["ok"] is True
    assert out["total_bars"] == 200
    for k in ("trades", "wins", "losses", "win_rate", "total_pnl",
              "expectancy", "profit_factor", "max_drawdown_pct",
              "sharpe", "ending_balance"):
        assert k in out["metrics"]


def test_backtest_strong_uptrend_with_long_signal_profits():
    """LONG in a steady uptrend with TP > SL distance should net positive PnL."""
    bars = _bars_uptrend(400)
    out = run_backtest(
        ohlcv=bars,
        signal_fn=_always_long_signal,
        config={
            "warmup_bars": 30, "initial_balance": 1000.0,
            "sl_atr_mult": 1.5, "tp_atr_mult": 2.5,
        },
    )
    assert out["ok"] is True
    # In a clean uptrend, ending balance should be at or above start
    assert out["metrics"]["ending_balance"] >= 1000.0


def test_backtest_score_gating_blocks_low_score():
    def low_score_signal(ohlcv):
        return {"direction": "LONG", "atr": 1.0, "score": 0.10}
    out = run_backtest(
        ohlcv=_bars_uptrend(200),
        signal_fn=low_score_signal,
        config={"warmup_bars": 30, "min_score": 0.5},
    )
    assert out["ok"] is True
    assert out["metrics"]["trades"] == 0


def test_backtest_signal_fn_exception_caught():
    def boom(ohlcv):
        raise RuntimeError("kaboom")
    out = run_backtest(
        ohlcv=_bars_uptrend(200),
        signal_fn=boom,
        config={"warmup_bars": 30},
    )
    assert out["ok"] is False
    assert out["reason"] == "SIGNAL_FN_RAISED"


def test_backtest_config_from_mapping():
    cfg = BacktestConfig.from_mapping({"initial_balance": 500.0, "min_score": 0.5})
    assert cfg.initial_balance == 500.0
    assert cfg.min_score == 0.5
    assert cfg.risk_per_trade_pct == 1.0  # default


# =================== telegram_control ===================


def test_dispatch_unknown_command():
    out = dispatch(
        CommandRequest(name="/nope", user_id="u1"),
        handlers=make_stub_handlers(),
        allowed_user_ids=("u1",),
    )
    assert out["ok"] is False
    assert out["reason"] == "UNKNOWN_COMMAND"


def test_dispatch_user_not_allowed():
    out = dispatch(
        CommandRequest(name="/status", user_id="evil"),
        handlers=make_stub_handlers(),
        allowed_user_ids=("u1",),
    )
    assert out["ok"] is False
    assert out["reason"] == "USER_NOT_ALLOWED"


def test_dispatch_status_handler_runs():
    out = dispatch(
        CommandRequest(name="/status", user_id="u1"),
        handlers=make_stub_handlers(),
        allowed_user_ids=("u1",),
    )
    assert out["ok"] is True
    assert out["command"] == "/status"


def test_dispatch_halt_requires_confirm():
    out = dispatch(
        CommandRequest(name="/halt", user_id="u1", confirm=False),
        handlers=make_stub_handlers(),
        allowed_user_ids=("u1",),
    )
    assert out["ok"] is False
    assert out["reason"] == "CONFIRM_REQUIRED"


def test_dispatch_halt_with_confirm_passes():
    out = dispatch(
        CommandRequest(name="/halt", user_id="u1", confirm=True),
        handlers=make_stub_handlers(),
        allowed_user_ids=("u1",),
    )
    assert out["ok"] is True


def test_dispatch_no_handler():
    handlers = {"/status": lambda req: {"x": 1}}  # only one handler registered
    out = dispatch(
        CommandRequest(name="/health", user_id="u1"),
        handlers=handlers,
        allowed_user_ids=("u1",),
    )
    assert out["ok"] is False
    assert out["reason"] == "NO_HANDLER"


def test_dispatch_handler_exception_caught():
    def boom(req):
        raise RuntimeError("kaboom")
    handlers = {"/status": boom}
    out = dispatch(
        CommandRequest(name="/status", user_id="u1"),
        handlers=handlers,
        allowed_user_ids=("u1",),
    )
    assert out["ok"] is False
    assert out["reason"] == "HANDLER_RAISED"


def test_default_commands_include_state_mutators_with_confirm():
    for name in ("/halt", "/resume", "/reset_day", "/force_close"):
        spec = DEFAULT_COMMANDS[name]
        assert spec.requires_confirm, f"{name} must require confirm"


def test_command_request_from_mapping():
    req = CommandRequest.from_mapping({
        "name": "/expectancy",
        "user_id": "u1",
        "args": {"last_n": 30},
        "confirm": False,
    })
    assert req.name == "/expectancy"
    assert req.args == {"last_n": 30}


# =================== quality_assessment ===================


def test_score_category_pass_when_all_pass():
    cat = score_category("data", [
        make_check("feed", "pass", "ticks flowing"),
        make_check("calendar", "pass", "events loaded"),
    ])
    assert cat["score"] == 1.0
    assert cat["status"] == "pass"


def test_score_category_blocker_when_any_blocker_fail():
    cat = score_category("execution", [
        make_check("orders", "pass", "fills observed"),
        make_check("kill_switch", "fail", "halt file unwritable", blocker=True),
    ])
    assert cat["status"] == "blocker"
    assert cat["blockers"] == 1


def test_score_category_weighted_average():
    cat = score_category("hybrid", [
        make_check("low", "pass", "ok", weight=1.0),       # 1.0 * 1
        make_check("high", "fail", "broken", weight=3.0),  # 0.0 * 3
    ])
    # weighted: (1.0*1 + 0.0*3) / 4 = 0.25
    assert cat["score"] == 0.25


def test_overall_rating_pass():
    cats = [
        score_category("a", [make_check("x", "pass", "")]),
        score_category("b", [make_check("y", "pass", "")]),
    ]
    overall = determine_overall_rating(cats)
    assert overall["rating"] == "pass"
    assert overall["score"] == 1.0


def test_overall_rating_blocker_propagates():
    cats = [
        score_category("a", [make_check("x", "fail", "broken", blocker=True)]),
    ]
    overall = determine_overall_rating(cats)
    assert overall["rating"] == "blocker"
    assert overall["has_blockers"] is True


def test_unattended_readiness_blocked_by_blocker():
    cats = [
        score_category("a", [make_check("x", "fail", "broken", blocker=True)]),
    ]
    overall = determine_overall_rating(cats)
    readiness = determine_unattended_readiness(cats, overall)
    assert readiness["ready"] is False
    assert readiness["reason"] == "BLOCKERS_PRESENT"


def test_unattended_readiness_below_min_score():
    cats = [
        score_category("a", [make_check("x", "partial", "meh")]),
    ]
    overall = determine_overall_rating(cats)
    readiness = determine_unattended_readiness(cats, overall, min_overall_score=0.85)
    assert readiness["ready"] is False
    assert readiness["reason"] == "SCORE_BELOW_MIN"


def test_build_report_shape():
    cats = [score_category("env", [make_check("x", "pass", "")])]
    report = build_report(categories=cats)
    assert report["ok"] is True
    assert "generated_at_utc" in report
    assert "overall" in report
    assert "readiness" in report
    assert "categories" in report


# =================== selfcheck ===================


def test_selfcheck_runs_and_returns_report(monkeypatch):
    # No env vars set → DASHBOARD_TOKEN missing → blocker; selfcheck still runs.
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    monkeypatch.delenv("MONGO_URL", raising=False)
    monkeypatch.delenv("BACKEND_HOST", raising=False)
    out = run_selfcheck()
    assert out["ok"] is True
    assert "categories" in out
    cat_names = {c["name"] for c in out["categories"]}
    # Sanity: all 4 categories ran
    assert {"environment", "rules", "kill_switch", "backend"} <= cat_names


def test_selfcheck_passes_with_dashboard_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_TOKEN", "test_token_long_enough_xxxxxxxx")
    monkeypatch.setenv("HALT_FILE", str(tmp_path / "halt"))
    out = run_selfcheck()
    env = next(c for c in out["categories"] if c["name"] == "environment")
    # DASHBOARD_TOKEN check should pass now
    token_check = next(c for c in env["checks"] if c["name"] == "env.DASHBOARD_TOKEN")
    assert token_check["status"] == "pass"


def test_selfcheck_warns_when_backend_bound_to_wildcard(monkeypatch, tmp_path):
    monkeypatch.setenv("DASHBOARD_TOKEN", "x" * 32)
    monkeypatch.setenv("HALT_FILE", str(tmp_path / "halt"))
    monkeypatch.setenv("BACKEND_HOST", "0.0.0.0")
    out = run_selfcheck()
    backend = next(c for c in out["categories"] if c["name"] == "backend")
    assert backend["status"] in ("partial", "review", "unknown")
