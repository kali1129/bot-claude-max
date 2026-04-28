"""Tests for capa 4 ports: sl_tp_manager, trailing_stop, quality_checks,
position_reconciliation.

Tests target the lib modules directly — they do not import server.py
because that would require the MetaTrader5 package which is not available
on Linux. The MCP tool wrappers are thin pass-throughs.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

UTC = timezone.utc

_HERE = Path(__file__).resolve().parent
_MCP_ROOT = _HERE.parent  # trading-mt5-mcp/
sys.path.insert(0, str(_MCP_ROOT))

from lib.sl_tp_manager import validate_sl_tp
from lib.trailing_stop import evaluate_trailing_stop
from lib.quality_checks import (
    QualityThresholds,
    check_bar_series,
    check_quote,
    validate_symbol,
    validate_timeframe,
)
from lib.position_reconciliation import reconcile_positions


# =================== sl_tp_manager ===================


def test_sltp_buy_valid_layout_passes():
    out = validate_sl_tp(side="buy", entry_price=100.0, stop_loss=99.0, take_profit=102.0)
    assert out.allowed
    assert out.reason_codes == []


def test_sltp_buy_invalid_when_sl_above_entry():
    out = validate_sl_tp(side="buy", entry_price=100.0, stop_loss=101.0, take_profit=102.0)
    assert not out.allowed
    assert "SLTP_INVALID" in out.reason_codes


def test_sltp_sell_valid_layout_passes():
    out = validate_sl_tp(side="sell", entry_price=100.0, stop_loss=102.0, take_profit=98.0)
    assert out.allowed


def test_sltp_sell_invalid_when_tp_above_entry():
    out = validate_sl_tp(side="sell", entry_price=100.0, stop_loss=102.0, take_profit=101.0)
    assert not out.allowed
    assert "SLTP_INVALID" in out.reason_codes


def test_sltp_unsupported_side_rejected():
    out = validate_sl_tp(side="hold", entry_price=100.0, stop_loss=99.0, take_profit=101.0)
    assert not out.allowed
    assert "UNSUPPORTED_SIDE" in out.reason_codes


def test_sltp_buy_resolves_entry_to_ask():
    out = validate_sl_tp(
        side="buy", entry_price=100.0, stop_loss=99.0, take_profit=102.0,
        bid=99.95, ask=100.05,
    )
    assert out.entry_price == 100.05


def test_sltp_sell_resolves_entry_to_bid():
    out = validate_sl_tp(
        side="sell", entry_price=100.0, stop_loss=102.0, take_profit=98.0,
        bid=99.95, ask=100.05,
    )
    assert out.entry_price == 99.95


def test_sltp_to_dict_shape():
    d = validate_sl_tp(side="buy", entry_price=100.0, stop_loss=99.0, take_profit=102.0).to_dict()
    assert d["ok"] is True
    assert d["allowed"] is True
    assert "audit" in d


# =================== trailing_stop ===================


def test_trailing_buy_not_triggered_yet():
    out = evaluate_trailing_stop(
        side="buy", entry_price=100.0, current_price=100.5,
        current_stop_loss=99.0,
        trigger_distance=1.0, trail_distance=0.5,
    )
    assert not out.should_update
    assert out.reason_code == "TRAILING_NOT_TRIGGERED"


def test_trailing_buy_updated_when_in_profit():
    out = evaluate_trailing_stop(
        side="buy", entry_price=100.0, current_price=102.0,
        current_stop_loss=99.0,
        trigger_distance=1.0, trail_distance=0.5,
    )
    assert out.should_update
    assert out.new_stop_loss == 101.5
    assert out.reason_code == "TRAILING_LONG_UPDATED"


def test_trailing_buy_step_too_small():
    out = evaluate_trailing_stop(
        side="buy", entry_price=100.0, current_price=102.0,
        current_stop_loss=101.4,  # candidate 101.5 vs current 101.4 < min_step
        trigger_distance=1.0, trail_distance=0.5, min_step=0.2,
    )
    assert not out.should_update
    assert out.reason_code == "TRAILING_STEP_TOO_SMALL"


def test_trailing_sell_updated_when_in_profit():
    out = evaluate_trailing_stop(
        side="sell", entry_price=100.0, current_price=98.0,
        current_stop_loss=101.0,
        trigger_distance=1.0, trail_distance=0.5,
    )
    assert out.should_update
    assert out.new_stop_loss == 98.5
    assert out.reason_code == "TRAILING_SHORT_UPDATED"


def test_trailing_sell_not_triggered():
    out = evaluate_trailing_stop(
        side="sell", entry_price=100.0, current_price=99.5,
        current_stop_loss=101.0,
        trigger_distance=1.0, trail_distance=0.5,
    )
    assert not out.should_update


def test_trailing_invalid_distances():
    out = evaluate_trailing_stop(
        side="buy", entry_price=100.0, current_price=102.0,
        current_stop_loss=99.0,
        trigger_distance=0.0, trail_distance=0.5,
    )
    assert not out.should_update
    assert out.reason_code == "TRAILING_RULE_INVALID"


def test_trailing_unknown_side():
    out = evaluate_trailing_stop(
        side="nope", entry_price=100.0, current_price=102.0,
        current_stop_loss=99.0,
        trigger_distance=1.0, trail_distance=0.5,
    )
    assert out.reason_code == "TRAILING_ACTION_UNSUPPORTED"


def test_trailing_to_dict_shape():
    d = evaluate_trailing_stop(
        side="buy", entry_price=100.0, current_price=102.0,
        current_stop_loss=99.0,
        trigger_distance=1.0, trail_distance=0.5,
    ).to_dict()
    assert d["ok"] is True
    assert d["should_update"] is True
    assert d["new_stop_loss"] == 101.5


# =================== quality_checks ===================


def test_validate_symbol_accepts_normal():
    r = validate_symbol("EURUSD")
    assert not r["has_errors"]


def test_validate_symbol_rejects_bad():
    r = validate_symbol("eu")  # too short
    assert r["has_errors"]
    assert any(f["code"] == "INVALID_SYMBOL" for f in r["flags"])


def test_validate_timeframe_accepts():
    r = validate_timeframe("M15")
    assert not r["has_errors"]


def test_validate_timeframe_rejects():
    r = validate_timeframe("M7")
    assert r["has_errors"]


def _bar(ts: datetime, *, volume: float = 100.0, spread: float = 1.0) -> dict:
    return {
        "time": ts.isoformat(),
        "open": 100.0, "high": 100.5, "low": 99.5, "close": 100.2,
        "volume": volume, "spread": spread,
    }


def test_quality_check_bar_series_clean():
    base = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    bars = [_bar(base + timedelta(minutes=15 * i)) for i in range(5)]
    r = check_bar_series("EURUSD", "M15", bars, as_of=bars[-1]["time"] and base + timedelta(minutes=60))
    assert not r["has_errors"]


def test_quality_check_bar_series_detects_duplicate():
    base = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    bars = [_bar(base), _bar(base)]  # duplicate
    r = check_bar_series("EURUSD", "M15", bars, as_of=base + timedelta(minutes=15))
    assert r["has_errors"]
    assert any(f["code"] == "DUPLICATE_BAR" for f in r["flags"])


def test_quality_check_bar_series_detects_gap():
    base = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    bars = [_bar(base), _bar(base + timedelta(minutes=15)), _bar(base + timedelta(minutes=60))]
    r = check_bar_series("EURUSD", "M15", bars, as_of=base + timedelta(minutes=75))
    assert any(f["code"] == "MISSING_BARS" for f in r["flags"])


def test_quality_check_bar_series_zero_volume_warning():
    base = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    bars = [_bar(base + timedelta(minutes=15 * i), volume=0.0) for i in range(3)]
    r = check_bar_series("EURUSD", "M15", bars, as_of=base + timedelta(minutes=45))
    assert any(f["code"] == "ZERO_VOLUME_ANOMALY" for f in r["flags"])


def test_quality_check_bar_series_spread_outlier():
    base = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    bars = [
        _bar(base, spread=2.0),
        _bar(base + timedelta(minutes=15), spread=99.0),  # outlier
    ]
    r = check_bar_series(
        "EURUSD", "M15", bars,
        as_of=base + timedelta(minutes=20),
        thresholds=QualityThresholds(max_spread_points=10.0),
    )
    assert any(f["code"] == "SPREAD_OUTLIER" for f in r["flags"])


def test_quality_check_bar_series_stale_warning():
    base = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    bars = [_bar(base)]
    # as_of is way in the future → STALE_MARKET_STATE
    r = check_bar_series(
        "EURUSD", "M15", bars,
        as_of=base + timedelta(hours=2),
    )
    assert any(f["code"] == "STALE_MARKET_STATE" for f in r["flags"])


def test_quality_check_quote_clean():
    ts = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    q = {"symbol": "EURUSD", "timestamp": ts.isoformat(), "bid": 1.10, "ask": 1.1001, "spread": 1.0}
    r = check_quote(q, as_of=ts + timedelta(seconds=5))
    assert not r["has_errors"]


def test_quality_check_quote_invalid_bidask():
    ts = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    q = {"symbol": "EURUSD", "timestamp": ts.isoformat(), "bid": 1.20, "ask": 1.10}
    r = check_quote(q, as_of=ts + timedelta(seconds=2))
    assert any(f["code"] == "INVALID_QUOTE" for f in r["flags"])


def test_quality_check_quote_stale_flag():
    ts = datetime(2026, 4, 28, 10, 0, tzinfo=UTC)
    q = {"symbol": "EURUSD", "timestamp": ts.isoformat(), "bid": 1.10, "ask": 1.1001}
    r = check_quote(q, as_of=ts + timedelta(minutes=5))  # stale_after default 30s
    assert any(f["code"] == "STALE_MARKET_STATE" for f in r["flags"])


# =================== position_reconciliation ===================


def test_reconcile_in_sync_empty():
    out = reconcile_positions(mt5_positions=[], journal_positions=[])
    assert out.in_sync


def test_reconcile_matched_no_diffs():
    mt5 = [{"ticket": 123, "symbol": "EURUSD", "type": "BUY", "volume": 0.10, "sl": 1.10, "tp": 1.12}]
    journal = [{"ticket": 123, "symbol": "EURUSD", "type": "buy", "volume": 0.10, "sl": 1.10, "tp": 1.12}]
    out = reconcile_positions(mt5_positions=mt5, journal_positions=journal)
    assert out.in_sync
    assert 123 in out.matched


def test_reconcile_missing_in_journal():
    mt5 = [{"ticket": 1}, {"ticket": 2}]
    journal = [{"ticket": 1}]
    out = reconcile_positions(mt5_positions=mt5, journal_positions=journal)
    assert not out.in_sync
    assert 2 in out.missing_in_journal


def test_reconcile_missing_in_mt5():
    mt5 = [{"ticket": 1}]
    journal = [{"ticket": 1}, {"ticket": 9}]
    out = reconcile_positions(mt5_positions=mt5, journal_positions=journal)
    assert 9 in out.missing_in_mt5


def test_reconcile_volume_mismatch_flagged():
    mt5 = [{"ticket": 1, "symbol": "EURUSD", "type": "buy", "volume": 0.10, "sl": 1.10, "tp": 1.12}]
    journal = [{"ticket": 1, "symbol": "EURUSD", "type": "buy", "volume": 0.20, "sl": 1.10, "tp": 1.12}]
    out = reconcile_positions(mt5_positions=mt5, journal_positions=journal)
    assert not out.in_sync
    assert len(out.mismatched) == 1
    assert out.mismatched[0]["ticket"] == 1
    assert "volume" in out.mismatched[0]["diffs"]


def test_reconcile_handles_alias_keys():
    # MT5 uses 'side', journal uses 'type' — should be normalized via alias
    mt5 = [{"position_id": 123, "symbol": "XAUUSD", "side": "buy", "volume": 0.05, "stop_loss": 1900.0, "take_profit": 1920.0}]
    journal = [{"deal_ticket": 123, "symbol": "XAUUSD", "type": "buy", "lot": 0.05, "sl": 1900.0, "tp": 1920.0}]
    out = reconcile_positions(mt5_positions=mt5, journal_positions=journal)
    assert out.in_sync


def test_reconcile_to_dict_shape():
    mt5 = [{"ticket": 1, "volume": 0.10}]
    journal = [{"ticket": 1, "volume": 0.20}]
    d = reconcile_positions(mt5_positions=mt5, journal_positions=journal).to_dict()
    assert d["ok"] is True
    assert d["in_sync"] is False
    assert d["matched_count"] == 1
    assert isinstance(d["mismatched"], list)


def test_reconcile_records_without_ticket_ignored():
    mt5 = [{"symbol": "EURUSD"}]  # no ticket
    journal = [{"ticket": 1}]
    out = reconcile_positions(mt5_positions=mt5, journal_positions=journal)
    assert 1 in out.missing_in_mt5
