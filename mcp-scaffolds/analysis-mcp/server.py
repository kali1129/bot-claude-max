"""analysis-mcp v1.2.0 — Pure-compute technical analysis.

No state, no network. Receives OHLCV arrays and returns indicators,
structure, support/resistance, candle patterns and a composite setup score.

v1.2.0 adds legacy-port Layer 5: bounded analysis profile engine
(run_analysis_chain, rank_opportunities).
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

load_dotenv(HERE / ".env")

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("analysis-mcp")

from mcp.server.fastmcp import FastMCP  # noqa: E402

from lib import indicators as ind, structure as struct, scoring  # noqa: E402
from lib import feature_pipeline  # noqa: E402
from lib import filters as session_filters  # noqa: E402
from lib.strategies import list_strategies as _list_strategies  # noqa: E402
from lib.profiles.runner import ProfileRunner  # noqa: E402
from lib.profiles.models import AnalysisProfileContext  # noqa: E402
from lib.profiles.opportunity_ranker import (  # noqa: E402
    OpportunityInput,
    OpportunityRanker,
    RankerSettings,
)

__version__ = "1.2.0"  # +legacy-port: profiles engine (Layer 5)

# Singleton runner — disabled until a YAML config is supplied via env var.
# Set ANALYSIS_PROFILES_CONFIG=/path/to/analysis-profiles.yaml to activate.
_PROFILES_CONFIG = os.environ.get("ANALYSIS_PROFILES_CONFIG")
_profile_runner: ProfileRunner = ProfileRunner.from_yaml(_PROFILES_CONFIG)
mcp = FastMCP("analysis")


@mcp.tool()
def health() -> dict:
    return {"version": __version__, "stateless": True}


@mcp.tool()
def indicators(ohlcv: List[Dict]) -> dict:
    """Latest + previous of EMA(20/50/200), RSI(14), ATR(14), MACD, BB."""
    return ind.indicators_snapshot(ohlcv)


@mcp.tool()
def market_structure(ohlcv: List[Dict], swing_n: int = 5) -> dict:
    """Detects HH/HL/LH/LL pattern → UPTREND / DOWNTREND / RANGE / UNKNOWN."""
    return struct.market_structure(ohlcv, swing_n)


@mcp.tool()
def support_resistance(ohlcv: List[Dict], min_touches: int = 2,
                       tolerance_pct: float = 0.15) -> dict:
    return struct.support_resistance(ohlcv, min_touches, tolerance_pct)


@mcp.tool()
def candlestick_patterns(ohlcv: List[Dict]) -> dict:
    return struct.candlestick_patterns(ohlcv)


@mcp.tool()
def mtf_bias(ohlcv_h4: List[Dict], ohlcv_m15: List[Dict]) -> dict:
    return scoring.mtf_bias(ohlcv_h4, ohlcv_m15)


@mcp.tool()
def score_setup(
    ohlcv: List[Dict],
    side: str,
    entry: float,
    sl: float,
    tp: float,
    ohlcv_h4: List[Dict] = None,
) -> dict:
    """Composite 0..100 score → TAKE (≥70), WAIT (50..69), SKIP (<50)."""
    return scoring.score_setup(ohlcv, side, entry, sl, tp, ohlcv_h4)


# ============================================================================
# Legacy-port tools (from xm-mt5-trading-platform, adapted to OHLCV List[Dict])
# ============================================================================


@mcp.tool()
def list_strategies() -> dict:
    """Return registered deterministic strategy names."""
    return {"ok": True, "strategies": _list_strategies()}


@mcp.tool()
def evaluate_strategy(
    ohlcv: List[Dict],
    strategy_name: str,
    config: Dict | None = None,
) -> dict:
    """Run a registered strategy on the given OHLCV.

    Returns: {ok, strategy, direction (LONG/SHORT/FLAT), rationale_codes,
    score (0..1), confidence_info}.
    """
    try:
        return feature_pipeline.evaluate_strategy_on_ohlcv(ohlcv, strategy_name, config)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("evaluate_strategy failed")
        return {"ok": False, "reason": "INTERNAL_ERROR", "detail": str(exc)}


@mcp.tool()
def feature_snapshot(ohlcv: List[Dict]) -> dict:
    """Build a FeatureSnapshot dict from the given OHLCV.

    Returns: {ok, values: {feature_name: float}, labels: {session: ...},
    is_fresh: bool}.
    """
    snapshot = feature_pipeline.build_snapshot(ohlcv)
    payload = snapshot.to_dict()
    payload["ok"] = True
    return payload


@mcp.tool()
def session_filter(bar: Dict, settings: Dict | None = None) -> dict:
    """Apply the session/spread filter to a single bar.

    `bar` shape: {time, open, high, low, close, spread?}.
    Returns: {passed, reason, detail}.
    """
    return session_filters.apply_session_filter(bar, settings)


# ============================================================================
# Layer 5 tools — bounded analysis profile engine
# ============================================================================


@mcp.tool()
def run_analysis_chain(
    symbol: str,
    timestamp_iso: str,
    timeframe: str | None = None,
    context_age_seconds: float | None = None,
    market_data: Dict | None = None,
    operational_state: Dict | None = None,
    active_events: List[Dict] | None = None,
    collected_headlines: List[Dict] | None = None,
    relevant_headlines: List[Dict] | None = None,
    stale_headlines: List[Dict] | None = None,
    anomaly_signals: List[str] | None = None,
    log_lines: List[str] | None = None,
    metadata: Dict | None = None,
    profile_names: List[str] | None = None,
) -> dict:
    """Run the bounded analysis profile chain for one symbol.

    Returns `{"ok": true, "chain": <AnalysisChainResult dict>}`.
    Gate values: ALLOW / REDUCE_RISK / REVIEW / BLOCK.

    The set of profiles executed is controlled by the server's
    ANALYSIS_PROFILES_CONFIG env var (YAML). If no config is present the
    runner is disabled and every chain returns ALLOW with reason
    ANALYSIS_PROFILES_DISABLED.
    """
    try:
        from datetime import datetime, timezone

        try:
            ts = datetime.fromisoformat(timestamp_iso)
        except ValueError:
            return {
                "ok": False,
                "reason": "INVALID_TIMESTAMP",
                "detail": f"Cannot parse timestamp_iso: {timestamp_iso!r}",
            }

        ctx = AnalysisProfileContext(
            symbol=symbol,
            timestamp=ts,
            timeframe=timeframe,
            context_age_seconds=context_age_seconds,
            market_data=market_data,
            operational_state=operational_state,
            active_events=(
                tuple(active_events) if active_events is not None else None
            ),
            collected_headlines=(
                tuple(collected_headlines) if collected_headlines is not None else None
            ),
            relevant_headlines=(
                tuple(relevant_headlines) if relevant_headlines is not None else None
            ),
            stale_headlines=(
                tuple(stale_headlines) if stale_headlines is not None else None
            ),
            anomaly_signals=(
                tuple(anomaly_signals) if anomaly_signals is not None else None
            ),
            log_lines=tuple(log_lines) if log_lines is not None else None,
            metadata=dict(metadata or {}),
        )
        result = _profile_runner.run_chain(
            context=ctx,
            profile_names=profile_names or None,
        )
        return {"ok": True, "chain": result.to_dict()}
    except Exception as exc:
        log.exception("run_analysis_chain failed")
        return {"ok": False, "reason": "INTERNAL_ERROR", "detail": str(exc)}


@mcp.tool()
def rank_opportunities(
    opportunities: List[Dict],
    ranker_settings: Dict | None = None,
) -> dict:
    """Rank one or more symbol opportunities by composite score.

    Each element of `opportunities` must be a dict matching the
    `OpportunityInput` field schema. Returns a sorted list (best first) of
    `OpportunityRankerResult` dicts.

    Optional `ranker_settings` overrides scoring weights/thresholds.

    Returns `{"ok": true, "ranked": [...]}`.
    """
    try:
        settings = RankerSettings(**ranker_settings) if ranker_settings else None
        ranker = OpportunityRanker(settings=settings)
        inputs = [OpportunityInput(**item) for item in opportunities]
        ranked = ranker.rank(inputs)
        return {"ok": True, "ranked": [r.to_dict() for r in ranked]}
    except (TypeError, ValueError) as exc:
        return {
            "ok": False,
            "reason": "INVALID_INPUT",
            "detail": str(exc),
        }
    except Exception as exc:
        log.exception("rank_opportunities failed")
        return {"ok": False, "reason": "INTERNAL_ERROR", "detail": str(exc)}


if __name__ == "__main__":
    log.info("analysis-mcp v%s starting", __version__)
    mcp.run()
