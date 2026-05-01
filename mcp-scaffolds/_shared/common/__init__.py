"""Shared utility primitives.

Ported from xm-mt5-trading-platform/src/common/. Kept dependency-free so any
MCP can import these without dragging the legacy graph along.
"""
from .clock import ensure_utc, utc_now
from .ids import new_trace_id
from .jsonl import append_jsonl, read_jsonl_records, read_jsonl_tail
from .timeframes import (
    SUPPORTED_TIMEFRAMES,
    Timeframe,
    normalize_timeframe,
    timeframe_to_minutes,
    timeframe_to_timedelta,
)
from .sessions import session_features, session_label, SessionFeatureSet
from .enums import GateState, ImpactLevel, impact_rank, max_impact
from . import capital_ledger
from . import expectancy_tracker
from . import regime
from . import correlation
from . import sizing_kelly
from . import user_settings
from . import equity_sampler

__all__ = [
    "ensure_utc",
    "utc_now",
    "new_trace_id",
    "append_jsonl",
    "read_jsonl_records",
    "read_jsonl_tail",
    "SUPPORTED_TIMEFRAMES",
    "Timeframe",
    "normalize_timeframe",
    "timeframe_to_minutes",
    "timeframe_to_timedelta",
    "session_features",
    "session_label",
    "SessionFeatureSet",
    "GateState",
    "ImpactLevel",
    "impact_rank",
    "max_impact",
    "capital_ledger",
    "expectancy_tracker",
    "regime",
    "correlation",
    "sizing_kelly",
    "user_settings",
    "equity_sampler",
]
