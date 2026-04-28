"""Strategy base class + FeatureSnapshot + StrategyDecision.

Ported from xm-mt5-trading-platform/src/strategies/base.py and
xm-mt5-trading-platform/src/common/models.py (FeatureSnapshot subset only).

Adapted for the bot nuevo:
- FeatureSnapshot is a self-contained dataclass (no dep on legacy
  common.models). Same shape as the legacy: `is_fresh`, `values`, `labels`.
- No dependency on legacy SignalAction/Signal types — the MCP tool wrapper
  serializes the StrategyDecision directly into a dict for the protocol.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
import math
from typing import Any, Mapping


ConfidenceValue = bool | float | int | str


@dataclass(slots=True)
class FeatureSnapshot:
    """Bundle of features + labels for a single decision moment."""

    values: dict[str, float] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    is_fresh: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": dict(self.values),
            "labels": dict(self.labels),
            "is_fresh": self.is_fresh,
        }


class StrategyDirection(str, Enum):
    """Normalized deterministic directions emitted by baseline strategies."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


@dataclass(slots=True)
class StrategyDecision:
    """Strategy output before risk controls or routing are applied."""

    strategy_name: str
    direction: StrategyDirection
    rationale_codes: tuple[str, ...] = ()
    confidence_info: dict[str, ConfidenceValue | None] = field(default_factory=dict)

    @property
    def score(self) -> float:
        """Convenience accessor for the 0..1 confidence score."""
        raw = self.confidence_info.get("score", 0.0)
        try:
            value = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0
        return value if math.isfinite(value) else 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for MCP protocol."""
        return {
            "ok": True,
            "strategy": self.strategy_name,
            "direction": self.direction.value,
            "rationale_codes": list(self.rationale_codes),
            "score": self.score,
            "confidence_info": dict(self.confidence_info),
        }


class BaseStrategy(ABC):
    """Base class for deterministic, auditable strategy modules."""

    name: str

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None = None) -> "BaseStrategy":
        """Subclasses override this to build the right config from a dict."""
        return cls()

    @abstractmethod
    def evaluate(self, snapshot: FeatureSnapshot) -> StrategyDecision:
        """Evaluate one feature snapshot and return a deterministic direction."""

    # ----- helpers used by concrete strategies -----

    def long(
        self,
        *codes: str,
        confidence_info: Mapping[str, ConfidenceValue | None] | None = None,
    ) -> StrategyDecision:
        return StrategyDecision(
            strategy_name=self.name,
            direction=StrategyDirection.LONG,
            rationale_codes=tuple(codes),
            confidence_info=dict(confidence_info or {}),
        )

    def short(
        self,
        *codes: str,
        confidence_info: Mapping[str, ConfidenceValue | None] | None = None,
    ) -> StrategyDecision:
        return StrategyDecision(
            strategy_name=self.name,
            direction=StrategyDirection.SHORT,
            rationale_codes=tuple(codes),
            confidence_info=dict(confidence_info or {}),
        )

    def flat(
        self,
        *codes: str,
        confidence_info: Mapping[str, ConfidenceValue | None] | None = None,
    ) -> StrategyDecision:
        return StrategyDecision(
            strategy_name=self.name,
            direction=StrategyDirection.FLAT,
            rationale_codes=tuple(codes),
            confidence_info=dict(confidence_info or {}),
        )

    @staticmethod
    def require_features(
        snapshot: FeatureSnapshot,
        feature_names: tuple[str, ...],
    ) -> tuple[bool, tuple[str, ...]]:
        """Return whether the snapshot has all finite required features."""
        missing: list[str] = []
        for feature_name in feature_names:
            raw_value = snapshot.values.get(feature_name, math.nan)
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                missing.append(feature_name)
                continue
            if not math.isfinite(value):
                missing.append(feature_name)
        return (not missing, tuple(f"MISSING_{name.upper()}" for name in missing))

    @staticmethod
    def session_label(snapshot: FeatureSnapshot) -> str:
        """Return the normalized session label attached to a snapshot."""
        return snapshot.labels.get("session", "UNKNOWN").upper()

    @staticmethod
    def session_is_allowed(
        snapshot: FeatureSnapshot, allowed_sessions: tuple[str, ...]
    ) -> bool:
        """Return True when the snapshot session is in the configured allow list."""
        return BaseStrategy.session_label(snapshot) in {
            value.upper() for value in allowed_sessions
        }

    @staticmethod
    def numeric(snapshot: FeatureSnapshot, feature_name: str) -> float:
        """Return a feature as float, or `nan` when unavailable."""
        raw_value = snapshot.values.get(feature_name, math.nan)
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            return math.nan

    @staticmethod
    def bounded_score(*components: float) -> float:
        """Average positive components into a 0..1 confidence score for logs."""
        finite = [max(0.0, min(value, 1.0)) for value in components if math.isfinite(value)]
        if not finite:
            return 0.0
        return round(sum(finite) / len(finite), 4)


__all__ = [
    "FeatureSnapshot",
    "StrategyDirection",
    "StrategyDecision",
    "BaseStrategy",
    "ConfidenceValue",
]
