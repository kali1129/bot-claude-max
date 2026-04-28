"""Deterministic event-calendar windows for pre-trade gating.

Port of xm-mt5-trading-platform/src/news/event_calendar.py.

Adapted: ImpactLevel from `_shared.common.enums`. The legacy
`from_news_events(NewsEvent...)` constructor is replaced by a friendlier
`from_dicts` that takes plain dicts so callers don't need a legacy class.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

_HERE = Path(__file__).resolve().parent
_SHARED_PARENT = _HERE.parent.parent
if str(_SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(_SHARED_PARENT))

from _shared.common.enums import ImpactLevel  # noqa: E402


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        try:
            return _ensure_utc(datetime.fromisoformat(s))
        except ValueError:
            pass
    raise ValueError(f"Unsupported timestamp value: {value!r}")


def _coerce_impact(value: Any) -> ImpactLevel:
    if isinstance(value, ImpactLevel):
        return value
    if isinstance(value, str):
        try:
            return ImpactLevel(value.lower())
        except ValueError:
            pass
    return ImpactLevel.LOW


@dataclass(frozen=True, slots=True)
class CalendarEvent:
    """One scheduled macro event relevant to one or more assets."""

    event_id: str
    title: str
    timestamp: datetime
    impact_level: ImpactLevel
    symbols: tuple[str, ...] = ()
    asset_classes: tuple[str, ...] = ()
    macro_theme: str | None = None
    source: str = "calendar"
    window_before_minutes: int = 30
    window_after_minutes: int = 30

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", _ensure_utc(self.timestamp))

    def applies_to(self, symbol: str, *, asset_class: str | None = None) -> bool:
        normalized_symbol = symbol.upper()
        if self.symbols and normalized_symbol in self.symbols:
            return True
        if (
            self.asset_classes
            and asset_class is not None
            and asset_class.upper() in self.asset_classes
        ):
            return True
        return not self.symbols and not self.asset_classes

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "title": self.title,
            "timestamp": self.timestamp.isoformat(),
            "impact_level": self.impact_level.value,
            "symbols": list(self.symbols),
            "asset_classes": list(self.asset_classes),
            "macro_theme": self.macro_theme,
            "source": self.source,
            "window_before_minutes": self.window_before_minutes,
            "window_after_minutes": self.window_after_minutes,
        }


@dataclass(frozen=True, slots=True)
class EventWindow:
    """Active or upcoming gating window around a scheduled event."""

    event: CalendarEvent
    starts_at: datetime
    ends_at: datetime
    minutes_until_event: float
    active: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "starts_at", _ensure_utc(self.starts_at))
        object.__setattr__(self, "ends_at", _ensure_utc(self.ends_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event.to_dict(),
            "starts_at": self.starts_at.isoformat(),
            "ends_at": self.ends_at.isoformat(),
            "minutes_until_event": self.minutes_until_event,
            "active": self.active,
        }


class EventCalendar:
    """Filters scheduled events into actionable windows for one symbol."""

    def __init__(self, events: Iterable[CalendarEvent] | None = None) -> None:
        self.events: list[CalendarEvent] = list(events or [])

    @classmethod
    def from_dicts(
        cls,
        events: Iterable[Mapping[str, Any]],
        *,
        default_before_minutes: int = 30,
        default_after_minutes: int = 30,
    ) -> "EventCalendar":
        """Build a calendar from a list of plain dicts.

        Each dict needs at least: title, timestamp, impact_level (or impact).
        Optional: event_id, symbols, asset_classes, macro_theme, source,
        window_before_minutes, window_after_minutes.
        """
        out: list[CalendarEvent] = []
        for index, raw in enumerate(events):
            symbols = tuple(s.upper() for s in raw.get("symbols", ()))
            asset_classes = tuple(s.upper() for s in raw.get("asset_classes", ()))
            impact = _coerce_impact(raw.get("impact_level", raw.get("impact", "low")))
            ts = _parse_dt(raw.get("timestamp", raw.get("time")))
            out.append(
                CalendarEvent(
                    event_id=str(raw.get("event_id", f"event-{index:04d}")),
                    title=str(raw.get("title", "")),
                    timestamp=ts,
                    impact_level=impact,
                    symbols=symbols,
                    asset_classes=asset_classes,
                    macro_theme=raw.get("macro_theme"),
                    source=str(raw.get("source", "calendar")),
                    window_before_minutes=int(
                        raw.get("window_before_minutes", default_before_minutes)
                    ),
                    window_after_minutes=int(
                        raw.get("window_after_minutes", default_after_minutes)
                    ),
                )
            )
        return cls(out)

    def extend(self, events: Iterable[CalendarEvent]) -> None:
        self.events.extend(events)

    def windows_for_symbol(
        self,
        *,
        as_of: datetime,
        symbol: str,
        asset_class: str | None = None,
    ) -> list[EventWindow]:
        reference = _ensure_utc(as_of)
        windows: list[EventWindow] = []
        for event in self.events:
            if not event.applies_to(symbol, asset_class=asset_class):
                continue
            starts_at = event.timestamp - timedelta(minutes=event.window_before_minutes)
            ends_at = event.timestamp + timedelta(minutes=event.window_after_minutes)
            minutes_until = (event.timestamp - reference).total_seconds() / 60.0
            active = starts_at <= reference <= ends_at
            if reference > ends_at:
                continue
            windows.append(
                EventWindow(
                    event=event,
                    starts_at=starts_at,
                    ends_at=ends_at,
                    minutes_until_event=minutes_until,
                    active=active,
                )
            )
        windows.sort(key=lambda item: (not item.active, abs(item.minutes_until_event)))
        return windows


__all__ = ["CalendarEvent", "EventWindow", "EventCalendar"]
