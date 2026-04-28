"""Tests for the shared/common port from xm-mt5-trading-platform."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
from pathlib import Path

import pytest

# Make _shared importable when running pytest from the repo root or scaffold root
_HERE = Path(__file__).resolve().parent
_SCAFFOLDS = _HERE.parent.parent  # mcp-scaffolds/
sys.path.insert(0, str(_SCAFFOLDS))

from _shared.common import (
    Timeframe,
    append_jsonl,
    ensure_utc,
    new_trace_id,
    normalize_timeframe,
    read_jsonl_records,
    read_jsonl_tail,
    session_features,
    session_label,
    timeframe_to_minutes,
    utc_now,
)


# ----- clock -----

def test_ensure_utc_naive_assigns_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    out = ensure_utc(naive)
    assert out.tzinfo == UTC
    assert out.hour == 12  # no shift, just tag


def test_ensure_utc_aware_converts_to_utc():
    eastern = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=-5)))
    out = ensure_utc(eastern)
    assert out.utcoffset() == timedelta(0)
    assert out.hour == 17


def test_utc_now_is_aware():
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


# ----- ids -----

def test_new_trace_id_default_prefix():
    tid = new_trace_id()
    assert tid.startswith("trace-")
    assert len(tid) == len("trace-") + 12


def test_new_trace_id_custom_prefix():
    tid = new_trace_id("audit")
    assert tid.startswith("audit-")


def test_new_trace_id_unique():
    seen = {new_trace_id() for _ in range(50)}
    assert len(seen) == 50


# ----- timeframes -----

def test_normalize_timeframe_string():
    assert normalize_timeframe("M5") is Timeframe.M5
    assert normalize_timeframe("h4") is Timeframe.H4


def test_normalize_timeframe_passthrough():
    assert normalize_timeframe(Timeframe.D1) is Timeframe.D1


def test_timeframe_to_minutes():
    assert timeframe_to_minutes("M1") == 1
    assert timeframe_to_minutes("H4") == 240
    assert timeframe_to_minutes("D1") == 1440


def test_timeframe_invalid_raises():
    with pytest.raises(ValueError):
        normalize_timeframe("M7")


# ----- jsonl -----

def test_append_jsonl_creates_dirs(tmp_path):
    target = tmp_path / "nested" / "dir" / "audit.jsonl"
    append_jsonl(target, {"event": "first", "n": 1})
    assert target.exists()
    records = read_jsonl_records(target)
    assert records == [{"event": "first", "n": 1}]


def test_append_jsonl_appends(tmp_path):
    target = tmp_path / "log.jsonl"
    for i in range(5):
        append_jsonl(target, {"i": i})
    records = read_jsonl_records(target)
    assert [r["i"] for r in records] == [0, 1, 2, 3, 4]


def test_read_jsonl_tail_keeps_order(tmp_path):
    target = tmp_path / "log.jsonl"
    for i in range(20):
        append_jsonl(target, {"i": i})
    tail = read_jsonl_tail(target, max_lines=5)
    assert [r["i"] for r in tail] == [15, 16, 17, 18, 19]


def test_read_jsonl_tail_empty(tmp_path):
    target = tmp_path / "missing.jsonl"
    assert read_jsonl_tail(target) == []


def test_read_jsonl_skips_invalid_lines(tmp_path):
    target = tmp_path / "log.jsonl"
    target.write_text(
        json.dumps({"good": 1}) + "\n" +
        "this is not json\n" +
        json.dumps({"good": 2}) + "\n",
        encoding="utf-8",
    )
    records = read_jsonl_records(target)
    assert records == [{"good": 1}, {"good": 2}]


# ----- sessions -----

def test_session_label_london_window():
    assert session_label(datetime(2026, 4, 27, 9, 30, tzinfo=UTC)) == "LONDON"


def test_session_label_new_york_window():
    assert session_label(datetime(2026, 4, 27, 14, 0, tzinfo=UTC)) == "NEW_YORK"


def test_session_label_weekend():
    # Saturday
    assert session_label(datetime(2026, 4, 25, 12, 0, tzinfo=UTC)) == "WEEKEND"


def test_session_features_one_hot():
    feats = session_features(datetime(2026, 4, 27, 9, 0, tzinfo=UTC))
    assert feats.label == "LONDON"
    assert feats.values["is_london_session"] == 1.0
    assert feats.values["is_new_york_session"] == 0.0
    assert feats.values["is_weekend"] == 0.0


def test_session_features_naive_timestamp_treated_as_utc():
    feats = session_features(datetime(2026, 4, 27, 9, 0))  # naive
    assert feats.label == "LONDON"
