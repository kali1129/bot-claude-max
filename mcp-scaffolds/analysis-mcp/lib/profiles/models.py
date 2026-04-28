"""Typed models for local bounded analysis profiles.

Port of xm-mt5-trading-platform/src/analysis/profile_models.py.
Adapted to import from _shared instead of the legacy common package.
No logic changes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

# ── _shared path bootstrap ────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SHARED_PARENT = _HERE.parent.parent.parent  # lib/profiles/ → lib/ → analysis-mcp/ → mcp-scaffolds/
if str(_SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(_SHARED_PARENT))

from _shared.common.clock import ensure_utc  # noqa: E402
from _shared.common.enums import ImpactLevel  # noqa: E402


# ── Timing window ─────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AnalysisTimingWindow:
    """Bounded holding-window guidance for supervised operation."""

    min_holding_minutes: int | None = None
    max_holding_minutes: int | None = None
    preferred_holding_window_minutes: int | None = None
    time_based_exit_enabled: bool = False
    session_end_exit_enabled: bool = False
    volatility_exit_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "min_holding_minutes": self.min_holding_minutes,
            "max_holding_minutes": self.max_holding_minutes,
            "preferred_holding_window_minutes": self.preferred_holding_window_minutes,
            "time_based_exit_enabled": self.time_based_exit_enabled,
            "session_end_exit_enabled": self.session_end_exit_enabled,
            "volatility_exit_enabled": self.volatility_exit_enabled,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AnalysisTimingWindow | None":
        if not isinstance(payload, dict):
            return None
        return cls(
            min_holding_minutes=_optional_int(payload.get("min_holding_minutes")),
            max_holding_minutes=_optional_int(payload.get("max_holding_minutes")),
            preferred_holding_window_minutes=_optional_int(
                payload.get("preferred_holding_window_minutes")
            ),
            time_based_exit_enabled=bool(payload.get("time_based_exit_enabled", False)),
            session_end_exit_enabled=bool(payload.get("session_end_exit_enabled", False)),
            volatility_exit_enabled=bool(payload.get("volatility_exit_enabled", False)),
        )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


# ── Enums ─────────────────────────────────────────────────────────────────────

class AnalysisGate(str, Enum):
    """Allowed bounded outputs from local analysis profiles."""

    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REDUCE_RISK = "REDUCE_RISK"
    REVIEW = "REVIEW"


class AnalysisProfileExecutionStatus(str, Enum):
    """Execution lifecycle for one profile run."""

    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    DISABLED = "DISABLED"
    MISSING_INPUT_FALLBACK = "MISSING_INPUT_FALLBACK"
    TIMEOUT_FALLBACK = "TIMEOUT_FALLBACK"
    ERROR_FALLBACK = "ERROR_FALLBACK"


# ── Context ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AnalysisProfileContext:
    """Inputs available to one local bounded analysis profile."""

    symbol: str
    timestamp: Any
    timeframe: str | None = None
    context_age_seconds: float | None = None
    collected_headlines: tuple[dict[str, Any], ...] | None = None
    relevant_headlines: tuple[dict[str, Any], ...] | None = None
    stale_headlines: tuple[dict[str, Any], ...] | None = None
    active_events: tuple[dict[str, Any], ...] | None = None
    market_data: dict[str, Any] | None = None
    operational_state: dict[str, Any] | None = None
    anomaly_signals: tuple[str, ...] | None = None
    log_lines: tuple[str, ...] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", ensure_utc(self.timestamp))

    def has_input(self, input_name: str) -> bool:
        """Return True when the requested input surface is present."""
        normalized = input_name.strip().lower()
        mapping = {
            "headlines": self.collected_headlines is not None,
            "relevant_headlines": self.relevant_headlines is not None,
            "stale_headlines": self.stale_headlines is not None,
            "active_events": self.active_events is not None,
            "market_data": self.market_data is not None,
            "operational_state": self.operational_state is not None,
            "anomaly_signals": self.anomaly_signals is not None,
            "log_lines": self.log_lines is not None,
            "context_age_seconds": self.context_age_seconds is not None,
        }
        return mapping.get(normalized, False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "timeframe": self.timeframe,
            "context_age_seconds": self.context_age_seconds,
            "collected_headlines": (
                None if self.collected_headlines is None else list(self.collected_headlines)
            ),
            "relevant_headlines": (
                None if self.relevant_headlines is None else list(self.relevant_headlines)
            ),
            "stale_headlines": (
                None if self.stale_headlines is None else list(self.stale_headlines)
            ),
            "active_events": (
                None if self.active_events is None else list(self.active_events)
            ),
            "market_data": (
                None if self.market_data is None else dict(self.market_data)
            ),
            "operational_state": (
                None if self.operational_state is None else dict(self.operational_state)
            ),
            "anomaly_signals": (
                None if self.anomaly_signals is None else list(self.anomaly_signals)
            ),
            "log_lines": (
                None if self.log_lines is None else list(self.log_lines)
            ),
            "metadata": dict(self.metadata),
        }


# ── Profile definition ────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AnalysisProfileDefinition:
    """Configuration for one local bounded analysis profile."""

    name: str
    enabled: bool = True
    timeout_seconds: float = 0.05
    required_inputs: tuple[str, ...] = ()
    skip_gate: AnalysisGate = AnalysisGate.ALLOW
    missing_input_gate: AnalysisGate = AnalysisGate.ALLOW
    timeout_gate: AnalysisGate = AnalysisGate.REVIEW
    error_gate: AnalysisGate = AnalysisGate.REVIEW
    impact_level: ImpactLevel = ImpactLevel.LOW
    timing_window: AnalysisTimingWindow | None = None
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "timeout_seconds": self.timeout_seconds,
            "required_inputs": list(self.required_inputs),
            "skip_gate": self.skip_gate.value,
            "missing_input_gate": self.missing_input_gate.value,
            "timeout_gate": self.timeout_gate.value,
            "error_gate": self.error_gate.value,
            "impact_level": self.impact_level.value,
            "timing_window": (
                None if self.timing_window is None else self.timing_window.to_dict()
            ),
            "params": dict(self.params),
        }


# ── Results ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class AnalysisProfileResult:
    """Structured output from one local bounded analysis profile."""

    profile_name: str
    decision_gate: AnalysisGate
    impact_level: ImpactLevel
    reasons: tuple[str, ...]
    confidence_info: dict[str, Any] = field(default_factory=dict)
    execution_status: AnalysisProfileExecutionStatus = AnalysisProfileExecutionStatus.COMPLETED
    duration_ms: int = 0
    used_fallback: bool = False
    missing_inputs: tuple[str, ...] = ()
    summary: str = ""
    timing_window: AnalysisTimingWindow | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile_name": self.profile_name,
            "decision_gate": self.decision_gate.value,
            "impact_level": self.impact_level.value,
            "reasons": list(self.reasons),
            "confidence_info": dict(self.confidence_info),
            "execution_status": self.execution_status.value,
            "duration_ms": self.duration_ms,
            "used_fallback": self.used_fallback,
            "missing_inputs": list(self.missing_inputs),
            "summary": self.summary,
            "timing_window": (
                None if self.timing_window is None else self.timing_window.to_dict()
            ),
        }


@dataclass(frozen=True, slots=True)
class AnalysisChainConfig:
    """Full config for local bounded analysis profiles."""

    enabled: bool
    default_chain: tuple[str, ...]
    profiles: dict[str, AnalysisProfileDefinition]
    config_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "default_chain": list(self.default_chain),
            "profiles": {
                name: profile.to_dict() for name, profile in self.profiles.items()
            },
            "config_path": self.config_path,
        }


@dataclass(frozen=True, slots=True)
class AnalysisChainResult:
    """Aggregated result from one profile chain execution."""

    chain_name: str
    decision_gate: AnalysisGate
    impact_level: ImpactLevel
    reason_codes: tuple[str, ...]
    profile_results: tuple[AnalysisProfileResult, ...]
    skipped_profiles: int = 0
    fallback_profiles: int = 0
    timed_out_profiles: int = 0
    summary: str = ""
    timing_window: AnalysisTimingWindow | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_name": self.chain_name,
            "decision_gate": self.decision_gate.value,
            "impact_level": self.impact_level.value,
            "reason_codes": list(self.reason_codes),
            "profile_results": [p.to_dict() for p in self.profile_results],
            "skipped_profiles": self.skipped_profiles,
            "fallback_profiles": self.fallback_profiles,
            "timed_out_profiles": self.timed_out_profiles,
            "summary": self.summary,
            "timing_window": (
                None if self.timing_window is None else self.timing_window.to_dict()
            ),
        }


__all__ = [
    "AnalysisChainConfig",
    "AnalysisChainResult",
    "AnalysisGate",
    "AnalysisProfileContext",
    "AnalysisProfileDefinition",
    "AnalysisProfileExecutionStatus",
    "AnalysisProfileResult",
    "AnalysisTimingWindow",
]
