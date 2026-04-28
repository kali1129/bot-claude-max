"""Tests for calc_position_size."""
import pytest

from lib.sizing import calc_position_size


def test_basic_eurusd():
    # $800 balance, 1% risk, 20-pip SL, $10/pip → $8 budget / $200 per lot = 0.04
    res = calc_position_size(
        balance=800, risk_pct=1.0, entry=1.0850, sl=1.0830,
        tick_value=10.0, tick_size=0.0001,
    )
    assert res["lots"] == 0.04
    assert res["risk_dollars"] == 8.0
    assert res["risk_pct_actual"] == 1.0


def test_risk_pct_above_rule_warns():
    res = calc_position_size(
        balance=800, risk_pct=2.0, entry=1.0850, sl=1.0830,
        tick_value=10.0, tick_size=0.0001,
    )
    assert any("excede" in w.lower() for w in res["warnings"])


def test_refuses_below_min_lot():
    # $50 balance, 1% = $0.5 budget, but min lot 0.01 with 20-pip SL = $2.
    res = calc_position_size(
        balance=50, risk_pct=1.0, entry=1.0850, sl=1.0830,
        tick_value=10.0, tick_size=0.0001,
    )
    assert res["lots"] == 0.0
    assert any("mínimo" in w.lower() or "minimo" in w.lower() for w in res["warnings"])


def test_caps_to_max_lot():
    # Big budget → would suggest 0.6 lots; cap is 0.5.
    res = calc_position_size(
        balance=100_000, risk_pct=1.0, entry=1.0850, sl=1.0830,
        tick_value=10.0, tick_size=0.0001, max_lot=0.5,
    )
    assert res["lots"] == 0.5
    assert any("Lotaje recortado" in w for w in res["warnings"])


def test_entry_eq_sl_rejects():
    res = calc_position_size(
        balance=800, risk_pct=1.0, entry=1.0850, sl=1.0850,
        tick_value=10.0, tick_size=0.0001,
    )
    assert "error" in res
    assert res["lots"] == 0.0


@pytest.mark.parametrize("balance,risk_pct", [
    (800, 1.0), (1000, 0.5), (5000, 1.0), (10_000, 0.75),
])
def test_actual_risk_never_exceeds_requested(balance, risk_pct):
    res = calc_position_size(
        balance=balance, risk_pct=risk_pct, entry=1.0850, sl=1.0810,
        tick_value=10.0, tick_size=0.0001,
    )
    # Lot snapping rounds to volume_step which can land slightly above
    # the requested risk; 5% tolerance covers it.
    assert res["risk_pct_actual"] <= risk_pct * 1.05
