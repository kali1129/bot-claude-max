"""Deterministic strategy modules.

Ported from xm-mt5-trading-platform/src/strategies/. Each strategy takes a
FeatureSnapshot (built by `feature_pipeline.build_snapshot` from raw OHLCV)
and returns a StrategyDecision with a normalized direction (LONG/SHORT/FLAT),
machine-readable rationale codes, and a 0..1 confidence score.

The pipeline + strategies are designed to be **pure**: same input → same
output. No state, no clocks, no IO.

Public registry:
    `STRATEGIES`: dict mapping name → strategy class
    `evaluate(name, snapshot, config=None)` convenience entrypoint
"""
from __future__ import annotations

from typing import Mapping

from .base import (
    BaseStrategy,
    FeatureSnapshot,
    StrategyDecision,
    StrategyDirection,
)
from .ema_rsi_trend import EMARSITrendStrategy, EMARSITrendConfig
from .breakout_volatility import BreakoutVolatilityStrategy, BreakoutVolatilityConfig


STRATEGIES: dict[str, type[BaseStrategy]] = {
    EMARSITrendStrategy.name: EMARSITrendStrategy,
    BreakoutVolatilityStrategy.name: BreakoutVolatilityStrategy,
}


def list_strategies() -> list[str]:
    """Return the names of all registered strategies."""
    return sorted(STRATEGIES.keys())


def evaluate(
    name: str,
    snapshot: FeatureSnapshot,
    config: Mapping[str, object] | None = None,
) -> StrategyDecision:
    """Evaluate a snapshot against a named strategy."""
    if name not in STRATEGIES:
        raise KeyError(f"Unknown strategy: {name}. Available: {list_strategies()}")
    strategy_cls = STRATEGIES[name]
    return strategy_cls.from_mapping(config).evaluate(snapshot)


__all__ = [
    "BaseStrategy",
    "FeatureSnapshot",
    "StrategyDecision",
    "StrategyDirection",
    "EMARSITrendStrategy",
    "EMARSITrendConfig",
    "BreakoutVolatilityStrategy",
    "BreakoutVolatilityConfig",
    "STRATEGIES",
    "list_strategies",
    "evaluate",
]
