"""Per-setup and per-symbol performance memory.

Port of xm-mt5-trading-platform/src/risk/setup_memory.py.

Tracks win rates, cumulative PnL and consecutive loss streaks for each
(symbol, signal-driver) combination so the bot can penalise poor setups
and favour proven ones — without ML.

Persistence: JSON file. Path defaults to `risk-mcp/setup_memory.json`
(adjacent to `state.json`). Override via `SETUP_MEMORY_PATH` env var.

Schema is intentionally identical to the legacy file so the user's history
can be moved by a copy.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_PATH = HERE.parent / "setup_memory.json"


@dataclass
class SetupStats:
    """Aggregate stats for a setup or symbol."""

    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    consecutive_losses: int = 0

    @property
    def total_trades(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0.5

    def record(self, *, won: bool, pnl: float) -> None:
        if won:
            self.wins += 1
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.consecutive_losses += 1
        self.total_pnl += pnl

    def to_dict(self) -> dict[str, Any]:
        return {
            "wins": self.wins,
            "losses": self.losses,
            "total_pnl": round(self.total_pnl, 4),
            "consecutive_losses": self.consecutive_losses,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "SetupStats":
        obj = cls()
        obj.wins = int(d.get("wins", 0))
        obj.losses = int(d.get("losses", 0))
        obj.total_pnl = float(d.get("total_pnl", 0.0))
        obj.consecutive_losses = int(d.get("consecutive_losses", 0))
        return obj


class SetupMemory:
    """Persistent per-setup and per-symbol performance tracker.

    Key space:
      `SYMBOL:driver`       — setup-level stats
      `SYMBOL:__symbol__`   — symbol-level stats (for consec-losses gates)
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = Path(path) if path else _resolve_path()
        self._data: dict[str, SetupStats] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self._path

    # ----- persistence -----

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return  # corrupt → start fresh
        for key, val in raw.items():
            if isinstance(val, dict):
                self._data[key] = SetupStats.from_dict(val)

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps({k: v.to_dict() for k, v in self._data.items()}, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ----- key helpers -----

    @staticmethod
    def _setup_key(symbol: str, driver: str) -> str:
        clean = str(driver or "generic").split(";")[0].strip()[:32].lower().replace(" ", "_")
        return f"{symbol.upper()}:{clean}"

    @staticmethod
    def _symbol_key(symbol: str) -> str:
        return f"{symbol.upper()}:__symbol__"

    # ----- write -----

    def record_trade(self, *, symbol: str, driver: str, won: bool, pnl: float) -> None:
        for key in (self._setup_key(symbol, driver), self._symbol_key(symbol)):
            if key not in self._data:
                self._data[key] = SetupStats()
            self._data[key].record(won=won, pnl=pnl)
        self._save()

    # ----- read -----

    def setup_score(self, symbol: str, driver: str) -> float:
        """Score adjustment in [-0.20, +0.10]. Returns 0.0 with < 3 trades."""
        stats = self._data.get(self._setup_key(symbol, driver))
        if stats is None or stats.total_trades < 3:
            return 0.0
        wr = stats.win_rate
        pnl_bias = max(-0.05, min(0.05, stats.total_pnl / 100.0))
        if wr < 0.35:
            return max(-0.20, -0.15 + pnl_bias)
        if wr < 0.45:
            return max(-0.10, -0.05 + pnl_bias)
        if wr > 0.65:
            return min(0.10, 0.07 + pnl_bias)
        return pnl_bias

    def symbol_consecutive_losses(self, symbol: str) -> int:
        stats = self._data.get(self._symbol_key(symbol))
        return 0 if stats is None else stats.consecutive_losses

    def symbol_should_reduce(self, symbol: str) -> bool:
        return self.symbol_consecutive_losses(symbol) >= 2

    def symbol_should_block(self, symbol: str) -> bool:
        return self.symbol_consecutive_losses(symbol) >= 4

    def get_setup_stats(self, symbol: str, driver: str) -> SetupStats | None:
        return self._data.get(self._setup_key(symbol, driver))

    def get_symbol_stats(self, symbol: str) -> SetupStats | None:
        return self._data.get(self._symbol_key(symbol))

    def setup_history_note(self, symbol: str, driver: str) -> str:
        stats = self._data.get(self._setup_key(symbol, driver))
        consec = self.symbol_consecutive_losses(symbol)
        if stats is None or stats.total_trades < 3:
            return ""
        wr = stats.win_rate
        if consec >= 4:
            return f"símbolo bloqueado ({consec} pérdidas seguidas)"
        if consec >= 2:
            return f"racha negativa ({consec} pérdidas seguidas)"
        if wr < 0.40:
            return f"setup débil ({wr:.0%} WR, {stats.total_trades}op)"
        if wr > 0.60:
            return f"setup favorecido ({wr:.0%} WR, {stats.total_trades}op)"
        return ""

    def all_keys(self) -> list[str]:
        return sorted(self._data.keys())


def _resolve_path() -> Path:
    """Resolve memory file path. SETUP_MEMORY_PATH env wins."""
    env = os.environ.get("SETUP_MEMORY_PATH")
    if env:
        return Path(env).expanduser()
    return DEFAULT_PATH


__all__ = ["SetupMemory", "SetupStats"]
