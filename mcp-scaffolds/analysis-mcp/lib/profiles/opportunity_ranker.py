"""Deterministic bounded multi-symbol opportunity ranking.

Port of xm-mt5-trading-platform/src/analysis/opportunity_ranker.py.

Dependencies on DISCARD modules eliminated:
  - analysis.agent_consensus   → OpportunityDirective and OpportunityRankerResult
                                  defined locally; confidence_band inlined.
  - analysis.live_context_fusion → _fuse() inlined (same logic, no external dep).
  - settings.models.OpportunitySettings → RankerSettings defined locally.
  - monitoring.telegram_operator_output → simple_guidance() replaces the old
                                           helper with no external dep.

All scoring and directive logic is preserved without modification.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable

# ── _shared path bootstrap ────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SHARED_PARENT = _HERE.parent.parent.parent  # profiles/ → lib/ → analysis-mcp/ → mcp-scaffolds/
if str(_SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(_SHARED_PARENT))

from _shared.common.enums import GateState  # noqa: E402


# ── Local enums (replaces agent_consensus.OpportunityDirective) ───────────────

class OpportunityDirective(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    REDUCE_RISK = "REDUCE_RISK"
    REVIEW = "REVIEW"
    HOLD_OFF = "HOLD_OFF"


class ConfidenceBand(str, Enum):
    VERY_LOW = "VERY_LOW"    # score < 0.35
    LOW = "LOW"              # 0.35 ≤ score < 0.50
    MODERATE = "MODERATE"   # 0.50 ≤ score < 0.65
    HIGH = "HIGH"            # 0.65 ≤ score < 0.80
    VERY_HIGH = "VERY_HIGH"  # score ≥ 0.80


def _confidence_band(score: float) -> ConfidenceBand:
    if score >= 0.80:
        return ConfidenceBand.VERY_HIGH
    if score >= 0.65:
        return ConfidenceBand.HIGH
    if score >= 0.50:
        return ConfidenceBand.MODERATE
    if score >= 0.35:
        return ConfidenceBand.LOW
    return ConfidenceBand.VERY_LOW


# ── Settings (replaces settings.models.OpportunitySettings) ──────────────────

@dataclass(frozen=True, slots=True)
class RankerSettings:
    """Scoring weights and thresholds for OpportunityRanker.

    Mirrors xm-mt5-trading-platform/src/settings/models.py:OpportunitySettings.
    Defaults taken from the legacy bot's live.yaml configuration.
    All risk-limit constants come from _shared/rules.py — never duplicated here.
    """

    min_opportunity_score: float = 0.52
    min_signal_strength: float = 0.15

    # Quality weights (must sum ≈ 1.0 to keep score in [0, 1])
    trend_weight: float = 0.22
    volatility_weight: float = 0.10
    session_weight: float = 0.12
    news_context_weight: float = 0.18
    risk_context_weight: float = 0.14
    execution_health_weight: float = 0.10
    # symbol_health + recent_outcome_quality add 0.08 + 0.06 = 0.14 inline

    # Penalties
    spread_penalty_weight: float = 0.15
    context_weak_penalty: float = 0.08
    execution_health_penalty: float = 0.10
    reconciliation_penalty: float = 0.12
    open_position_focus_bias: float = 0.05

    @classmethod
    def default(cls) -> "RankerSettings":
        return cls()


# ── Fused context (replaces live_context_fusion.FusedOpportunityContext) ──────

@dataclass(frozen=True, slots=True)
class _Fused:
    """Internal quality surface computed from OpportunityInput."""

    trend_quality: float
    volatility_quality: float
    session_quality: float
    news_context_quality: float
    risk_context_quality: float
    execution_feasibility: float
    spread_penalty: float
    symbol_health: float
    recent_outcome_quality: float
    entry_candidate: bool
    reason_codes: tuple[str, ...]


# ── Input ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class OpportunityInput:
    """Everything the ranker needs for one symbol+timeframe slot."""

    symbol: str
    timeframe: str
    signal_action: str           # "buy" / "sell" / "hold"
    signal_strength: float       # 0..1
    gate_state: str              # GateState value
    gate_reason: str
    risk_disposition: str        # "allow" / "reduce_risk" / "block"
    risk_approved: bool
    risk_reason_codes: tuple[str, ...]
    spread_points: float
    spread_block_threshold: float
    spread_reduce_threshold: float
    session_allowed: bool
    session_reason: str
    quote_age_seconds: float | None
    terminal_connected: bool | None
    trade_allowed: bool | None
    bridge_stale: bool
    reconciliation_mismatch_count: int
    reconciliation_pending_count: int
    daily_stop_active: bool
    symbol_allowed_today: bool
    open_positions_on_symbol: int
    recent_closed_trades: int
    recent_win_rate: float | None
    recent_realized_pnl: float | None
    news_context_state: str
    source_state_counts: dict[str, int] = field(default_factory=dict)
    bar_timestamp: str = ""
    state_timestamp: str = ""
    entry_bar_is_new: bool = False
    setup_score: float = 0.0
    consecutive_symbol_losses: int = 0


# ── Result (replaces agent_consensus.OpportunityAssessment) ──────────────────

@dataclass(frozen=True, slots=True)
class OpportunityRankerResult:
    """Structured output for one symbol opportunity assessment."""

    symbol: str
    timeframe: str
    opportunity_score: float
    confidence_band: ConfidenceBand
    directive: OpportunityDirective
    signal_action: str
    signal_strength: float
    spread_penalty: float
    execution_feasibility: float
    news_context_quality: float
    risk_context_quality: float
    session_quality: float
    trend_quality: float
    volatility_quality: float
    symbol_health: float
    recent_outcome_quality: float
    entry_bar_is_new: bool
    entry_candidate: bool
    gate_state: str
    risk_disposition: str
    bar_timestamp: str
    state_timestamp: str
    reason_codes: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "opportunity_score": round(self.opportunity_score, 4),
            "confidence_band": self.confidence_band.value,
            "directive": self.directive.value,
            "signal_action": self.signal_action,
            "signal_strength": self.signal_strength,
            "spread_penalty": round(self.spread_penalty, 4),
            "execution_feasibility": round(self.execution_feasibility, 4),
            "news_context_quality": round(self.news_context_quality, 4),
            "risk_context_quality": round(self.risk_context_quality, 4),
            "session_quality": round(self.session_quality, 4),
            "trend_quality": round(self.trend_quality, 4),
            "volatility_quality": round(self.volatility_quality, 4),
            "symbol_health": round(self.symbol_health, 4),
            "recent_outcome_quality": round(self.recent_outcome_quality, 4),
            "entry_bar_is_new": self.entry_bar_is_new,
            "entry_candidate": self.entry_candidate,
            "gate_state": self.gate_state,
            "risk_disposition": self.risk_disposition,
            "bar_timestamp": self.bar_timestamp,
            "state_timestamp": self.state_timestamp,
            "reason_codes": list(self.reason_codes),
        }


# ── Internal fusion helpers (replaces live_context_fusion) ────────────────────

def _fuse(item: OpportunityInput) -> _Fused:
    """Compute quality scores from a raw OpportunityInput. Pure function."""
    reason_codes: list[str] = []

    # --- Trend / volatility ---
    strength = max(0.0, min(abs(float(item.signal_strength)), 1.0))
    action_norm = str(item.signal_action).strip().lower()
    if action_norm == "hold":
        trend_quality = 0.0
        volatility_quality = 0.2
        reason_codes.append("NO_SIGNAL")
    elif strength < 0.15:
        trend_quality = strength * 0.5
        volatility_quality = 0.3
        reason_codes.append("LOW_CONVICTION")
    else:
        trend_quality = strength
        volatility_quality = 0.45 + min(strength, 0.45)

    # --- Session ---
    session_quality = 1.0 if item.session_allowed else 0.0
    if not item.session_allowed:
        reason_codes.append("SESSION_BLOCKED")

    # --- News / gate ---
    gate_norm = str(item.gate_state).strip().lower()
    news_state_norm = str(item.news_context_state or "").strip().upper()
    if gate_norm == GateState.BLOCK_NEW_ENTRIES.value:
        news_context_quality = 0.0
        reason_codes.append("NEWS_GATE_BLOCKED")
    elif gate_norm == GateState.REVIEW_REQUIRED.value:
        news_context_quality = 0.2
        reason_codes.append("NEWS_GATE_REVIEW")
    elif news_state_norm in {"UNAVAILABLE", "STALE_SOURCE", "SOURCE_NOT_POPULATED"}:
        news_context_quality = 0.35
        reason_codes.append("WEAK_LIVE_CONTEXT")
    elif news_state_norm == "EMPTY_HEALTHY":
        news_context_quality = 0.5
        reason_codes.append("EMPTY_NEWS_FALLBACK")
    elif gate_norm == GateState.REDUCE_SIZE.value:
        news_context_quality = 0.55
        reason_codes.append("REDUCE_RISK_CONTEXT")
    else:
        news_context_quality = 0.9

    # --- Risk ---
    risk_norm = str(item.risk_disposition).strip().lower()
    if item.daily_stop_active:
        risk_context_quality = 0.0
    elif item.risk_approved:
        risk_context_quality = 0.9 if risk_norm == "allow" else 0.7
    elif risk_norm == "reduce_risk":
        risk_context_quality = 0.55
        reason_codes.extend(item.risk_reason_codes)
    else:
        risk_context_quality = 0.15
        reason_codes.extend(item.risk_reason_codes)

    # --- Execution feasibility ---
    execution_feasibility = 1.0
    if item.terminal_connected is False:
        reason_codes.append("MT5_DISCONNECTED")
        execution_feasibility = 0.0
    elif item.trade_allowed is False:
        reason_codes.append("TRADE_NOT_ALLOWED")
        execution_feasibility = 0.0
    elif item.bridge_stale:
        reason_codes.append("STALE_BRIDGE_MESSAGES")
        execution_feasibility = 0.0
    else:
        if item.reconciliation_mismatch_count > 0:
            reason_codes.append("RECONCILIATION_MISMATCH_PRESENT")
            execution_feasibility -= 0.4
        if item.reconciliation_pending_count > 0:
            reason_codes.append("RECONCILIATION_PENDING")
            execution_feasibility -= 0.15
        if item.quote_age_seconds is not None and item.quote_age_seconds > 20:
            reason_codes.append("QUOTE_STALE")
            execution_feasibility -= 0.2
        execution_feasibility = max(execution_feasibility, 0.0)

    # --- Spread penalty ---
    if item.spread_block_threshold <= 0:
        spread_penalty = 0.0
    else:
        spread = float(item.spread_points)
        block = float(item.spread_block_threshold)
        reduce = min(float(item.spread_reduce_threshold), block)
        if spread >= block:
            reason_codes.append("MARKET_SPREAD_ELEVATED")
            spread_penalty = 1.0
        elif spread >= reduce:
            reason_codes.append("SPREAD_REDUCE_THRESHOLD_EXCEEDED")
            spread_penalty = min(
                0.8, max((spread - reduce) / max(block - reduce, 1.0), 0.35)
            )
        else:
            spread_penalty = max(0.0, spread / max(block, 1.0) * 0.25)

    # --- Symbol health ---
    symbol_health = 1.0
    if item.open_positions_on_symbol > 0:
        symbol_health -= 0.15
    if not item.symbol_allowed_today:
        symbol_health -= 0.75
    if item.quote_age_seconds is not None and item.quote_age_seconds > 30:
        symbol_health -= 0.2
    if news_state_norm in {"UNAVAILABLE", "STALE_SOURCE"}:
        symbol_health -= 0.15
    symbol_health = max(symbol_health, 0.0)
    if symbol_health < 0.4:
        reason_codes.append("SYMBOL_HEALTH_WEAK")

    # --- Recent outcome quality ---
    if item.recent_closed_trades <= 0 or item.recent_win_rate is None:
        recent_outcome_quality = 0.5
    else:
        pnl = item.recent_realized_pnl or 0.0
        pnl_bias = 0.1 if pnl > 0 else (-0.1 if pnl < 0 else 0.0)
        recent_outcome_quality = max(
            0.0, min(1.0, float(item.recent_win_rate) * 0.8 + 0.1 + pnl_bias)
        )

    # --- Entry candidate ---
    entry_candidate = (
        action_norm != "hold"
        and item.symbol_allowed_today
        and not item.daily_stop_active
        and gate_norm
        not in {GateState.BLOCK_NEW_ENTRIES.value, GateState.REVIEW_REQUIRED.value}
    )
    if not item.symbol_allowed_today:
        reason_codes.append("SYMBOL_NOT_ALLOWED_TODAY")
    if item.daily_stop_active:
        reason_codes.append("DAILY_STOP_ACTIVE")

    return _Fused(
        trend_quality=max(0.0, min(trend_quality, 1.0)),
        volatility_quality=max(0.0, min(volatility_quality, 1.0)),
        session_quality=max(0.0, min(session_quality, 1.0)),
        news_context_quality=max(0.0, min(news_context_quality, 1.0)),
        risk_context_quality=max(0.0, min(risk_context_quality, 1.0)),
        execution_feasibility=max(0.0, min(execution_feasibility, 1.0)),
        spread_penalty=max(0.0, min(spread_penalty, 1.0)),
        symbol_health=max(0.0, min(symbol_health, 1.0)),
        recent_outcome_quality=max(0.0, min(recent_outcome_quality, 1.0)),
        entry_candidate=entry_candidate,
        reason_codes=tuple(dict.fromkeys(reason_codes)),  # dedup, preserve order
    )


# ── Ranker ────────────────────────────────────────────────────────────────────

class OpportunityRanker:
    """Builds bounded opportunity assessments and returns ranked symbols."""

    def __init__(self, settings: RankerSettings | None = None) -> None:
        self.settings = settings or RankerSettings.default()

    def assess(self, item: OpportunityInput) -> OpportunityRankerResult:
        fused = _fuse(item)
        score = self._score(item, fused)
        directive = self._directive(item=item, fused=fused, score=score)
        entry_candidate = fused.entry_candidate and score >= self.settings.min_opportunity_score
        return OpportunityRankerResult(
            symbol=item.symbol,
            timeframe=item.timeframe,
            opportunity_score=score,
            confidence_band=_confidence_band(score),
            directive=directive,
            signal_action=str(item.signal_action).upper(),
            signal_strength=item.signal_strength,
            spread_penalty=fused.spread_penalty,
            execution_feasibility=fused.execution_feasibility,
            news_context_quality=fused.news_context_quality,
            risk_context_quality=fused.risk_context_quality,
            session_quality=fused.session_quality,
            trend_quality=fused.trend_quality,
            volatility_quality=fused.volatility_quality,
            symbol_health=fused.symbol_health,
            recent_outcome_quality=fused.recent_outcome_quality,
            entry_bar_is_new=item.entry_bar_is_new,
            entry_candidate=entry_candidate,
            gate_state=item.gate_state,
            risk_disposition=item.risk_disposition,
            bar_timestamp=item.bar_timestamp,
            state_timestamp=item.state_timestamp,
            reason_codes=fused.reason_codes,
        )

    def rank(
        self, items: Iterable[OpportunityInput]
    ) -> list[OpportunityRankerResult]:
        assessments = [self.assess(item) for item in items]
        return sorted(
            assessments,
            key=lambda r: (
                r.entry_candidate,
                r.opportunity_score,
                r.execution_feasibility,
                r.trend_quality,
            ),
            reverse=True,
        )

    # ── Internal scoring ──────────────────────────────────────────────────────

    def _score(self, item: OpportunityInput, fused: _Fused) -> float:
        s = self.settings
        weighted_quality = (
            fused.trend_quality * s.trend_weight
            + fused.volatility_quality * s.volatility_weight
            + fused.session_quality * s.session_weight
            + fused.news_context_quality * s.news_context_weight
            + fused.risk_context_quality * s.risk_context_weight
            + fused.execution_feasibility * s.execution_health_weight
            + fused.symbol_health * 0.08
            + fused.recent_outcome_quality * 0.06
        )
        penalty = fused.spread_penalty * s.spread_penalty_weight
        if fused.news_context_quality < 0.5:
            penalty += s.context_weak_penalty
        if fused.execution_feasibility < 0.6:
            penalty += s.execution_health_penalty
        if item.reconciliation_mismatch_count > 0:
            penalty += s.reconciliation_penalty
        if item.open_positions_on_symbol > 0:
            weighted_quality += s.open_position_focus_bias
        if abs(float(item.signal_strength)) < float(s.min_signal_strength):
            penalty += 0.40
        # Setup history: bad setups penalised, good setups get a small bonus
        setup = max(-0.20, min(0.10, float(item.setup_score)))
        if setup < 0:
            penalty += abs(setup)
        else:
            weighted_quality += setup
        return max(0.0, min(1.0, weighted_quality - penalty))

    def _directive(
        self,
        *,
        item: OpportunityInput,
        fused: _Fused,
        score: float,
    ) -> OpportunityDirective:
        if item.daily_stop_active or not item.symbol_allowed_today:
            return OpportunityDirective.HOLD_OFF
        if int(item.consecutive_symbol_losses) >= 4:
            return OpportunityDirective.HOLD_OFF
        if abs(float(item.signal_strength)) < float(self.settings.min_signal_strength):
            return OpportunityDirective.HOLD_OFF
        if item.spread_points >= item.spread_block_threshold > 0:
            return OpportunityDirective.HOLD_OFF

        gate_norm = str(item.gate_state).strip().lower()
        risk_norm = str(item.risk_disposition).strip().lower()

        if gate_norm == GateState.BLOCK_NEW_ENTRIES.value or risk_norm == "block":
            return OpportunityDirective.BLOCK
        if gate_norm == GateState.REVIEW_REQUIRED.value:
            return OpportunityDirective.REVIEW
        if gate_norm == GateState.REDUCE_SIZE.value or risk_norm == "reduce_risk":
            return OpportunityDirective.REDUCE_RISK
        if not fused.entry_candidate or score < self.settings.min_opportunity_score:
            return OpportunityDirective.HOLD_OFF
        return OpportunityDirective.ALLOW


__all__ = [
    "ConfidenceBand",
    "OpportunityDirective",
    "OpportunityInput",
    "OpportunityRanker",
    "OpportunityRankerResult",
    "RankerSettings",
]
