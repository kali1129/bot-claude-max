"""EMA/RSI trend-following strategy.

Port of xm-mt5-trading-platform/src/strategies/ema_rsi_trend.py. Logic
unchanged; deps adapted to use the new FeatureSnapshot defined in this
package. No legacy `common.models.*` import.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .base import BaseStrategy, FeatureSnapshot, StrategyDecision


@dataclass(frozen=True, slots=True)
class EMARSITrendConfig:
    """Configuration for the EMA/RSI trend strategy."""

    fast_period: int = 5
    slow_period: int = 20
    rsi_long_min: float = 55.0
    rsi_short_max: float = 45.0
    min_atr_pct: float = 0.00015
    max_spread_points: float = 25.0
    allowed_sessions: tuple[str, ...] = ("LONDON", "NEW_YORK")
    min_normalized_gap: float = 0.0
    min_rolling_volatility: float = 0.0
    max_rolling_volatility: float = 0.0

    @classmethod
    def from_mapping(
        cls,
        data: Mapping[str, object] | None = None,
        *,
        fast_period: int = 5,
        slow_period: int = 20,
    ) -> "EMARSITrendConfig":
        payload = dict(data or {})
        allowed_sessions_raw = payload.get("allowed_sessions", ("LONDON", "NEW_YORK"))
        if isinstance(allowed_sessions_raw, (list, tuple)):
            allowed_sessions = tuple(str(value).upper() for value in allowed_sessions_raw)
        else:
            allowed_sessions = ("LONDON", "NEW_YORK")
        return cls(
            fast_period=int(payload.get("fast_period", fast_period)),
            slow_period=int(payload.get("slow_period", slow_period)),
            rsi_long_min=float(payload.get("rsi_long_min", 55.0)),
            rsi_short_max=float(payload.get("rsi_short_max", 45.0)),
            min_atr_pct=float(payload.get("min_atr_pct", 0.00015)),
            max_spread_points=float(payload.get("max_spread_points", 25.0)),
            allowed_sessions=allowed_sessions,
            min_normalized_gap=float(payload.get("min_normalized_gap", 0.0)),
            min_rolling_volatility=float(payload.get("min_rolling_volatility", 0.0)),
            max_rolling_volatility=float(payload.get("max_rolling_volatility", 0.0)),
        )


class EMARSITrendStrategy(BaseStrategy):
    """Deterministic trend strategy based on EMA alignment and RSI confirmation."""

    name = "ema_rsi_trend"

    def __init__(self, config: EMARSITrendConfig | None = None) -> None:
        self.config = config or EMARSITrendConfig()

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None = None) -> "EMARSITrendStrategy":
        return cls(EMARSITrendConfig.from_mapping(data))

    def evaluate(self, snapshot: FeatureSnapshot) -> StrategyDecision:
        if not snapshot.is_fresh:
            return self.flat(
                "SNAPSHOT_INVALID",
                confidence_info={"session": self.session_label(snapshot), "score": 0.0},
            )

        required = (
            "fast_ema",
            "slow_ema",
            "normalized_trend_gap",
            "rsi",
            "atr_pct",
            "spread_points",
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
        if spread_points > self.config.max_spread_points:
            return self.flat(
                "SPREAD_TOO_HIGH",
                confidence_info={
                    "session": session,
                    "spread_points": round(spread_points, 4),
                    "score": 0.0,
                },
            )

        atr_pct = self.numeric(snapshot, "atr_pct")
        if atr_pct < self.config.min_atr_pct:
            return self.flat(
                "ATR_TOO_LOW",
                confidence_info={
                    "session": session,
                    "atr_pct": round(atr_pct, 8),
                    "score": 0.0,
                },
            )

        fast_ema = self.numeric(snapshot, "fast_ema")
        slow_ema = self.numeric(snapshot, "slow_ema")
        normalized_gap = self.numeric(snapshot, "normalized_trend_gap")
        rsi_value = self.numeric(snapshot, "rsi")

        rolling_vol_raw = snapshot.values.get("rolling_volatility")
        rolling_vol: float | None = None
        if rolling_vol_raw is not None:
            try:
                rolling_vol = float(rolling_vol_raw)
            except (TypeError, ValueError):
                rolling_vol = None

        common_confidence = {
            "session": session,
            "fast_period": self.config.fast_period,
            "slow_period": self.config.slow_period,
            "ema_gap": round(fast_ema - slow_ema, 8),
            "normalized_gap": round(normalized_gap, 8),
            "rsi": round(rsi_value, 4),
            "atr_pct": round(atr_pct, 8),
            "spread_points": round(spread_points, 4),
            "rolling_volatility": round(rolling_vol, 8) if rolling_vol is not None else None,
        }

        if rolling_vol is not None:
            if (
                self.config.min_rolling_volatility > 0.0
                and rolling_vol < self.config.min_rolling_volatility
            ):
                return self.flat(
                    "REGIME_VOL_TOO_LOW",
                    confidence_info={**common_confidence, "score": 0.0},
                )
            if (
                self.config.max_rolling_volatility > 0.0
                and rolling_vol > self.config.max_rolling_volatility
            ):
                return self.flat(
                    "REGIME_VOL_TOO_HIGH",
                    confidence_info={**common_confidence, "score": 0.0},
                )

        if abs(normalized_gap) < self.config.min_normalized_gap:
            return self.flat(
                "EMA_GAP_TOO_SMALL",
                confidence_info={**common_confidence, "score": 0.0},
            )

        trend_component = min(abs(normalized_gap) / max(self.config.min_atr_pct, 1e-9), 1.0)
        volatility_component = min(atr_pct / max(self.config.min_atr_pct * 2.0, 1e-9), 1.0)

        if fast_ema > slow_ema:
            if rsi_value < self.config.rsi_long_min:
                return self.flat(
                    "RSI_LONG_NOT_CONFIRMED",
                    "EMA_BULLISH",
                    confidence_info={**common_confidence, "score": 0.0},
                )
            score = self.bounded_score(
                trend_component,
                volatility_component,
                min((rsi_value - 50.0) / 20.0, 1.0),
            )
            return self.long(
                "EMA_BULLISH",
                "RSI_LONG_CONFIRMED",
                "ATR_OK",
                "SPREAD_OK",
                confidence_info={**common_confidence, "score": score},
            )

        if fast_ema < slow_ema:
            if rsi_value > self.config.rsi_short_max:
                return self.flat(
                    "RSI_SHORT_NOT_CONFIRMED",
                    "EMA_BEARISH",
                    confidence_info={**common_confidence, "score": 0.0},
                )
            score = self.bounded_score(
                trend_component,
                volatility_component,
                min((50.0 - rsi_value) / 20.0, 1.0),
            )
            return self.short(
                "EMA_BEARISH",
                "RSI_SHORT_CONFIRMED",
                "ATR_OK",
                "SPREAD_OK",
                confidence_info={**common_confidence, "score": score},
            )

        return self.flat(
            "EMA_NEUTRAL",
            confidence_info={**common_confidence, "score": 0.0},
        )


__all__ = ["EMARSITrendStrategy", "EMARSITrendConfig"]
