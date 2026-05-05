"""Aggregator state — tracks open positions opened by signal_aggregator.

Stores per-ticket metadata that we need at close-time:
  - equity_at_entry: snapshot of account equity when the position was opened.
    Used as the anchor for the soft-stop threshold (drawdown is measured
    against THIS value, not the live account equity).
  - soft_stop_pct: float in [0,1]. If floating loss reaches
    -soft_stop_pct * equity_at_entry, the position is force-closed.
  - target_pct: float in [0,1]. Target unrealized profit (default 0.01 = 1%).
  - profile: "conservative"|"normal"|"aggressive" (informational).
  - source_strategy / source_score: which sub-strategy emitted the original
    setup, for post-mortem.

The state lives in aggregator_positions.json next to the bot. It is updated
from auto_trader.py at: open (register), close (remove). The soft-stop loop
reads this file every iteration to know which open MT5 positions to police.

Config (profile + target_pct) lives in strategy_config.json under the
"aggregator" key, read on every iteration.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

log = logging.getLogger("aggregator-state")

_STATE_DIR_ENV = (os.environ.get("STATE_DIR") or "").strip()
if _STATE_DIR_ENV:
    _STATE_DIR = Path(_STATE_DIR_ENV)
else:
    _STATE_DIR = Path("/opt/trading-bot/state")

POSITIONS_FILE = _STATE_DIR / "aggregator_positions.json"
CONFIG_FILE = _STATE_DIR / "strategy_config.json"

# Profile → soft-stop drawdown (fraction of equity_at_entry).
PROFILE_DRAWDOWN: Dict[str, float] = {
    "conservative": 0.10,
    "normal":       0.25,
    "aggressive":   0.50,
}
DEFAULT_PROFILE = "conservative"
DEFAULT_TARGET_PCT = 0.01   # +1% of equity at entry

# Per-symbol profile overrides (validated by 60-day backtest 2026-05-05).
# Symbols NOT in this map use DEFAULT_PROFILE; symbols not in
# `allowed_symbols` are blocked entirely.
DEFAULT_SYMBOL_PROFILES: Dict[str, str] = {
    "EURUSD": "conservative",
    "GBPUSD": "aggressive",
}
DEFAULT_ALLOWED_SYMBOLS = ["EURUSD", "GBPUSD"]


def _load_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("read %s failed: %s", path, exc)
    return default


def _save_json(path: Path, data) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError as exc:
        log.warning("write %s failed: %s", path, exc)
        return False


def load_profile(symbol: Optional[str] = None) -> dict:
    """Returns the live profile config for a symbol (or the global default
    if symbol is None / not in the per-symbol map).

    Returned shape:
        {"profile": "conservative", "drawdown_pct": 0.10, "target_pct": 0.01}

    Lookup order for profile:
      1. strategy_config.aggregator.symbol_profiles[<SYMBOL>]
      2. DEFAULT_SYMBOL_PROFILES[<SYMBOL>] (compiled-in defaults)
      3. strategy_config.aggregator.profile (legacy global)
      4. DEFAULT_PROFILE
    """
    cfg = _load_json(CONFIG_FILE, {}) or {}
    agg = cfg.get("aggregator", {}) or {}
    sym_map = agg.get("symbol_profiles") or DEFAULT_SYMBOL_PROFILES

    profile = None
    if symbol:
        profile = sym_map.get(symbol.upper()) or DEFAULT_SYMBOL_PROFILES.get(symbol.upper())
    if profile is None:
        profile = agg.get("profile", DEFAULT_PROFILE)
    profile = str(profile).lower()
    if profile not in PROFILE_DRAWDOWN:
        profile = DEFAULT_PROFILE

    target_pct = float(agg.get("target_pct", DEFAULT_TARGET_PCT))
    target_pct = max(0.001, min(0.10, target_pct))
    return {
        "profile": profile,
        "drawdown_pct": PROFILE_DRAWDOWN[profile],
        "target_pct": target_pct,
    }


def allowed_symbols() -> list:
    """Symbols the aggregator is allowed to trade. Reads from config or
    falls back to DEFAULT_ALLOWED_SYMBOLS."""
    cfg = _load_json(CONFIG_FILE, {}) or {}
    agg = cfg.get("aggregator", {}) or {}
    sym_list = agg.get("allowed_symbols")
    if isinstance(sym_list, list) and sym_list:
        return [str(s).upper() for s in sym_list]
    return list(DEFAULT_ALLOWED_SYMBOLS)


def is_symbol_allowed(symbol: str) -> bool:
    return symbol.upper() in allowed_symbols()


def is_active_strategy() -> bool:
    """True iff strategy_config.json has signal_aggregator as the active
    single-mode strategy."""
    cfg = _load_json(CONFIG_FILE, {}) or {}
    return (
        cfg.get("mode") == "single"
        and cfg.get("active_strategy") == "signal_aggregator"
    )


def list_positions() -> Dict[str, dict]:
    """Returns {ticket_str: meta} for all live aggregator positions."""
    return _load_json(POSITIONS_FILE, {}) or {}


def get_position(ticket: int) -> Optional[dict]:
    return list_positions().get(str(int(ticket)))


def register_position(
    *,
    ticket: int,
    symbol: str,
    side: str,
    equity_at_entry: float,
    profile: str,
    target_pct: float,
    source_strategy: str,
    source_score: int,
    entry: float,
    lots: float,
) -> bool:
    """Persist that this ticket is an aggregator-managed position."""
    profile = profile if profile in PROFILE_DRAWDOWN else DEFAULT_PROFILE
    state = list_positions()
    state[str(int(ticket))] = {
        "ticket": int(ticket),
        "symbol": symbol,
        "side": side,
        "entry": float(entry),
        "lots": float(lots),
        "equity_at_entry": float(equity_at_entry),
        "soft_stop_pct": PROFILE_DRAWDOWN[profile],
        "target_pct": float(target_pct),
        "profile": profile,
        "source_strategy": source_strategy,
        "source_score": int(source_score),
        "opened_at": datetime.now(timezone.utc).isoformat(),
    }
    return _save_json(POSITIONS_FILE, state)


def remove_position(ticket: int) -> bool:
    state = list_positions()
    if str(int(ticket)) in state:
        state.pop(str(int(ticket)), None)
        return _save_json(POSITIONS_FILE, state)
    return False
