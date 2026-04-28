"""Tests for capa 2 ports: conviction_sizing, drawdown_guard, setup_memory."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

UTC = timezone.utc

# Make risk-mcp importable when running from repo root
_HERE = Path(__file__).resolve().parent
_MCP_ROOT = _HERE.parent  # risk-mcp/
_SCAFFOLDS = _MCP_ROOT.parent  # mcp-scaffolds/
sys.path.insert(0, str(_MCP_ROOT))
sys.path.insert(0, str(_SCAFFOLDS / "_shared"))  # for `rules` import inside lib

from lib.conviction_sizing import compute_conviction_multiplier
from lib.drawdown_guard import (
    AccountSnapshot,
    DailyPnLStatus,
    evaluate_daily_pnl_guard,
    evaluate_drawdown_guard,
)
from lib.setup_memory import SetupMemory


# ============================================================================
# conviction_sizing
# ============================================================================


def test_conviction_blocked_on_4_consec_losses():
    out = compute_conviction_multiplier(
        signal_strength=0.9,
        opportunity_score=0.9,
        consecutive_symbol_losses=4,
    )
    assert out.multiplier == 0.0
    assert out.conviction_label == "BLOCKED"
    assert "bloqueado" in out.reason


def test_conviction_high_clean_history():
    out = compute_conviction_multiplier(
        signal_strength=0.85,
        opportunity_score=0.80,
        setup_score=0.05,
        spread_ratio=0.10,
        session_quality=1.0,
        consecutive_symbol_losses=0,
    )
    assert out.multiplier >= 1.10
    assert out.conviction_label == "HIGH"


def test_conviction_low_on_weak_signal():
    out = compute_conviction_multiplier(
        signal_strength=0.15,
        opportunity_score=0.20,
    )
    assert out.multiplier <= 0.50
    assert out.conviction_label == "LOW"


def test_conviction_spread_cap_at_block_threshold():
    out = compute_conviction_multiplier(
        signal_strength=0.9,
        opportunity_score=0.9,
        spread_ratio=1.0,  # at the threshold
    )
    assert out.multiplier <= 0.50


def test_conviction_consec_2_losses_hard_caps_at_0_50():
    out = compute_conviction_multiplier(
        signal_strength=0.9,
        opportunity_score=0.9,
        consecutive_symbol_losses=2,
    )
    assert out.multiplier <= 0.50


def test_conviction_session_quality_drag():
    high_session = compute_conviction_multiplier(
        signal_strength=0.5, opportunity_score=0.5, session_quality=1.0,
    )
    dead_session = compute_conviction_multiplier(
        signal_strength=0.5, opportunity_score=0.5, session_quality=0.0,
    )
    assert dead_session.multiplier <= high_session.multiplier


def test_conviction_audit_payload_complete():
    out = compute_conviction_multiplier(
        signal_strength=0.5, opportunity_score=0.5, session_quality=1.0,
    )
    expected_keys = {
        "signal_strength", "opportunity_score", "setup_score", "spread_ratio",
        "session_quality", "consecutive_symbol_losses", "multiplier", "conviction_label",
    }
    assert expected_keys.issubset(set(out.audit_payload.keys()))


def test_conviction_to_dict_shape():
    d = compute_conviction_multiplier(signal_strength=0.5).to_dict()
    assert d["ok"] is True
    assert "multiplier" in d
    assert "conviction_label" in d
    assert "size_label" in d


def test_conviction_clamps_input_ranges():
    # signal_strength > 1.0 must be clamped to 1.0; setup_score > 0.15 too.
    out = compute_conviction_multiplier(
        signal_strength=99.0,
        opportunity_score=99.0,
        setup_score=99.0,
    )
    assert 0.0 <= out.multiplier <= 1.25


# ============================================================================
# drawdown_guard
# ============================================================================


def _snap(**overrides) -> AccountSnapshot:
    base = dict(
        equity=800.0,
        balance=800.0,
        day_start_equity=800.0,
        peak_equity=800.0,
        consecutive_losses=0,
        last_loss_at=None,
    )
    base.update(overrides)
    return AccountSnapshot(**base)


def test_drawdown_passes_clean_account():
    out = evaluate_drawdown_guard(account=_snap())
    assert not out.blocked
    assert out.reason_codes == []


def test_drawdown_invalid_day_start():
    out = evaluate_drawdown_guard(account=_snap(day_start_equity=0.0))
    assert out.blocked
    assert "INVALID_DAY_START_EQUITY" in out.reason_codes


def test_drawdown_blocks_on_max_daily_loss():
    # rules.py has MAX_DAILY_LOSS_PCT = 50.0 (DEMO mode); use a >50% drop.
    out = evaluate_drawdown_guard(
        account=_snap(equity=300.0, day_start_equity=800.0),
    )
    assert out.blocked
    assert "MAX_DAILY_LOSS_REACHED" in out.reason_codes


def test_drawdown_blocks_on_max_drawdown_when_configured():
    # 10% drawdown from peak; max set at 5%.
    out = evaluate_drawdown_guard(
        account=_snap(equity=720.0, peak_equity=800.0),
        max_drawdown_pct=5.0,
    )
    assert out.blocked
    assert "MAX_DRAWDOWN_REACHED" in out.reason_codes


def test_drawdown_no_check_when_max_drawdown_pct_none():
    # equity=790 is 1.25% below day_start (800) — below the 3% daily-loss rule.
    # With max_drawdown_pct=None the peak-drawdown check is skipped, so nothing blocks.
    out = evaluate_drawdown_guard(
        account=_snap(equity=790.0, peak_equity=800.0),
        max_drawdown_pct=None,
    )
    assert not out.blocked


def test_drawdown_blocks_on_consecutive_losses():
    # rules.py has MAX_CONSECUTIVE_LOSSES = 6 (DEMO); use 6.
    out = evaluate_drawdown_guard(account=_snap(consecutive_losses=6))
    assert out.blocked
    assert "MAX_CONSECUTIVE_LOSSES_REACHED" in out.reason_codes


def test_drawdown_cooldown_active_blocks():
    now = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
    last_loss = now - timedelta(minutes=10)
    out = evaluate_drawdown_guard(
        account=_snap(last_loss_at=last_loss),
        as_of=now,
        cooldown_after_loss_minutes=15,
    )
    assert out.blocked
    assert "LOSS_COOLDOWN_ACTIVE" in out.reason_codes


def test_drawdown_cooldown_expired_passes():
    now = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)
    last_loss = now - timedelta(minutes=20)
    out = evaluate_drawdown_guard(
        account=_snap(last_loss_at=last_loss),
        as_of=now,
        cooldown_after_loss_minutes=15,
    )
    assert not out.blocked


def test_drawdown_audit_includes_inputs():
    out = evaluate_drawdown_guard(account=_snap())
    for key in ("equity", "balance", "day_start_equity", "peak_equity",
                "max_daily_loss_pct", "max_consecutive_losses"):
        assert key in out.audit_payload


# ============================================================================
# daily_pnl_guard
# ============================================================================


def test_daily_pnl_guard_none_passes():
    out = evaluate_daily_pnl_guard(status=None)
    assert not out.blocked
    assert not out.close_only_mode


def test_daily_pnl_guard_disabled_blocks():
    out = evaluate_daily_pnl_guard(
        status=DailyPnLStatus(daily_trading_enabled=False),
    )
    assert out.blocked
    assert "DAILY_TRADING_DISABLED" in out.reason_codes


def test_daily_pnl_guard_symbol_not_allowed_blocks():
    out = evaluate_daily_pnl_guard(
        status=DailyPnLStatus(allowed_symbols_today=("EURUSD", "BTCUSD")),
        symbol="XAUUSD",
    )
    assert out.blocked
    assert "SYMBOL_NOT_ALLOWED_TODAY" in out.reason_codes


def test_daily_pnl_guard_symbol_allowed_passes():
    out = evaluate_daily_pnl_guard(
        status=DailyPnLStatus(allowed_symbols_today=("EURUSD", "BTCUSD")),
        symbol="BTCUSD",
    )
    assert not out.blocked


def test_daily_pnl_guard_stopped_uses_stop_reason_code():
    out = evaluate_daily_pnl_guard(
        status=DailyPnLStatus(
            trading_stopped_for_day=True,
            stop_reason_code="DAILY_PROFIT_TARGET_REACHED",
        ),
    )
    assert out.blocked
    assert "DAILY_PROFIT_TARGET_REACHED" in out.reason_codes


def test_daily_pnl_guard_close_only_propagates():
    out = evaluate_daily_pnl_guard(
        status=DailyPnLStatus(close_only_mode=True),
    )
    # close_only alone doesn't block; the flag flows to caller
    assert not out.blocked
    assert out.close_only_mode is True


# ============================================================================
# setup_memory
# ============================================================================


@pytest.fixture
def mem(tmp_path):
    return SetupMemory(path=tmp_path / "setup_memory.json")


def test_setup_memory_empty_score_is_zero(mem):
    assert mem.setup_score("EURUSD", "ema_rsi_trend") == 0.0


def test_setup_memory_persists(tmp_path):
    p = tmp_path / "mem.json"
    m1 = SetupMemory(path=p)
    m1.record_trade(symbol="EURUSD", driver="ema_rsi_trend", won=True, pnl=10.0)
    m1.record_trade(symbol="EURUSD", driver="ema_rsi_trend", won=False, pnl=-5.0)
    # Re-open to verify persistence
    m2 = SetupMemory(path=p)
    stats = m2.get_setup_stats("EURUSD", "ema_rsi_trend")
    assert stats is not None
    assert stats.wins == 1
    assert stats.losses == 1
    assert stats.total_pnl == 5.0


def test_setup_memory_score_bad_setup_negative(mem):
    # 4 losses, 1 win → 20% win rate → strong negative
    for _ in range(4):
        mem.record_trade(symbol="BTCUSD", driver="bad_setup", won=False, pnl=-5.0)
    mem.record_trade(symbol="BTCUSD", driver="bad_setup", won=True, pnl=5.0)
    score = mem.setup_score("BTCUSD", "bad_setup")
    assert score < -0.10


def test_setup_memory_score_strong_setup_positive(mem):
    # 7 wins, 1 loss → 87.5% win rate
    for _ in range(7):
        mem.record_trade(symbol="XAUUSD", driver="good_setup", won=True, pnl=10.0)
    mem.record_trade(symbol="XAUUSD", driver="good_setup", won=False, pnl=-5.0)
    score = mem.setup_score("XAUUSD", "good_setup")
    assert score > 0.0


def test_setup_memory_score_neutral_below_3_trades(mem):
    mem.record_trade(symbol="EURUSD", driver="x", won=True, pnl=5.0)
    mem.record_trade(symbol="EURUSD", driver="x", won=False, pnl=-3.0)
    assert mem.setup_score("EURUSD", "x") == 0.0


def test_symbol_consecutive_losses_tracked(mem):
    mem.record_trade(symbol="EURUSD", driver="a", won=False, pnl=-5.0)
    mem.record_trade(symbol="EURUSD", driver="b", won=False, pnl=-5.0)
    assert mem.symbol_consecutive_losses("EURUSD") == 2
    assert mem.symbol_should_reduce("EURUSD")
    assert not mem.symbol_should_block("EURUSD")


def test_symbol_should_block_at_4(mem):
    for _ in range(4):
        mem.record_trade(symbol="BTCUSD", driver="x", won=False, pnl=-5.0)
    assert mem.symbol_should_block("BTCUSD")


def test_symbol_consec_resets_on_win(mem):
    mem.record_trade(symbol="EURUSD", driver="a", won=False, pnl=-5.0)
    mem.record_trade(symbol="EURUSD", driver="a", won=False, pnl=-5.0)
    assert mem.symbol_consecutive_losses("EURUSD") == 2
    mem.record_trade(symbol="EURUSD", driver="a", won=True, pnl=10.0)
    assert mem.symbol_consecutive_losses("EURUSD") == 0


def test_setup_history_note_silent_below_3(mem):
    mem.record_trade(symbol="EURUSD", driver="x", won=True, pnl=5.0)
    assert mem.setup_history_note("EURUSD", "x") == ""


def test_setup_history_note_blocked(mem):
    for _ in range(4):
        mem.record_trade(symbol="EURUSD", driver="x", won=False, pnl=-5.0)
    note = mem.setup_history_note("EURUSD", "x")
    assert "bloqueado" in note


def test_setup_memory_corrupt_file_recovers(tmp_path):
    p = tmp_path / "mem.json"
    p.write_text("not json {{{", encoding="utf-8")
    mem = SetupMemory(path=p)
    # Should not raise; should be empty
    assert mem.symbol_consecutive_losses("ANY") == 0
    # And should be writable
    mem.record_trade(symbol="EURUSD", driver="x", won=True, pnl=5.0)
    assert mem.get_setup_stats("EURUSD", "x") is not None
