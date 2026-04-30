"""Multi-strategy engine registry.

v3.1 - 2026-04-30: Multi-strategy scheduling. All strategies propose
       signals in their trading hours. Best score wins.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from .base import Strategy, Signal  # noqa: F401
from .trend_rider import TrendRider
from .mean_reverter import MeanReverter
from .breakout_hunter import BreakoutHunter
from .score_v3 import ScoreV3

log = logging.getLogger("strategies")

REGISTRY: Dict[str, Strategy] = {
    "trend_rider": TrendRider(),
    "mean_reverter": MeanReverter(),
    "breakout_hunter": BreakoutHunter(),
    "score_v3": ScoreV3(),
}

DEFAULT_STRATEGY = "trend_rider"
STATE_FILE = Path("/opt/trading-bot/state/strategy_config.json")

STRATEGY_HOURS: Dict[str, list] = {
    "trend_rider":     [{"start": 8, "end": 17}],
    "mean_reverter":   [{"start": 0, "end": 7}, {"start": 17, "end": 23}],
    "breakout_hunter": [{"start": 7, "end": 10}, {"start": 13, "end": 16}],
    "score_v3":        [{"start": 7, "end": 20}],
}


def _is_in_hours(strategy_id: str, utc_hour: int) -> bool:
    hours = STRATEGY_HOURS.get(strategy_id, [])
    if not hours:
        return True
    for window in hours:
        if window["start"] <= utc_hour < window["end"]:
            return True
    return False


def get_eligible_strategies(utc_hour: int = None) -> List[Strategy]:
    if utc_hour is None:
        utc_hour = datetime.now(timezone.utc).hour
    eligible = []
    for sid, strategy in REGISTRY.items():
        if _is_in_hours(sid, utc_hour):
            eligible.append(strategy)
    if not eligible:
        eligible.append(REGISTRY["mean_reverter"])
    return eligible


def get_active_strategy() -> Strategy:
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            sid = data.get("active_strategy", DEFAULT_STRATEGY)
            if sid in REGISTRY:
                return REGISTRY[sid]
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to read strategy state: %s", exc)
    return REGISTRY[DEFAULT_STRATEGY]


def set_active_strategy(strategy_id: str) -> dict:
    if strategy_id not in REGISTRY:
        return {"ok": False, "reason": "UNKNOWN_STRATEGY",
                "available": list(REGISTRY.keys())}
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({
            "active_strategy": strategy_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }), encoding="utf-8")
        log.info("Active strategy set to '%s'", strategy_id)
        return {"ok": True, "active": strategy_id}
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}


def list_strategies() -> list:
    return [s.to_dict() for s in REGISTRY.values()]
