"""State persistence + migration tests."""
import json

from lib import state_manager as sm


def test_creates_state_on_first_load(fresh_state):
    s = sm.load_state()
    assert s["_schema_version"] == sm.CURRENT_SCHEMA_VERSION
    assert s["starting_balance_today"] == 800
    assert s["current_equity"] == 800
    assert s["deals_today"] == []
    assert s["consecutive_losses"] == 0
    assert s["locked_until_utc"] is None
    assert fresh_state["state"].exists()


def test_round_trip(fresh_state):
    s = sm.load_state()
    s["current_equity"] = 850.0
    s["deals_today"].append({"profit": 50.0, "r_multiple": 2.0, "symbol": "EURUSD",
                             "side": "buy", "deal_ticket": 1, "ts": "x"})
    sm.save_state(s)
    s2 = sm.load_state()
    assert s2["current_equity"] == 850.0
    assert len(s2["deals_today"]) == 1


def test_migration_from_v0(fresh_state):
    legacy = {
        "starting_balance_today": 800,
        "current_equity": 800,
        "deals_today": [{"profit": 5, "r_multiple": 1, "symbol": "EURUSD", "side": "buy"}],
        "consecutive_losses": 0,
        "locked_until_utc": None,
        "last_reset_date": "2026-01-01",
    }
    fresh_state["state"].write_text(json.dumps(legacy))
    s = sm.load_state()
    assert s["_schema_version"] == 1
    assert s["deals_today"][0]["deal_ticket"] is None  # backfilled


def test_corrupt_state_is_recovered(fresh_state):
    fresh_state["state"].write_text("{ this is not json")
    s = sm.load_state()
    assert s["_schema_version"] == 1
    # A backup file should exist next to the state, named state.corrupt.<ts>.
    assert any(".corrupt." in p.name for p in fresh_state["state"].parent.iterdir())
