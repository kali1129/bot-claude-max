"""Runtime loader and deterministic chain runner for local analysis profiles.

Port of xm-mt5-trading-platform/src/analysis/profile_runner.py.
Adapted to import from _shared and the new profiles package layout.
No logic changes.
"""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

# ── _shared path bootstrap ────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SHARED_PARENT = _HERE.parent.parent.parent  # profiles/ → lib/ → analysis-mcp/ → mcp-scaffolds/
if str(_SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(_SHARED_PARENT))

from _shared.common.enums import ImpactLevel  # noqa: E402

from .models import (  # noqa: E402
    AnalysisChainConfig,
    AnalysisChainResult,
    AnalysisGate,
    AnalysisProfileContext,
    AnalysisProfileDefinition,
    AnalysisProfileExecutionStatus,
    AnalysisProfileResult,
    AnalysisTimingWindow,
)
from .registry import ProfileRegistry  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gate_rank(gate: AnalysisGate) -> int:
    return {
        AnalysisGate.ALLOW: 0,
        AnalysisGate.REDUCE_RISK: 1,
        AnalysisGate.REVIEW: 2,
        AnalysisGate.BLOCK: 3,
    }[gate]


def _impact_rank(level: ImpactLevel) -> int:
    return {ImpactLevel.LOW: 1, ImpactLevel.MEDIUM: 2, ImpactLevel.HIGH: 3}[level]


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _parse_gate(value: Any, default: AnalysisGate) -> AnalysisGate:
    if value is None:
        return default
    try:
        return AnalysisGate(str(value).strip().upper())
    except ValueError:
        return default


def _parse_impact(value: Any, default: ImpactLevel) -> ImpactLevel:
    if value is None:
        return default
    try:
        return ImpactLevel(str(value).strip().lower())
    except ValueError:
        return default


def _fallback_result(
    profile_name: str,
    *,
    gate: AnalysisGate,
    impact_level: ImpactLevel,
    execution_status: AnalysisProfileExecutionStatus,
    reason_codes: list[str],
    summary: str,
    duration_ms: int = 0,
    missing_inputs: tuple[str, ...] = (),
    error: str | None = None,
    timing_window: AnalysisTimingWindow | None = None,
) -> AnalysisProfileResult:
    notes = [summary]
    if error:
        notes.append(error)
    return AnalysisProfileResult(
        profile_name=profile_name,
        decision_gate=gate,
        impact_level=impact_level,
        reasons=tuple(reason_codes),
        confidence_info={
            "score": 0.0,
            "source": f"analysis_profile:{profile_name}",
            "notes": notes,
        },
        execution_status=execution_status,
        duration_ms=duration_ms,
        used_fallback=execution_status
        not in {
            AnalysisProfileExecutionStatus.COMPLETED,
            AnalysisProfileExecutionStatus.SKIPPED,
            AnalysisProfileExecutionStatus.DISABLED,
        },
        missing_inputs=missing_inputs,
        summary=summary,
        timing_window=timing_window,
    )


def _merge_timing_windows(
    results: tuple[AnalysisProfileResult, ...],
) -> AnalysisTimingWindow | None:
    candidates = [r.timing_window for r in results if r.timing_window is not None]
    if not candidates:
        return None
    min_holding = max(
        (c.min_holding_minutes for c in candidates if c.min_holding_minutes is not None),
        default=None,
    )
    max_holding = min(
        (c.max_holding_minutes for c in candidates if c.max_holding_minutes is not None),
        default=None,
    )
    preferred = next(
        (
            c.preferred_holding_window_minutes
            for c in candidates
            if c.preferred_holding_window_minutes is not None
        ),
        None,
    )
    if preferred is not None:
        if min_holding is not None:
            preferred = max(preferred, min_holding)
        if max_holding is not None:
            preferred = min(preferred, max_holding)
    return AnalysisTimingWindow(
        min_holding_minutes=min_holding,
        max_holding_minutes=max_holding,
        preferred_holding_window_minutes=preferred,
        time_based_exit_enabled=any(c.time_based_exit_enabled for c in candidates),
        session_end_exit_enabled=any(c.session_end_exit_enabled for c in candidates),
        volatility_exit_enabled=any(c.volatility_exit_enabled for c in candidates),
    )


# ── Runner ────────────────────────────────────────────────────────────────────

