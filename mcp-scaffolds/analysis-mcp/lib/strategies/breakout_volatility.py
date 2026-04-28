"""Breakout strategy with consolidation and volatility confirmation.

Port of xm-mt5-trading-platform/src/strategies/breakout_volatility.py.
Logic unchanged; legacy `common.models` import replaced with the local
FeatureSnapshot from `.base`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .base import BaseStrategy, FeatureSnapshot, StrategyDecision


@dataclass(frozen=True, slots=True)
class BreakoutVolatilityConfig:
    """Configuration for the breakout-volatility strategy."""

    allowed_sessions: tuple[str, ...] = ("LONDON", "NEW_YORK")
    max_spread_points: float = 25.0
    max_spread_zscore: float = 2.5
    max_consolidation_atr_ratio: float = 3.0
    min_breakout_position_long: float = 0.9
    max_breakout_position_short: float = 0.1
    min_rolling_volatility: float = 0.00008
    min_atr_pct: float = 0.00015
    min_candle_body_fraction: float = 0.55

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None = None) -> "BreakoutVolatilityConfig":
        payload = dict(data or {})
        allowed_sessions_raw = payload.get("allowed_sessions", ("LONDON", "NEW_YORK"))
        if isinstance(allowed_sessions_raw, (list, tuple)):
            allowed_sessions = tuple(str(value).upper() for value in allowed_sessions_raw)
        else:
            allowed_sessions = ("LONDON", "NEW_YORK")
        return cls(
            allowed_sessions=allowed_sessions,
            max_spread_points=float(payload.get("max_spread_points", 25.0)),
            max_spread_zscore=float(payload.get("max_spread_zscore", 2.5)),
            max_consolidation_atr_ratio=float(payload.get("max_consolidation_atr_ratio", 3.0)),
            min_breakout_position_long=float(payload.get("min_breakout_position_long", 0.9)),
            max_breakout_position_short=float(payload.get("max_breakout_position_short", 0.1)),
            min_rolling_volatility=float(payload.get("min_rolling_volatility", 0.00008)),
            min_atr_pct=float(payload.get("min_atr_pct", 0.00015)),
            min_candle_body_fraction=float(payload.get("min_candle_body_fraction", 0.55)),
        )


class BreakoutVolatilityStrategy(BaseStrategy):
    """Deterministic breakout strategy for controlled regime changes."""

    name = "breakout_volatility"

    def __init__(self, config: BreakoutVolatilityConfig | None = None) -> None:
        self.config = config or BreakoutVolatilityConfig()

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None = None) -> "BreakoutVolatilityStrategy":
        return cls(BreakoutVolatilityConfig.from_mapping(data))

    def evaluate(self, snapshot: FeatureSnapshot) -> StrategyDecision:
        if not snapshot.is_fresh:
            return self.flat(
                "SNAPSHOT_INVALID",
                confidence_info={"session": self.session_label(snapshot), "score": 0.0},
            )

        required = (
            "breakout_range",
            "breakout_position",
            "rolling_volatility",
            "atr",
            "atr_pct",
            "spread_points",
            "spread_zscore",
            "candle_body",
            "candle_body_fraction",
            "candle_close_location",
            "return_1",
        )
        valid, missing_codes = self.require_features(snapshot, required)
        if not valid:
            return self.flat(
                "FEATURES_INVALID",
                *missing_codes,
                confidence_info={"session": self.session_label(snapshot), "score": 0.0},
            )

        session = self.session_label(snapshot)
        if not self.session_is_allowed(snapshot, self.config.allowed_sessions):
            return self.flat(
                "SESSION_BLOCKED",
                confidence_info={"session": session, "score": 0.0},
            )

        spread_points = self.numeric(snapshot, "spread_points")
        spread_zscore = self.numeric(snapshot, "spread_zscore")
        if (
            spread_points > self.config.max_spread_points
            or spread_zscore > self.config.max_spread_zscore
        ):
            return self.flat(
                "SPREAD_ABNORMAL",
                confidence_info={
                    "session": session,
                    "spread_points": round(spread_points, 4),
                    "spread_zscore": round(spread_zscore, 4),
                    "score": 0.0,
                },
            )

        atr_value = self.numeric(snapshot, "atr")
        atr_pct = self.numeric(snapshot, "atr_pct")
        rolling_vol = self.numeric(snapshot, "rolling_volatility")
        if atr_value <= 0.0 or atr_pct < self.config.min_atr_pct:
            return self.flat(
                "ATR_TOO_LOW",
                confidence_info={
                    "session": session,
                    "atr": round(atr_value, 8),
                    "atr_pct": round(atr_pct, 8),
                    "score": 0.0,
                },
            )
        if rolling_vol < self.config.min_rolling_volatility:
            return self.flat(
                "VOLATILITY_TOO_LOW",
                confidence_info={
                    "session": session,
                    "rolling_volatility": round(rolling_vol, 8),
                    "score": 0.0,
                },
            )

        breakout_range = self.numeric(snapshot, "breakout_range")
        consolidation_ratio = breakout_range / atr_value
        if consolidation_ratio > self.config.max_consolidation_atr_ratio:
            return self.flat(
                "NO_CONSOLIDATION",
                confidence_info={
                    "session": session,
                    "consolidation_ratio": round(consolidation_ratio, 4),
                    "score": 0.0,
                },
            )

        breakout_position = self.numeric(snapshot, "breakout_position")
        candle_body = self.numeric(snapshot, "candle_body")
        candle_body_fraction = self.numeric(snapshot, "candle_body_fraction")
        close_location = self.numeric(snapshot, "candle_close_location")
        return_1 = self.numeric(snapshot, "return_1")

        common_confidence = {
            "session": session,
            "breakout_position": round(breakout_position, 4),
            "consolidation_ratio": round(consolidation_ratio, 4),
            "rolling_volatility": round(rolling_vol, 8),
            "atr_pct": round(atr_pct, 8),
            "spread_points": round(spread_points, 4),
            "spread_zscore": round(spread_zscore, 4),
            "candle_body_fraction": round(candle_body_fraction, 4),
        }

        volatility_component = min(
            rolling_vol / max(self.config.min_rolling_volatility * 2.0, 1e-9),
            1.0,
        )
        body_component = min(
            candle_body_fraction / max(self.config.min_candle_body_fraction, 1e-9),
            1.0,
        )

        if (
            breakout_position >= self.config.min_breakout_position_long
            and return_1 > 0.0
            and candle_body > 0.0
            and candle_body_fraction >= self.config.min_candle_body_fraction
            and close_location >= 0.65
        ):
            score = self.bounded_score(
                volatility_component,
                body_component,
                breakout_position,
            )
            return self.long(
                "CONSOLIDATION_READY",
                "BREAKOUT_LONG_CONFIRMED",
                "VOLATILITY_CONFIRMED",
                "SPREAD_OK",
                confidence_info={**common_confidence, "score": score},
            )

        if (
            breakout_position <= self.config.max_breakout_position_short
            and return_1 < 0.0
            and candle_body < 0.0
            and candle_body_fraction >= self.config.min_candle_body_fraction
            and close_location <= 0.35
        ):
            score = self.bounded_score(
                volatility_component,
                body_component,
                1.0 - breakout_position,
            )
            return self.short(
                "CONSOLIDATION_READY",
                "BREAKOUT_SHORT_CONFIRMED",
                "VOLATILITY_CONFIRMED",
                "SPREAD_OK",
                confidence_info={**common_confidence, "score": score},
            )

        return self.flat(
            "BREAKOUT_NOT_CONFIRMED",
            confidence_info={**common_confidence, "score": 0.0},
        )


__all__ = ["BreakoutVolatilityStrategy", "BreakoutVolatilityConfig"]
