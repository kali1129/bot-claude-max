"""Multi-strategy engine registry.

v3.2 - 2026-05-01: Per-user config via STATE_DIR env var. Mode toggle
       AUTO (all strategies, best score wins) vs SINGLE (one strategy).
       Plus per-user min_score override.

v3.1 - 2026-04-30: Multi-strategy scheduling. All strategies propose
       signals in their trading hours. Best score wins.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

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
DEFAULT_MODE = "auto"      # auto = best-score across all; single = only active
DEFAULT_MIN_SCORE = 70     # default UI score gate; CLI arg precedes
MIN_SCORE_FLOOR = 1        # nunca dejar 0 (todo señal pasaría)
MIN_SCORE_CEIL = 95        # NO 100% — no existe certeza absoluta en trading

# STATE_DIR env var (set by process_supervisor for user-bots) overrides
# global path. Admin's bot reads global, user-bots read their own.
_STATE_DIR_ENV = (os.environ.get("STATE_DIR") or "").strip()
if _STATE_DIR_ENV:
    STATE_FILE = Path(_STATE_DIR_ENV) / "strategy_config.json"
else:
    STATE_FILE = Path("/opt/trading-bot/state/strategy_config.json")

STRATEGY_HOURS: Dict[str, list] = {
    "trend_rider":     [{"start": 8, "end": 17}],
    "mean_reverter":   [{"start": 0, "end": 7}, {"start": 17, "end": 23}],
    "breakout_hunter": [{"start": 7, "end": 10}, {"start": 13, "end": 16}],
    "score_v3":        [{"start": 7, "end": 20}],
}


def clamp_min_score(value) -> int:
    """Clamp min_score al rango válido. NO permite 100% (ni > 95)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MIN_SCORE
    return max(MIN_SCORE_FLOOR, min(MIN_SCORE_CEIL, v))


def _is_in_hours(strategy_id: str, utc_hour: int) -> bool:
    hours = STRATEGY_HOURS.get(strategy_id, [])
    if not hours:
        return True
    for window in hours:
        if window["start"] <= utc_hour < window["end"]:
            return True
    return False


def load_config() -> dict:
    """Read full config: mode, active_strategy, min_score. Falls back to
    defaults if file missing or corrupt."""
    out = {
        "mode": DEFAULT_MODE,
        "active_strategy": DEFAULT_STRATEGY,
        "min_score": DEFAULT_MIN_SCORE,
    }
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            mode = data.get("mode", DEFAULT_MODE)
            if mode not in ("auto", "single"):
                mode = DEFAULT_MODE
            sid = data.get("active_strategy", DEFAULT_STRATEGY)
            if sid not in REGISTRY:
                sid = DEFAULT_STRATEGY
            out.update({
                "mode": mode,
                "active_strategy": sid,
                "min_score": clamp_min_score(data.get("min_score",
                                                       DEFAULT_MIN_SCORE)),
                "updated_at": data.get("updated_at"),
            })
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to read strategy state: %s", exc)
    return out


def save_config(*, mode: Optional[str] = None,
                active_strategy: Optional[str] = None,
                min_score: Optional[int] = None) -> dict:
    """Atomic update — solo modifica los campos pasados."""
    cur = load_config()
    if mode is not None:
        if mode not in ("auto", "single"):
            return {"ok": False, "reason": "INVALID_MODE",
                    "detail": "mode debe ser 'auto' o 'single'"}
        cur["mode"] = mode
    if active_strategy is not None:
        if active_strategy not in REGISTRY:
            return {"ok": False, "reason": "UNKNOWN_STRATEGY",
                    "available": list(REGISTRY.keys())}
        cur["active_strategy"] = active_strategy
    if min_score is not None:
        clamped = clamp_min_score(min_score)
        if clamped != int(min_score):
            log.info("min_score %s clamped to %s (range %s..%s)",
                     min_score, clamped, MIN_SCORE_FLOOR, MIN_SCORE_CEIL)
        cur["min_score"] = clamped
    cur["updated_at"] = datetime.now(timezone.utc).isoformat()
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(cur, indent=2), encoding="utf-8")
        log.info("strategy_config saved: %s", cur)
        return {"ok": True, **cur}
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}


def get_eligible_strategies(utc_hour: int = None) -> List[Strategy]:
    """Si mode=single → solo la active_strategy. Si mode=auto → todas.

    Antes (v3.1) este método ignoraba la config y siempre devolvía todas.
    Ahora respeta el mode del usuario.
    """
    cfg = load_config()
    if cfg.get("mode") == "single":
        sid = cfg.get("active_strategy", DEFAULT_STRATEGY)
        strat = REGISTRY.get(sid)
        return [strat] if strat else list(REGISTRY.values())
    return list(REGISTRY.values())


def get_active_strategy() -> Strategy:
    """Retorna la strategy 'active' del config. En mode=auto sigue siendo
    la 'preferida' / etiqueta en UI, pero el bot evalúa todas."""
    cfg = load_config()
    sid = cfg.get("active_strategy", DEFAULT_STRATEGY)
    return REGISTRY.get(sid, REGISTRY[DEFAULT_STRATEGY])


def set_active_strategy(strategy_id: str) -> dict:
    """Compat: setea active_strategy + cambia a mode=single (asume que
    si el usuario eligió una específica, quiere usar SOLO esa)."""
    res = save_config(mode="single", active_strategy=strategy_id)
    if res.get("ok"):
        return {"ok": True, "active": strategy_id, "mode": "single"}
    return res


def set_auto_mode() -> dict:
    """Activa modo AUTO — el bot evalúa todas y opera la de mayor score."""
    return save_config(mode="auto")


def set_min_score(value) -> dict:
    """Cambia el umbral mínimo de score. Clamped a 1-95 (no 100%)."""
    return save_config(min_score=value)


def list_strategies() -> list:
    return [s.to_dict() for s in REGISTRY.values()]
