"""Tests for lib/profiles — Layer 5 legacy port.

Coverage:
  models      — AnalysisProfileContext, AnalysisTimingWindow, AnalysisChainResult
  registry    — ProfileRegistry default evaluators
  runner      — ProfileRunner.disabled(), run_profile(), run_chain(), from_yaml()
  ranker      — OpportunityRanker.assess(), rank(), edge-cases
"""

from __future__ import annotations

import pytest
from datetime import datetime, timezone

# conftest.py already adds the analysis-mcp root to sys.path
from lib.profiles.models import (
    AnalysisGate,
    AnalysisProfileContext,
    AnalysisProfileDefinition,
    AnalysisProfileExecutionStatus,
    AnalysisTimingWindow,
)
from lib.profiles.registry import ProfileRegistry
from lib.profiles.runner import ProfileRunner
from lib.profiles.opportunity_ranker import (
    ConfidenceBand,
    OpportunityDirective,
    OpportunityInput,
    OpportunityRanker,
    RankerSettings,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

NOW = datetime(2025, 4, 28, 10, 0, 0, tzinfo=timezone.utc)


def _ctx(**kwargs) -> AnalysisProfileContext:
    defaults = {"symbol": "EURUSD", "timestamp": NOW}
    defaults.update(kwargs)
    return AnalysisProfileContext(**defaults)


def _opportunity(**kwargs) -> OpportunityInput:
    base = dict(
        symbol="EURUSD",
        timeframe="M15",
        signal_action="buy",
        signal_strength=0.75,
        gate_state="allow",
        gate_reason="all clear",
        risk_disposition="allow",
        risk_approved=True,
        risk_reason_codes=(),
        spread_points=1.5,
        spread_block_threshold=80.0,
        spread_reduce_threshold=25.0,
        session_allowed=True,
        session_reason="london session",
        quote_age_seconds=2.0,
        terminal_connected=True,
        trade_allowed=True,
        bridge_stale=False,
        reconciliation_mismatch_count=0,
        reconciliation_pending_count=0,
        daily_stop_active=False,
        symbol_allowed_today=True,
        open_positions_on_symbol=0,
        recent_closed_trades=5,
        recent_win_rate=0.6,
        recent_realized_pnl=12.0,
        news_context_state="ACTIVE_HEALTHY",
        entry_bar_is_new=True,
    )
    base.update(kwargs)
    return OpportunityInput(**base)


# ── AnalysisTimingWindow ──────────────────────────────────────────────────────

def test_timing_window_roundtrip():
    tw = AnalysisTimingWindow(
        min_holding_minutes=5,
        max_holding_minutes=60,
        preferred_holding_window_minutes=30,
        time_based_exit_enabled=True,
    )
    d = tw.to_dict()
    assert d["min_holding_minutes"] == 5
    assert d["time_based_exit_enabled"] is True

    tw2 = AnalysisTimingWindow.from_dict(d)
    assert tw2 == tw


def test_timing_window_from_none():
    assert AnalysisTimingWindow.from_dict(None) is None


# ── AnalysisProfileContext ────────────────────────────────────────────────────

def test_context_has_input_present():
    ctx = _ctx(market_data={"spread_points": 2.0})
    assert ctx.has_input("market_data") is True
    assert ctx.has_input("operational_state") is False


def test_context_timestamp_utc():
    naive = datetime(2025, 4, 28, 10, 0, 0)
    ctx = _ctx(timestamp=naive)
    assert ctx.timestamp.tzinfo is not None


def test_context_to_dict():
    ctx = _ctx(anomaly_signals=("BRIDGE_STALE",))
    d = ctx.to_dict()
    assert d["symbol"] == "EURUSD"
    assert d["anomaly_signals"] == ["BRIDGE_STALE"]


# ── ProfileRegistry ───────────────────────────────────────────────────────────

def test_registry_has_default_evaluators():
    reg = ProfileRegistry()
    names = reg.names()
    for expected in (
        "market_watch", "news_scan", "macro_window", "anomaly_check",
        "log_review", "pretrade_context", "spread_watch",
        "reconcile_watch", "risk_review", "session_watch",
    ):
        assert expected in names


def test_registry_evaluate_unknown_raises():
    reg = ProfileRegistry()
    defn = AnalysisProfileDefinition(name="ghost")
    with pytest.raises(KeyError):
        reg.evaluate("ghost", context=_ctx(), definition=defn)


def test_registry_market_watch_allow():
    reg = ProfileRegistry()
    defn = AnalysisProfileDefinition(
        name="market_watch",
        params={"block_quote_age_seconds": 120.0, "reduce_spread_points": 25.0, "block_spread_points": 80.0},
    )
    ctx = _ctx(market_data={"spread_points": 2.0, "quote_age_seconds": 1.0, "terminal_connected": True})
    result = reg.evaluate("market_watch", context=ctx, definition=defn)
    assert result.decision_gate == AnalysisGate.ALLOW


def test_registry_market_watch_block_spread():
    reg = ProfileRegistry()
    defn = AnalysisProfileDefinition(
        name="market_watch",
        params={"reduce_spread_points": 25.0, "block_spread_points": 80.0},
    )
    ctx = _ctx(market_data={"spread_points": 85.0, "quote_age_seconds": 0.5, "terminal_connected": True})
    result = reg.evaluate("market_watch", context=ctx, definition=defn)
    assert result.decision_gate == AnalysisGate.BLOCK


def test_registry_macro_window_high_impact():
    reg = ProfileRegistry()
    defn = AnalysisProfileDefinition(name="macro_window")
    ctx = _ctx(active_events=({"impact_level": "high", "name": "NFP"},))
    result = reg.evaluate("macro_window", context=ctx, definition=defn)
    assert result.decision_gate == AnalysisGate.BLOCK
    assert "EVENT_WINDOW_HIGH_IMPACT" in result.reasons


def test_registry_anomaly_check_block():
    reg = ProfileRegistry()
    defn = AnalysisProfileDefinition(name="anomaly_check")
    ctx = _ctx(anomaly_signals=("MT5_DISCONNECTED",))
    result = reg.evaluate("anomaly_check", context=ctx, definition=defn)
    assert result.decision_gate == AnalysisGate.BLOCK


def test_registry_session_watch_block():
    reg = ProfileRegistry()
    defn = AnalysisProfileDefinition(name="session_watch")
    ctx = _ctx(operational_state={"session_allowed": False, "session_reason": "weekend"})
    result = reg.evaluate("session_watch", context=ctx, definition=defn)
    assert result.decision_gate == AnalysisGate.BLOCK


# ── ProfileRunner — disabled mode ─────────────────────────────────────────────

def test_runner_disabled_returns_allow():
    runner = ProfileRunner.disabled()
    result = runner.run_profile("market_watch", context=_ctx())
    assert result.decision_gate == AnalysisGate.ALLOW
    assert result.execution_status == AnalysisProfileExecutionStatus.DISABLED


def test_runner_disabled_chain_returns_allow():
    runner = ProfileRunner.disabled()
    chain = runner.run_default_chain(context=_ctx())
    assert chain.decision_gate == AnalysisGate.ALLOW


# ── ProfileRunner — run_profile ───────────────────────────────────────────────

def _make_runner(chain=("market_watch", "news_scan")) -> ProfileRunner:
    from lib.profiles.models import AnalysisChainConfig
    definitions = {
        name: AnalysisProfileDefinition(name=name) for name in chain
    }
    config = AnalysisChainConfig(
        enabled=True,
        default_chain=tuple(chain),
        profiles=definitions,
    )
    return ProfileRunner(config=config)


def test_runner_run_profile_happy_path():
    runner = _make_runner()
    ctx = _ctx(
        market_data={"spread_points": 2.0, "quote_age_seconds": 1.0, "terminal_connected": True},
        collected_headlines=({"title": "EUR up"},),
        relevant_headlines=({"title": "EUR up"},),
    )
    result = runner.run_profile("market_watch", context=ctx)
    assert result.profile_name == "market_watch"
    assert result.decision_gate == AnalysisGate.ALLOW
    assert result.execution_status == AnalysisProfileExecutionStatus.COMPLETED


def test_runner_run_profile_unknown():
    runner = _make_runner()
    result = runner.run_profile("nonexistent_profile", context=_ctx())
    assert result.execution_status == AnalysisProfileExecutionStatus.ERROR_FALLBACK
    assert result.decision_gate == AnalysisGate.REVIEW


def test_runner_missing_required_input():
    """Profile requiring market_data but context has none → MISSING_INPUT_FALLBACK."""
    from lib.profiles.models import AnalysisChainConfig

    defn = AnalysisProfileDefinition(
        name="market_watch",
        required_inputs=("market_data",),
        missing_input_gate=AnalysisGate.REVIEW,
    )
    config = AnalysisChainConfig(
        enabled=True,
        default_chain=("market_watch",),
        profiles={"market_watch": defn},
    )
    runner = ProfileRunner(config=config)
    result = runner.run_profile("market_watch", context=_ctx())  # no market_data
    assert result.execution_status == AnalysisProfileExecutionStatus.MISSING_INPUT_FALLBACK
    assert result.decision_gate == AnalysisGate.REVIEW
    assert "market_data" in result.missing_inputs


def test_runner_run_chain_aggregates_worst_gate():
    runner = _make_runner(chain=("macro_window", "news_scan"))
    ctx = _ctx(
        active_events=({"impact_level": "high"},),
        collected_headlines=({"title": "ok"},),
        relevant_headlines=({"title": "ok"},),
    )
    chain = runner.run_chain(context=ctx)
    # macro_window → BLOCK wins over news_scan → ALLOW
    assert chain.decision_gate == AnalysisGate.BLOCK


def test_runner_chain_empty():
    from lib.profiles.models import AnalysisChainConfig
    config = AnalysisChainConfig(enabled=True, default_chain=(), profiles={})
    runner = ProfileRunner(config=config)
    chain = runner.run_default_chain(context=_ctx())
    assert chain.decision_gate == AnalysisGate.ALLOW
    assert "ANALYSIS_CHAIN_EMPTY" in chain.reason_codes


def test_runner_from_yaml_missing_path():
    runner = ProfileRunner.from_yaml("/nonexistent/path.yaml")
    assert not runner.config.enabled


# ── OpportunityRanker ─────────────────────────────────────────────────────────

def test_ranker_assess_allow():
    ranker = OpportunityRanker()
    item = _opportunity()
    result = ranker.assess(item)
    assert result.directive == OpportunityDirective.ALLOW
    assert result.entry_candidate is True
    assert result.opportunity_score > 0


def test_ranker_assess_daily_stop():
    """daily_stop_active → HOLD_OFF regardless of everything else."""
    ranker = OpportunityRanker()
    item = _opportunity(daily_stop_active=True)
    result = ranker.assess(item)
    assert result.directive == OpportunityDirective.HOLD_OFF
    assert result.entry_candidate is False
    assert "DAILY_STOP_ACTIVE" in result.reason_codes


def test_ranker_assess_symbol_blocked_today():
    ranker = OpportunityRanker()
    item = _opportunity(symbol_allowed_today=False)
    result = ranker.assess(item)
    assert result.directive == OpportunityDirective.HOLD_OFF


def test_ranker_assess_weak_signal():
    ranker = OpportunityRanker()
    item = _opportunity(signal_strength=0.05)
    result = ranker.assess(item)
    assert result.directive == OpportunityDirective.HOLD_OFF


def test_ranker_assess_spread_block():
    ranker = OpportunityRanker()
    item = _opportunity(spread_points=90.0, spread_block_threshold=80.0)
    result = ranker.assess(item)
    assert result.directive == OpportunityDirective.HOLD_OFF


def test_ranker_assess_gate_block():
    ranker = OpportunityRanker()
    item = _opportunity(gate_state="block_new_entries")
    result = ranker.assess(item)
    assert result.directive == OpportunityDirective.BLOCK


def test_ranker_assess_gate_reduce_risk():
    ranker = OpportunityRanker()
    item = _opportunity(gate_state="reduce_size")
    result = ranker.assess(item)
    assert result.directive == OpportunityDirective.REDUCE_RISK


def test_ranker_assess_terminal_disconnected():
    ranker = OpportunityRanker()
    item = _opportunity(terminal_connected=False)
    result = ranker.assess(item)
    assert result.execution_feasibility == 0.0
    assert "MT5_DISCONNECTED" in result.reason_codes


def test_ranker_assess_consecutive_losses():
    """4+ consecutive losses on symbol → HOLD_OFF."""
    ranker = OpportunityRanker()
    item = _opportunity(consecutive_symbol_losses=4)
    result = ranker.assess(item)
    assert result.directive == OpportunityDirective.HOLD_OFF


def test_ranker_rank_orders_best_first():
    ranker = OpportunityRanker()
    strong = _opportunity(symbol="EURUSD", signal_strength=0.9)
    weak = _opportunity(symbol="GBPUSD", signal_strength=0.2)
    blocked = _opportunity(symbol="USDJPY", gate_state="block_new_entries")
    ranked = ranker.rank([weak, blocked, strong])
    assert ranked[0].symbol == "EURUSD"
    assert ranked[-1].symbol == "USDJPY"


def test_ranker_confidence_band():
    ranker = OpportunityRanker()
    high_item = _opportunity(signal_strength=0.95, recent_win_rate=0.8)
    result = ranker.assess(high_item)
    assert result.confidence_band in (ConfidenceBand.HIGH, ConfidenceBand.VERY_HIGH)


def test_ranker_custom_settings():
    settings = RankerSettings(min_opportunity_score=0.99)  # almost impossible to reach
    ranker = OpportunityRanker(settings=settings)
    item = _opportunity()
    result = ranker.assess(item)
    # Score won't reach 0.99, so entry_candidate should be False
    assert result.entry_candidate is False


def test_opportunity_result_to_dict():
    ranker = OpportunityRanker()
    result = ranker.assess(_opportunity())
    d = result.to_dict()
    assert d["symbol"] == "EURUSD"
    assert "opportunity_score" in d
    assert "directive" in d
    assert isinstance(d["reason_codes"], list)
