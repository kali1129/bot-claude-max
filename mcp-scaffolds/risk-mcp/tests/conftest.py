"""Test wiring: import paths + fresh state per test."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))                  # for lib/, server.py
sys.path.insert(0, str(ROOT.parent / "_shared"))  # for rules.py


import pytest


@pytest.fixture
def fresh_state(tmp_path, monkeypatch):
    """Each test gets isolated state.json + deals.jsonl in tmp_path."""
    state = tmp_path / "state.json"
    deals = tmp_path / "deals.jsonl"
    monkeypatch.setenv("STATE_FILE", str(state))
    monkeypatch.setenv("DEALS_FILE", str(deals))
    monkeypatch.setenv("STARTING_BALANCE", "800")
    yield {"state": state, "deals": deals}
