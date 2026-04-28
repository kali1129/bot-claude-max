"""Registry of deterministic local bounded analysis profiles.

Port of xm-mt5-trading-platform/src/analysis/profile_registry.py.
Adapted to import from _shared and the new profiles package layout.
No logic changes.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

# ── _shared path bootstrap ────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SHARED_PARENT = _HERE.parent.parent.parent  # profiles/ → lib/ → analysis-mcp/ → mcp-scaffolds/
if str(_SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(_SHARED_PARENT))

from _shared.common.enums import ImpactLevel  # noqa: E402

from .models import (  # noqa: E402
    AnalysisGate,
    AnalysisProfileContext,
    AnalysisProfileDefinition,
    AnalysisProfileResult,
    AnalysisTimingWindow,
)


ProfileEvaluator = Callable[
    [AnalysisProfileContext, AnalysisProfileDefinition],
    AnalysisProfileResult,
]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _result(
    profile_name: str,
    *,
    gate: AnalysisGate,
    impact_level: ImpactLevel,
    reasons: list[str] | tuple[str, ...],
    score: float,
    summary: str,
    notes: list[str] | None = None,
    timing_window: AnalysisTimingWindow | None = None,
) -> AnalysisProfileResult:
    return AnalysisProfileResult(
        profile_name=profile_name,
        decision_gate=gate,
        impact_level=impact_level,
        reasons=tuple(reasons),
        confidence_info={
            "score": score,
            "source": f"analysis_profile:{profile_name}",
            "notes": list(notes or []),
        },
        summary=summary,
        timing_window=timing_window,
    )


def _resolve_symbol_spread_thresholds(
    *,
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
    default_reduce: float,
    default_block: float,
) -> tuple[float, float]:
    market = dict(context.market_data or {})
    configured_block = _to_float(market.get("configured_block_spread_points"), -1.0)
    configured_reduce = _to_float(market.get("configured_reduce_spread_points"), -1.0)
    if configured_block > 0.0:
        block_spread_points = configured_block
        if configured_reduce > 0.0:
            reduce_spread_points = min(block_spread_points, configured_reduce)
        elif block_spread_points <= 1.0:
            reduce_spread_points = block_spread_points
        else:
            reduce_spread_points = max(
                1.0, min(block_spread_points - 1.0, block_spread_points * 0.8)
            )
        return reduce_spread_points, block_spread_points
    return (
        _to_float(definition.params.get("reduce_spread_points"), default_reduce),
        _to_float(definition.params.get("block_spread_points"), default_block),
    )


# ── Built-in evaluators ───────────────────────────────────────────────────────

def _market_watch(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    market = dict(context.market_data or {})
    quote_age = _to_float(market.get("quote_age_seconds"), -1.0)
    spread_points = _to_float(market.get("spread_points"), -1.0)
    terminal_connected = market.get("terminal_connected")
    trade_allowed = market.get("trade_allowed")

    if terminal_connected is False:
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.HIGH,
            reasons=["MARKET_TERMINAL_DISCONNECTED"],
            score=0.95,
            summary="Market terminal connectivity is unavailable.",
            notes=["Terminal connectivity is required for safe live context evaluation."],
            timing_window=definition.timing_window,
        )

    block_quote_age = _to_float(definition.params.get("block_quote_age_seconds"), 120.0)
    review_quote_age = _to_float(definition.params.get("review_quote_age_seconds"), 30.0)
    if quote_age >= block_quote_age:
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.HIGH,
            reasons=["MARKET_QUOTE_STALE"],
            score=0.90,
            summary="Quote age exceeds the configured block threshold.",
            timing_window=definition.timing_window,
        )
    if quote_age >= review_quote_age:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["MARKET_QUOTE_AGING"],
            score=0.55,
            summary="Quote age exceeds the configured review threshold.",
            timing_window=definition.timing_window,
        )

    reduce_spread, block_spread = _resolve_symbol_spread_thresholds(
        context=context, definition=definition, default_reduce=25.0, default_block=80.0
    )
    if spread_points >= block_spread:
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.HIGH,
            reasons=["MARKET_SPREAD_EXTREME"],
            score=0.90,
            summary="Spread is above the configured block threshold.",
            timing_window=definition.timing_window,
        )
    if spread_points >= reduce_spread:
        return _result(
            definition.name,
            gate=AnalysisGate.REDUCE_RISK,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["MARKET_SPREAD_ELEVATED"],
            score=0.65,
            summary="Spread is above the configured reduce-risk threshold.",
            timing_window=definition.timing_window,
        )

    if trade_allowed is False:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["MARKET_TRADE_NOT_ALLOWED"],
            score=0.50,
            summary="Market state reports trade-not-allowed.",
            timing_window=definition.timing_window,
        )

    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["MARKET_STATE_ACCEPTABLE"],
        score=0.85,
        summary="Market state is acceptable for bounded context evaluation.",
        timing_window=definition.timing_window,
    )


def _news_scan(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    relevant_count = len(context.relevant_headlines or ())
    stale_count = len(context.stale_headlines or ())
    collected_count = len(context.collected_headlines or ())
    conflicting = bool(context.metadata.get("sentiment_conflicting", False))

    if conflicting:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["CONFLICTING_HEADLINES"],
            score=0.30,
            summary="Fresh headlines conflict materially across approved sources.",
            timing_window=definition.timing_window,
        )
    if stale_count > 0 and relevant_count <= 0:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["STALE_HEADLINES"],
            score=0.35,
            summary="Only stale relevant headlines are available.",
            timing_window=definition.timing_window,
        )
    if collected_count <= 0:
        return _result(
            definition.name,
            gate=AnalysisGate.ALLOW,
            impact_level=ImpactLevel.LOW,
            reasons=["EMPTY_NEWS_FALLBACK"],
            score=0.80,
            summary="No fresh headlines were collected.",
            timing_window=definition.timing_window,
        )
    if relevant_count <= 0:
        return _result(
            definition.name,
            gate=AnalysisGate.ALLOW,
            impact_level=ImpactLevel.LOW,
            reasons=["NO_RELEVANT_HEADLINES"],
            score=0.80,
            summary="Collected headlines are not relevant for the requested symbol.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["NEWS_SCAN_ACCEPTABLE"],
        score=0.75,
        summary="News scan found no blocking or reducing conflicts.",
        timing_window=definition.timing_window,
    )


def _macro_window(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    active_events = tuple(context.active_events or ())
    high_active = [
        e for e in active_events if str(e.get("impact_level", "")).lower() == "high"
    ]
    medium_active = [
        e for e in active_events if str(e.get("impact_level", "")).lower() == "medium"
    ]
    if high_active:
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.HIGH,
            reasons=["EVENT_WINDOW_HIGH_IMPACT"],
            score=0.95,
            summary="Active high-impact macro window detected.",
            timing_window=definition.timing_window,
        )
    if medium_active:
        return _result(
            definition.name,
            gate=AnalysisGate.REDUCE_RISK,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["EVENT_WINDOW_MEDIUM_IMPACT"],
            score=0.70,
            summary="Active medium-impact macro window detected.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["NO_ACTIVE_MACRO_WINDOW"],
        score=0.85,
        summary="No active macro event windows are affecting the symbol.",
        timing_window=definition.timing_window,
    )


def _anomaly_check(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    signals = {
        item.strip().upper() for item in (context.anomaly_signals or ()) if item.strip()
    }
    block_signals = {
        str(item).strip().upper()
        for item in definition.params.get(
            "block_signals",
            ["MT5_DISCONNECTED", "BRIDGE_STALE", "BROKER_STATE_DRIFT"],
        )
    }
    review_signals = {
        str(item).strip().upper()
        for item in definition.params.get(
            "review_signals",
            ["RECONCILIATION_PENDING", "STARTUP_DEGRADED", "NEWS_CONTEXT_STALE"],
        )
    }
    matched_block = sorted(signals & block_signals)
    matched_review = sorted(signals & review_signals)
    if matched_block:
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.HIGH,
            reasons=matched_block,
            score=0.90,
            summary="Blocking operational anomalies were detected.",
            timing_window=definition.timing_window,
        )
    if matched_review:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=matched_review,
            score=0.55,
            summary="Operational anomalies require bounded review.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["NO_OPERATIONAL_ANOMALIES"],
        score=0.85,
        summary="No blocking anomaly signals were detected.",
        timing_window=definition.timing_window,
    )


def _log_review(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    lines = [line.upper() for line in (context.log_lines or ())]
    block_kw = [
        str(k).upper()
        for k in definition.params.get("block_keywords", ["CRITICAL", "TRACEBACK", "FATAL"])
    ]
    review_kw = [
        str(k).upper()
        for k in definition.params.get("review_keywords", ["ERROR", "REJECTED", "TIMEOUT"])
    ]
    if any(kw in line for kw in block_kw for line in lines):
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.HIGH,
            reasons=["LOG_CRITICAL_FINDING"],
            score=0.85,
            summary="Critical log patterns were detected in the supplied log sample.",
            timing_window=definition.timing_window,
        )
    if any(kw in line for kw in review_kw for line in lines):
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["LOG_REVIEW_FINDING"],
            score=0.50,
            summary="Non-critical log patterns require operator review.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["LOG_REVIEW_CLEAR"],
        score=0.80,
        summary="No blocking log patterns were detected.",
        timing_window=definition.timing_window,
    )


def _pretrade_context(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    max_age = _to_float(definition.params.get("max_context_age_seconds"), 900.0)
    if context.context_age_seconds is None:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["MISSING_CONTEXT_TIMESTAMP"],
            score=0.20,
            summary="The pre-trade context timestamp is missing.",
            timing_window=definition.timing_window,
        )
    if context.context_age_seconds > max_age:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["CONTEXT_TIMESTAMP_STALE"],
            score=0.20,
            summary="The pre-trade context timestamp exceeds the configured freshness bound.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["PRETRADE_CONTEXT_FRESH"],
        score=0.90,
        summary="Pre-trade context is present and fresh.",
        timing_window=definition.timing_window,
    )


def _spread_watch(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    market = dict(context.market_data or {})
    spread_points = _to_float(market.get("spread_points"), -1.0)
    reduce_spread, block_spread = _resolve_symbol_spread_thresholds(
        context=context, definition=definition, default_reduce=25.0, default_block=80.0
    )
    if spread_points >= block_spread:
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.HIGH,
            reasons=["SPREAD_BLOCK_THRESHOLD_EXCEEDED"],
            score=0.92,
            summary="Spread exceeds the configured block threshold.",
            timing_window=definition.timing_window,
        )
    if spread_points >= reduce_spread:
        return _result(
            definition.name,
            gate=AnalysisGate.REDUCE_RISK,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["SPREAD_REDUCE_THRESHOLD_EXCEEDED"],
            score=0.68,
            summary="Spread exceeds the configured reduce-risk threshold.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["SPREAD_WITHIN_BOUND"],
        score=0.88,
        summary="Spread is within the configured profile bound.",
        timing_window=definition.timing_window,
    )


def _reconcile_watch(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    operational = dict(context.operational_state or {})
    pending_count = _to_int(operational.get("reconciliation_pending_count"), 0)
    deferred_count = _to_int(operational.get("reconciliation_deferred_count"), 0)
    mismatch_count = _to_int(operational.get("reconciliation_mismatch_count"), 0)
    pending_threshold = _to_int(definition.params.get("pending_review_threshold"), 3)
    deferred_threshold = _to_int(definition.params.get("deferred_review_threshold"), 2)
    if mismatch_count > 0:
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.HIGH,
            reasons=["RECONCILIATION_MISMATCH_PRESENT"],
            score=0.95,
            summary="Reconciliation mismatches are present.",
            timing_window=definition.timing_window,
        )
    if pending_count >= pending_threshold or deferred_count >= deferred_threshold:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["RECONCILIATION_BACKLOG_ELEVATED"],
            score=0.55,
            summary="Reconciliation backlog exceeds the configured review threshold.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["RECONCILIATION_STABLE"],
        score=0.85,
        summary="Reconciliation state is within configured thresholds.",
        timing_window=definition.timing_window,
    )


def _risk_review(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    operational = dict(context.operational_state or {})
    consecutive_losses = _to_int(operational.get("consecutive_losses"), 0)
    reduce_after_losses = _to_int(definition.params.get("reduce_after_losses"), 1)
    open_positions = _to_int(operational.get("open_positions"), 0)
    max_open_positions = _to_int(operational.get("max_open_positions"), 1)
    reduced_risk_mode = bool(operational.get("reduced_risk_mode_active", False))

    if reduced_risk_mode or consecutive_losses >= reduce_after_losses:
        return _result(
            definition.name,
            gate=AnalysisGate.REDUCE_RISK,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["RISK_CONTEXT_REDUCED_MODE"],
            score=0.70,
            summary="Operational risk context indicates reduced-risk mode.",
            timing_window=definition.timing_window,
        )
    if open_positions >= max_open_positions > 0:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["RISK_POSITION_CAP_NEAR"],
            score=0.45,
            summary="Open positions are at or above the configured maximum.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["RISK_CONTEXT_STABLE"],
        score=0.80,
        summary="Risk context does not require additional bounded gating.",
        timing_window=definition.timing_window,
    )


def _session_watch(
    context: AnalysisProfileContext,
    definition: AnalysisProfileDefinition,
) -> AnalysisProfileResult:
    operational = dict(context.operational_state or {})
    session_allowed = operational.get("session_allowed")
    session_reason = str(operational.get("session_reason", "")).strip()
    if session_allowed is False:
        return _result(
            definition.name,
            gate=AnalysisGate.BLOCK,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["SESSION_NOT_ALLOWED"],
            score=0.90,
            summary=session_reason or "Session is outside the configured operating window.",
            timing_window=definition.timing_window,
        )
    if session_allowed is None:
        return _result(
            definition.name,
            gate=AnalysisGate.REVIEW,
            impact_level=ImpactLevel.MEDIUM,
            reasons=["SESSION_CONTEXT_INCOMPLETE"],
            score=0.30,
            summary="Session context is incomplete.",
            timing_window=definition.timing_window,
        )
    return _result(
        definition.name,
        gate=AnalysisGate.ALLOW,
        impact_level=ImpactLevel.LOW,
        reasons=["SESSION_ALLOWED"],
        score=0.90,
        summary="Session context is acceptable.",
        timing_window=definition.timing_window,
    )


# ── Registry ──────────────────────────────────────────────────────────────────

class ProfileRegistry:
    """Registry of named deterministic local bounded analysis profiles."""

    def __init__(self, evaluators: dict[str, ProfileEvaluator] | None = None) -> None:
        self._evaluators = dict(evaluators or self.default_evaluators())

    @staticmethod
    def default_evaluators() -> dict[str, ProfileEvaluator]:
        return {
            "market_watch": _market_watch,
            "news_scan": _news_scan,
            "macro_window": _macro_window,
            "anomaly_check": _anomaly_check,
            "log_review": _log_review,
            "pretrade_context": _pretrade_context,
            "spread_watch": _spread_watch,
            "reconcile_watch": _reconcile_watch,
            "risk_review": _risk_review,
            "session_watch": _session_watch,
        }

    def names(self) -> tuple[str, ...]:
        return tuple(self._evaluators.keys())

    def get(self, name: str) -> ProfileEvaluator | None:
        return self._evaluators.get(name)

    def evaluate(
        self,
        name: str,
        *,
        context: AnalysisProfileContext,
        definition: AnalysisProfileDefinition,
    ) -> AnalysisProfileResult:
        evaluator = self.get(name)
        if evaluator is None:
            raise KeyError(f"Unknown analysis profile: {name!r}")
        return evaluator(context, definition)


__all__ = ["ProfileEvaluator", "ProfileRegistry"]
