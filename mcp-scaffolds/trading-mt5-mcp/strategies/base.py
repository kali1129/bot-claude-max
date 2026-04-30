"""Strategy base class and Signal dataclass for the multi-strategy engine.

Every strategy implements ``propose()`` which returns a list of candidate
signals for a given symbol. The auto_trader picks the best signal across
the watchlist and applies global hard filters (spread, session) before
executing.

Each strategy defines:
  - preferred_symbols: symbols it operates best on (None = all)
  - blocked_symbols: symbols it should never trade
  - trading_hours: list of (start_utc, end_utc) windows when the strategy
    is active. Empty list = 24/7. Multiple windows supported.
  - always_24h_symbols: symbols that trade 24/7 regardless of hour windows
    (crypto typically).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class Signal:
    """A trade proposal from a strategy."""
    symbol: str
    side: str                    # "buy" or "sell"
    entry: float
    sl: float
    tp: float
    atr: float
    score: int                   # 0-100 quality rating
    rec: str                     # "TAKE", "WAIT", "SKIP"
    breakdown: Dict[str, int]    # per-component scores
    strategy_id: str             # which strategy produced this
    extra: Dict = field(default_factory=dict)  # strategy-specific metadata


class Strategy(ABC):
    """Base class for all trading strategies."""

    # --- Identity (override in subclass) ---
    id: str = "base"
    name: str = "Base Strategy"
    description: str = ""
    strategy_type: str = "unknown"   # "trend", "reversion", "breakout"
    color: str = "blue"              # UI accent color

    # --- Theoretical performance (from research/backtests) ---
    theoretical_wr: float = 0.0      # expected win rate 0-100
    theoretical_rr: float = 0.0      # expected R:R ratio
    theoretical_expectancy: float = 0.0  # expected R per trade

    # --- Parameters ---
    min_score: int = 70              # minimum score to recommend TAKE
    sl_atr_mult: float = 1.5        # SL = N x ATR
    tp_atr_mult: float = 3.0        # TP = N x ATR

    # --- Market & schedule preferences (override per strategy) ---
    # None = all symbols allowed. Set = only these symbols.
    preferred_symbols: Optional[Set[str]] = None
    # Symbols this strategy should NEVER trade (e.g. crypto for a forex-only strat)
    blocked_symbols: Set[str] = frozenset()
    # Trading windows as list of (start_hour_utc, end_hour_utc) tuples.
    # Empty list = 24/7. Hours are 0-23. Wrapping (22,7) means 22:00-07:00.
    trading_hours: List[Tuple[int, int]] = []
    # Symbols that ignore trading_hours (always tradeable). Typically crypto.
    always_24h: Set[str] = frozenset({"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"})
    # Human-readable schedule description for dashboard
    schedule_desc: str = "24/7"

    def is_symbol_allowed(self, symbol: str) -> Tuple[bool, str]:
        """Check if this strategy should trade this symbol."""
        sym = symbol.upper()
        if sym in self.blocked_symbols:
            return False, f"BLOCKED_SYMBOL ({sym})"
        if self.preferred_symbols is not None and sym not in self.preferred_symbols:
            return False, f"NOT_PREFERRED ({sym})"
        return True, "OK"

    def is_in_trading_hours(self, symbol: str, utc_hour: Optional[int] = None) -> Tuple[bool, str]:
        """Check if current UTC hour is within this strategy's trading windows."""
        sym = symbol.upper()
        # 24/7 symbols bypass hour checks
        if sym in self.always_24h:
            return True, "CRYPTO_24H"
        # No trading_hours defined = always active
        if not self.trading_hours:
            return True, "NO_HOUR_RESTRICTION"
        if utc_hour is None:
            utc_hour = datetime.now(timezone.utc).hour
        for start, end in self.trading_hours:
            if start <= end:
                # Normal window: e.g. (7, 17)
                if start <= utc_hour < end:
                    return True, f"IN_WINDOW ({start:02d}-{end:02d})"
            else:
                # Overnight window: e.g. (22, 7) means 22:00-07:00
                if utc_hour >= start or utc_hour < end:
                    return True, f"IN_WINDOW ({start:02d}-{end:02d})"
        return False, f"OUTSIDE_HOURS (now={utc_hour:02d} UTC)"

    @abstractmethod
    def propose(
        self,
        symbol: str,
        tick: dict,
        bars_m15: List[Dict],
        bars_h4: Optional[List[Dict]],
        bars_d1: Optional[List[Dict]],
    ) -> List[Signal]:
        """Return 0-2 candidate signals (buy, sell) for this symbol."""
        ...

    def hard_filter(self, signal: Signal, tick: dict) -> tuple:
        """Strategy-specific hard filter applied AFTER scoring.
        Returns (pass: bool, reason: str).
        The base implementation checks symbol + hours.
        Subclasses should call super().hard_filter() first.
        """
        # Check symbol allowlist/blocklist
        sym_ok, sym_reason = self.is_symbol_allowed(signal.symbol)
        if not sym_ok:
            return False, sym_reason
        # Check trading hours
        hr_ok, hr_reason = self.is_in_trading_hours(signal.symbol)
        if not hr_ok:
            return False, hr_reason
        return True, "OK"

    def to_dict(self) -> dict:
        """Serialize for the /api/strategies endpoint."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "type": self.strategy_type,
            "color": self.color,
            "theoretical": {
                "win_rate": self.theoretical_wr,
                "rr": self.theoretical_rr,
                "expectancy": self.theoretical_expectancy,
            },
            "params": {
                "min_score": self.min_score,
                "sl_atr_mult": self.sl_atr_mult,
                "tp_atr_mult": self.tp_atr_mult,
            },
            "schedule": self.schedule_desc,
            "preferred_symbols": sorted(self.preferred_symbols) if self.preferred_symbols else None,
            "blocked_symbols": sorted(self.blocked_symbols) if self.blocked_symbols else [],
            "trading_hours": [{"start": s, "end": e} for s, e in self.trading_hours] if self.trading_hours else [],
        }
