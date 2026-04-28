import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from rules import (
    MIN_RR, MAX_RISK_PER_TRADE_PCT,
    rr, passes_rr, is_blocked_hour, max_risk_dollars, snapshot,
)


def test_constants_are_within_safe_envelope():
    # Smoke: if any of these moves, a human must approve the change.
    assert MIN_RR >= 2.0
    assert MAX_RISK_PER_TRADE_PCT <= 1.0


@pytest.mark.parametrize("entry,sl,tp,expected", [
    (1.0850, 1.0830, 1.0890, 2.0),
    (1.0850, 1.0830, 1.0870, 1.0),
    (1.0850, 1.0850, 1.0870, 0.0),  # zero risk → 0
])
def test_rr(entry, sl, tp, expected):
    assert rr(entry, sl, tp) == pytest.approx(expected, abs=1e-6)


@pytest.mark.parametrize("entry,sl,tp,ok", [
    (1.0850, 1.0830, 1.0890, True),   # 1:2 exact
    (1.0850, 1.0830, 1.0889, False),  # 1:1.95
])
def test_passes_rr_boundary(entry, sl, tp, ok):
    assert passes_rr(entry, sl, tp) is ok


@pytest.mark.parametrize("h,blocked", [
    (0, True), (3, True), (6, True),
    (7, False), (12, False), (20, False),
    (21, True), (23, True),
])
def test_is_blocked_hour(h, blocked):
    assert is_blocked_hour(h) is blocked


def test_max_risk_dollars_caps_above_rule():
    assert max_risk_dollars(800, 5.0) == 8.0  # capped to 1%
    assert max_risk_dollars(800, 0.5) == 4.0  # below cap honoured


def test_snapshot_is_frozen():
    s = snapshot()
    with pytest.raises(Exception):
        s.max_risk_per_trade_pct = 99.0  # type: ignore