class ProfileRunner:
    """Loads and runs deterministic bounded analysis profiles."""

    def __init__(
        self,
        *,
        config: AnalysisChainConfig,
        registry: ProfileRegistry | None = None,
        perf_counter_fn: Callable[[], float] | None = None,
    ) -> None:
        self.config = config
        self.registry = registry or ProfileRegistry()
        self.perf_counter_fn = perf_counter_fn or time.perf_counter

    # ── Factory helpers ───────────────────────────────────────────────────────

    @classmethod
    def disabled(cls, *, reason: str = "ANALYSIS_PROFILES_DISABLED") -> "ProfileRunner":
        profile = AnalysisProfileDefinition(name="_disabled", enabled=False)
        config = AnalysisChainConfig(
            enabled=False,
            default_chain=(),
            profiles={"_disabled": profile},
            config_path=reason,
        )
        return cls(config=config)

    @classmethod
    def from_yaml(
        cls,
        path: str | Path | None,
        *,
        registry: ProfileRegistry | None = None,
    ) -> "ProfileRunner":
        if path is None:
            return cls.disabled(reason="ANALYSIS_PROFILE_CONFIG_UNSET")
        config_path = Path(path).resolve()
        if not config_path.exists():
            return cls.disabled(reason="ANALYSIS_PROFILE_CONFIG_MISSING")

        loaded_registry = registry or ProfileRegistry()
        try:
            raw_root = _read_yaml(config_path)
        except Exception:
            return cls.disabled(reason="ANALYSIS_PROFILE_CONFIG_INVALID")

        raw = raw_root.get("analysis_profiles", {})
        defaults = dict(raw.get("defaults", {}))
        profiles_raw = dict(raw.get("profiles", {}))
        chain_names = [str(item) for item in raw.get("default_chain", [])]
        candidate_names = (
            set(loaded_registry.names()) | set(profiles_raw.keys()) | set(chain_names)
        )

        definitions: dict[str, AnalysisProfileDefinition] = {}
        for name in sorted(candidate_names):
            profile_raw = dict(profiles_raw.get(name, {}))
            params_raw = profile_raw.get("params", {})
            params = dict(params_raw) if isinstance(params_raw, dict) else {}
            timing_window = AnalysisTimingWindow.from_dict(
                profile_raw.get("holding_window", defaults.get("holding_window"))
            )
            required_inputs_raw = profile_raw.get(
                "required_inputs", defaults.get("required_inputs", [])
            )
            required_inputs = (
                tuple(str(item) for item in required_inputs_raw)
                if isinstance(required_inputs_raw, list)
                else ()
            )
            definitions[name] = AnalysisProfileDefinition(
                name=name,
                enabled=bool(profile_raw.get("enabled", defaults.get("enabled", True))),
                timeout_seconds=float(
                    profile_raw.get("timeout_seconds", defaults.get("timeout_seconds", 0.05))
                ),
                required_inputs=required_inputs,
                skip_gate=_parse_gate(
                    profile_raw.get("skip_gate"),
                    _parse_gate(defaults.get("skip_gate"), AnalysisGate.ALLOW),
                ),
                missing_input_gate=_parse_gate(
                    profile_raw.get("missing_input_gate"),
                    _parse_gate(defaults.get("missing_input_gate"), AnalysisGate.ALLOW),
                ),
                timeout_gate=_parse_gate(
                    profile_raw.get("timeout_gate"),
                    _parse_gate(defaults.get("timeout_gate"), AnalysisGate.REVIEW),
                ),
                error_gate=_parse_gate(
                    profile_raw.get("error_gate"),
                    _parse_gate(defaults.get("error_gate"), AnalysisGate.REVIEW),
                ),
                impact_level=_parse_impact(
                    profile_raw.get("impact_level"),
                    _parse_impact(defaults.get("impact_level"), ImpactLevel.LOW),
                ),
                timing_window=timing_window,
                params=params,
            )

        config = AnalysisChainConfig(
            enabled=bool(raw.get("enabled", True)),
            default_chain=tuple(chain_names),
            profiles=definitions,
            config_path=str(config_path),
        )
        return cls(config=config, registry=loaded_registry)

    # ── Execution ─────────────────────────────────────────────────────────────

    def run_profile(
        self,
        name: str,
        *,
        context: AnalysisProfileContext,
    ) -> AnalysisProfileResult:
        definition = self.config.profiles.get(name)

        if not self.config.enabled:
            return _fallback_result(
                name,
                gate=AnalysisGate.ALLOW,
                impact_level=ImpactLevel.LOW,
                execution_status=AnalysisProfileExecutionStatus.DISABLED,
                reason_codes=["ANALYSIS_PROFILES_DISABLED"],
                summary="Analysis profiles are disabled by configuration.",
                timing_window=definition.timing_window if definition else None,
            )

        if definition is None:
            return _fallback_result(
                name,
                gate=AnalysisGate.REVIEW,
                impact_level=ImpactLevel.MEDIUM,
                execution_status=AnalysisProfileExecutionStatus.ERROR_FALLBACK,
                reason_codes=["UNKNOWN_ANALYSIS_PROFILE"],
                summary="The requested analysis profile is not registered.",
            )

        if not definition.enabled:
            return AnalysisProfileResult(
                profile_name=name,
                decision_gate=definition.skip_gate,
                impact_level=definition.impact_level,
                reasons=("PROFILE_DISABLED",),
                confidence_info={
                    "score": 1.0,
                    "source": f"analysis_profile:{name}",
                    "notes": ["Profile disabled by configuration."],
                },
                execution_status=AnalysisProfileExecutionStatus.DISABLED,
                summary="Profile disabled by configuration.",
                timing_window=definition.timing_window,
            )

        missing_inputs = tuple(
            inp for inp in definition.required_inputs if not context.has_input(inp)
        )
        if missing_inputs:
            return _fallback_result(
                name,
                gate=definition.missing_input_gate,
                impact_level=max(
                    definition.impact_level,
                    ImpactLevel.MEDIUM,
                    key=_impact_rank,
                ),
                execution_status=AnalysisProfileExecutionStatus.MISSING_INPUT_FALLBACK,
                reason_codes=[
                    "PROFILE_MISSING_INPUTS",
                    *[f"MISSING_{inp.upper()}" for inp in missing_inputs],
                ],
                summary="Profile inputs are incomplete; configured fallback applied.",
                missing_inputs=missing_inputs,
                timing_window=definition.timing_window,
            )

        started = self.perf_counter_fn()
        try:
            result = self.registry.evaluate(name, context=context, definition=definition)
        except Exception as exc:
            duration_ms = max(0, int((self.perf_counter_fn() - started) * 1000))
            return _fallback_result(
                name,
                gate=definition.error_gate,
                impact_level=max(
                    definition.impact_level, ImpactLevel.MEDIUM, key=_impact_rank
                ),
                execution_status=AnalysisProfileExecutionStatus.ERROR_FALLBACK,
                reason_codes=["PROFILE_ERROR", type(exc).__name__.upper()],
                summary="Profile execution failed; configured fallback applied.",
                duration_ms=duration_ms,
                error=str(exc),
                timing_window=definition.timing_window,
            )

        duration_ms = max(0, int((self.perf_counter_fn() - started) * 1000))
        if duration_ms > int(definition.timeout_seconds * 1000):
            return _fallback_result(
                name,
                gate=definition.timeout_gate,
                impact_level=max(
                    definition.impact_level, ImpactLevel.MEDIUM, key=_impact_rank
                ),
                execution_status=AnalysisProfileExecutionStatus.TIMEOUT_FALLBACK,
                reason_codes=["PROFILE_TIMEOUT"],
                summary=(
                    "Profile execution exceeded the configured timeout; "
                    "configured fallback applied."
                ),
                duration_ms=duration_ms,
                timing_window=definition.timing_window,
            )

        return AnalysisProfileResult(
            profile_name=result.profile_name,
            decision_gate=result.decision_gate,
            impact_level=result.impact_level,
            reasons=result.reasons,
            confidence_info=dict(result.confidence_info),
            execution_status=AnalysisProfileExecutionStatus.COMPLETED,
            duration_ms=duration_ms,
            used_fallback=result.used_fallback,
            missing_inputs=result.missing_inputs,
            summary=result.summary,
            timing_window=result.timing_window or definition.timing_window,
        )

    def run_chain(
        self,
        *,
        context: AnalysisProfileContext,
        profile_names: list[str] | tuple[str, ...] | None = None,
        chain_name: str = "default",
    ) -> AnalysisChainResult:
        names = tuple(profile_names or self.config.default_chain)
        results = tuple(self.run_profile(name, context=context) for name in names)

        if not results:
            return AnalysisChainResult(
                chain_name=chain_name,
                decision_gate=AnalysisGate.ALLOW,
                impact_level=ImpactLevel.LOW,
                reason_codes=("ANALYSIS_CHAIN_EMPTY",),
                profile_results=(),
                summary="No analysis profiles were configured for this chain.",
            )

        chosen_gate = AnalysisGate.ALLOW
        chosen_impact = ImpactLevel.LOW
        reasons: list[str] = []
        seen: set[str] = set()
        for result in results:
            if _gate_rank(result.decision_gate) > _gate_rank(chosen_gate):
                chosen_gate = result.decision_gate
            if _impact_rank(result.impact_level) > _impact_rank(chosen_impact):
                chosen_impact = result.impact_level
            for reason in result.reasons:
                if reason not in seen:
                    seen.add(reason)
                    reasons.append(reason)

        skipped = sum(
            1
            for r in results
            if r.execution_status
            in {
                AnalysisProfileExecutionStatus.SKIPPED,
                AnalysisProfileExecutionStatus.DISABLED,
            }
        )
        fallbacks = sum(1 for r in results if r.used_fallback)
        timed_out = sum(
            1
            for r in results
            if r.execution_status == AnalysisProfileExecutionStatus.TIMEOUT_FALLBACK
        )
        return AnalysisChainResult(
            chain_name=chain_name,
            decision_gate=chosen_gate,
            impact_level=chosen_impact,
            reason_codes=tuple(reasons),
            profile_results=results,
            skipped_profiles=skipped,
            fallback_profiles=fallbacks,
            timed_out_profiles=timed_out,
            summary=(
                f"Analysis chain '{chain_name}' completed with gate "
                f"{chosen_gate.value} across {len(results)} profile(s)."
            ),
            timing_window=_merge_timing_windows(results),
        )

    def run_default_chain(
        self, *, context: AnalysisProfileContext
    ) -> AnalysisChainResult:
        return self.run_chain(
            context=context,
            profile_names=self.config.default_chain,
            chain_name="default",
        )


__all__ = ["ProfileRunner"]
