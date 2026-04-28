"""Timeframe helpers.

Port of xm-mt5-trading-platform/src/common/timeframes.py. Used by the
trading-mt5-mcp and analysis-mcp to map between strings and MT5 constants.
"""
from __future__ import annotations

from datetime import timedelta
from enum import Enum
from typing import Any


class Timeframe(str, Enum):
    """Supported platform timeframes."""

    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    M30 = "M30"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"

    @property
    def minutes(self) -> int:
        mapping = {
            Timeframe.M1: 1,
            Timeframe.M5: 5,
            Timeframe.M15: 15,
            Timeframe.M30: 30,
            Timeframe.H1: 60,
            Timeframe.H4: 240,
            Timeframe.D1: 1440,
        }
        return mapping[self]

    @property
    def seconds(self) -> int:
        return self.minutes * 60

    @property
    def delta(self) -> timedelta:
        return timedelta(seconds=self.seconds)

    @property
    def mt5_name(self) -> str:
        return f"TIMEFRAME_{self.value}"


SUPPORTED_TIMEFRAMES = tuple(timeframe.value for timeframe in Timeframe)


def normalize_timeframe(value: str | Timeframe) -> Timeframe:
    """Normalize a timeframe string into a supported enum."""
    if isinstance(value, Timeframe):
        return value
    return Timeframe(value.strip().upper())


def timeframe_to_timedelta(value: str | Timeframe) -> timedelta:
    """Return the expected interval for a timeframe."""
    return normalize_timeframe(value).delta


def timeframe_to_minutes(value: str | Timeframe) -> int:
    """Return timeframe length in minutes."""
    return normalize_timeframe(value).minutes


def timeframe_to_mt5_constant(mt5_module: Any, value: str | Timeframe) -> Any:
    """Resolve the MetaTrader 5 constant for a timeframe."""
    timeframe = normalize_timeframe(value)
    constant = getattr(mt5_module, timeframe.mt5_name, None)
    if constant is None:
        raise ValueError(f"Unsupported MT5 timeframe: {timeframe.value}")
    return constant


__all__ = [
    "Timeframe",
    "SUPPORTED_TIMEFRAMES",
    "normalize_timeframe",
    "timeframe_to_timedelta",
    "timeframe_to_minutes",
    "timeframe_to_mt5_constant",
]
