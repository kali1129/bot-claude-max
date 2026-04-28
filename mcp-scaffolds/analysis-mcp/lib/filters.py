"""Session and spread filters.

Port of xm-mt5-trading-platform/src/filters/session_filter.py. Adapted to
take a plain dict-shaped bar instead of the legacy `MarketBar` and to take
filter settings as a dataclass without the legacy `settings.models` dep.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class FilterSettings:
    """Configuration for the session/spread filter."""

    allowed_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)  # Mon..Fri
    start_hour_utc: int = 7  # London open
    end_hour_utc: int = 21   # NY close
    max_spread_points: float = 25.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "FilterSettings":
        payload = dict(data or {})
        weekdays_raw = payload.get("allowed_weekdays", (0, 1, 2, 3, 4))
        if isinstance(weekdays_raw, (list, tuple)):
            allowed = tuple(int(v) for v in weekdays_raw)
        else:
            allowed = (0, 1, 2, 3, 4)
        return cls(
            allowed_weekdays=allowed,
            start_hour_utc=int(payload.get("start_hour_utc", 7)),
            end_hour_utc=int(payload.get("end_hour_utc", 21)),
            max_spread_points=float(payload.get("max_spread_points", 25.0)),
        )


@dataclass(slots=True)
class FilterResult:
    """Outcome of a filter evaluation."""

    passed: bool
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"passed": self.passed, "reason": self.reason, "detail": dict(self.detail)}


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        try:
            cleaned = value.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(cleaned)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


class SessionFilter:
    """Blocks signals outside configured trading hours or on wide spreads."""

    def __init__(self, settings: FilterSettings | None = None) -> None:
        self.settings = settings or FilterSettings()

    def evaluate(self, bar: Mapping[str, Any]) -> FilterResult:
        timestamp = _parse_ts(bar.get("time"))
        spread_points = float(bar.get("spread", 0.0))

        if timestamp.weekday() not in self.settings.allowed_weekdays:
            return FilterResult(
                passed=False,
                reason="WEEKDAY_BLOCKED",
                detail={"weekday": timestamp.weekday()},
            )
        if not (self.settings.start_hour_utc <= timestamp.hour < self.settings.end_hour_utc):
            return FilterResult(
                passed=False,
                reason="HOUR_OUTSIDE_WINDOW",
                detail={
                    "hour": timestamp.hour,
                    "window": [self.settings.start_hour_utc, self.settings.end_hour_utc],
                },
            )
        if spread_points > self.settings.max_spread_points:
            return FilterResult(
                passed=False,
                reason="SPREAD_TOO_HIGH",
                detail={
                    "spread_points": spread_points,
                    "max": self.settings.max_spread_points,
                },
            )
        return FilterResult(passed=True, reason="OK", detail={})


def apply_session_filter(
    bar: Mapping[str, Any],
    settings: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Convenience for MCP tool wrappers."""
    s = FilterSettings.from_mapping(settings)
    return SessionFilter(s).evaluate(bar).to_dict()


__all__ = ["FilterSettings", "FilterResult", "SessionFilter", "apply_session_filter"]
