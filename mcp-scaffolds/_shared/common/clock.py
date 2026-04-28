"""Clock helpers — deterministic UTC normalization.

Port of xm-mt5-trading-platform/src/common/clock.py. No behavior change.
"""
from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime for internal consistency."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(timezone.utc)


__all__ = ["ensure_utc", "utc_now"]
