"""Trading-session labeling and time-of-day features.

Port of xm-mt5-trading-platform/src/features/session_features.py. Useful for
both analysis (regime detection) and risk (session-based filters).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True, slots=True)
class SessionFeatureSet:
    """Human-readable session label plus numeric features."""

    label: str
    values: dict[str, float]


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def session_label(timestamp: datetime) -> str:
    """Return a deterministic session label from a UTC timestamp."""
    value = _ensure_utc(timestamp)
    if value.weekday() >= 5:
        return "WEEKEND"

    hour = value.hour
    if 0 <= hour < 7:
        return "ASIA"
    if 7 <= hour < 12:
        return "LONDON"
    if 12 <= hour < 17:
        return "NEW_YORK"
    if 17 <= hour < 22:
        return "US_CLOSE"
    return "OFF_HOURS"


def session_features(timestamp: datetime) -> SessionFeatureSet:
    """Return numeric session features and the matching label."""
    value = _ensure_utc(timestamp)
    label = session_label(value)
    hour_fraction = (value.hour * 60 + value.minute) / 1440.0
    weekday = float(value.weekday())
    return SessionFeatureSet(
        label=label,
        values={
            "hour_fraction": hour_fraction,
            "weekday": weekday,
            "is_asia_session": 1.0 if label == "ASIA" else 0.0,
            "is_london_session": 1.0 if label == "LONDON" else 0.0,
            "is_new_york_session": 1.0 if label == "NEW_YORK" else 0.0,
            "is_us_close_session": 1.0 if label == "US_CLOSE" else 0.0,
            "is_weekend": 1.0 if label == "WEEKEND" else 0.0,
            "is_off_hours": 1.0 if label == "OFF_HOURS" else 0.0,
        },
    )


__all__ = ["SessionFeatureSet", "session_label", "session_features"]
