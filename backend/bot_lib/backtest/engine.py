"""Minimal deterministic backtest engine.

Reduced port of xm-mt5-trading-platform/src/backtest/{engine,metrics,
slippage}.py. Trims legacy dependencies in favor of a higher-order signal
callback.

Pipeline:
  1. Caller passes OHLCV list[dict] and a `signal_fn(ohlcv_so_far) -> dict`
     callback. The callback returns:
        {"direction": "LONG" | "SHORT" | "FLAT", "atr": float, "score": float}
     where `atr` is the volatility used to size SL/TP, and `score` is an
     optional 0..1 confidence value the engine can gate on (`min_score`).
  2. For each bar (after warmup), engine calls the signal_fn and, if direction
     is non-FLAT and score >= min_score, opens a simulated position with
     ATR-based SL/TP.
  3. Each subsequent bar checks SL/TP hits in price order; positions exit
     when one is touched.
  4. At the end, compute metrics: trades, win rate, expectancy, max DD,
     profit factor, sharpe-like ratio.

Why a callback instead of a strategy registry: the backtest does NOT need
to import the analysis-mcp lib (which lives in mcp-scaffolds/) — that
makes the engine usable from anywhere and keeps tests isolated. Production
callers can wire `signal_fn` to call analysis-mcp via the strategy registry
once that import path is set up cleanly in the host process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import statistics
from typing import Any, Callable, Mapping


SignalFn = Callable[[list[Mapping[str, Any]]], Mapping[str, Any]]


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class BacktestConfig:
    """Caller-tunable backtest settings."""

    initial_balance: float = 800.0
    risk_per_trade_pct: float = 1.0
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5
    commission_per_trade: float = 0.0
    slippage_pct: float = 0.0001
    warmup_bars: int = 50
    max_open_positions: int = 1
    min_score: float = 0.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None = None) -> "BacktestConfig":
        d = dict(data or {})
        return cls(
            initial_balance=float(d.get("initial_balance", 800.0)),
            risk_per_trade_pct=float(d.get("risk_per_trade_pct", 1.0)),
            sl_atr_mult=float(d.get("sl_atr_mult", 1.5)),
            tp_atr_mult=float(d.get("tp_atr_mult", 2.5)),
            commission_per_trade=float(d.get("commission_per_trade", 0.0)),
            slippage_pct=float(d.get("slippage_pct", 0.0001)),
            warmup_bars=int(d.get("warmup_bars", 50)),
            max_open_positions=int(d.get("max_open_positions", 1)),
            min_score=float(d.get("min_score", 0.0)),
        )


@dataclass
class _OpenPosition:
    side: str
    entry_time: datetime
    entry_price: float
    stop_loss: float
    take_profit: float
    units: float


@dataclass
class _ClosedTrade:
    side: str
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    stop_loss: float
    take_profit: float
    pnl: float
    exit_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "side": self.side,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "pnl": round(self.pnl, 4),
            "exit_reason": self.exit_reason,
        }


def _check_exits(
    pos: _OpenPosition,
    bar: Mapping[str, Any],
    cfg: BacktestConfig,
) -> tuple[float | None, str | None]:
    high = float(bar.get("high", math.nan))
    low = float(bar.get("low", math.nan))
    if not math.isfinite(high) or not math.isfinite(low):
        return None, None

    if pos.side == "LONG":
        if low <= pos.stop_loss:
            return pos.stop_loss * (1.0 - cfg.slippage_pct), "SL_HIT"
        if high >= pos.take_profit:
            return pos.take_profit * (1.0 - cfg.slippage_pct), "TP_HIT"
    else:
        if high >= pos.stop_loss:
            return pos.stop_loss * (1.0 + cfg.slippage_pct), "SL_HIT"
        if low <= pos.take_profit:
            return pos.take_profit * (1.0 + cfg.slippage_pct), "TP_HIT"
    return None, None


def _compute_metrics(closed: list[_ClosedTrade], initial_balance: float) -> dict[str, Any]:
    if not closed:
        return {
            "trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "total_pnl": 0.0, "expectancy": 0.0, "profit_factor": 0.0,
            "max_drawdown_pct": 0.0, "sharpe": 0.0,
            "ending_balance": initial_balance,
        }

    pnls = [t.pnl for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    total_pnl = sum(pnls)
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    win_rate = len(wins) / len(pnls)
    expectancy = win_rate * avg_win + (1.0 - win_rate) * avg_loss
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 0.0

    balance = initial_balance
    peak = balance
    max_dd = 0.0
    for p in pnls:
        balance += p
        peak = max(peak, balance)
        dd = (peak - balance) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    rets = [p / initial_balance for p in pnls]
    sharpe = 0.0
    if len(rets) > 1:
        mu = statistics.mean(rets)
        sigma = statistics.stdev(rets)
        sharpe = (mu / sigma * math.sqrt(len(rets))) if sigma > 0 else 0.0

    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 4),
        "total_pnl": round(total_pnl, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "expectancy": round(expectancy, 4),
        "profit_factor": round(profit_factor, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
        "sharpe": round(sharpe, 4),
        "ending_balance": round(balance, 4),
    }


def run_backtest(
    *,
    ohlcv: list[Mapping[str, Any]],
    signal_fn: SignalFn,
    config: BacktestConfig | Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one backtest pass.

    `signal_fn` receives the OHLCV slice up to and including the current bar
    and must return a dict with keys:
      - direction: "LONG" | "SHORT" | "FLAT"
      - atr: float (>0 to enter; engine uses this for SL/TP sizing)
      - score: float in [0, 1] (optional; defaults to 1.0)
    """
    cfg = config if isinstance(config, BacktestConfig) else BacktestConfig.from_mapping(config)
    if not ohlcv or len(ohlcv) <= cfg.warmup_bars + 1:
        return {
            "ok": False,
            "reason": "INSUFFICIENT_BARS",
            "detail": f"Need at least {cfg.warmup_bars + 2} bars; got {len(ohlcv)}.",
        }

    open_positions: list[_OpenPosition] = []
    closed: list[_ClosedTrade] = []
    balance = cfg.initial_balance

    for i in range(cfg.warmup_bars, len(ohlcv)):
        bar = ohlcv[i]
        bar_time = _parse_dt(bar.get("time"))
        bar_close = float(bar.get("close", math.nan))

        # 1. Check exits on existing positions
        still_open: list[_OpenPosition] = []
        for pos in open_positions:
            exit_price, reason = _check_exits(pos, bar, cfg)
            if exit_price is not None and reason is not None:
                pnl = (
                    (exit_price - pos.entry_price) * pos.units
                    if pos.side == "LONG"
                    else (pos.entry_price - exit_price) * pos.units
                ) - cfg.commission_per_trade
                closed.append(_ClosedTrade(
                    side=pos.side,
                    entry_time=pos.entry_time,
                    exit_time=bar_time,
                    entry_price=pos.entry_price,
                    exit_price=exit_price,
                    stop_loss=pos.stop_loss,
                    take_profit=pos.take_profit,
                    pnl=pnl,
                    exit_reason=reason,
                ))
                balance += pnl
            else:
                still_open.append(pos)
        open_positions = still_open

        # 2. Look for new entry
        if len(open_positions) >= cfg.max_open_positions:
            continue

        try:
            signal = signal_fn(list(ohlcv[: i + 1]))
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "ok": False,
                "reason": "SIGNAL_FN_RAISED",
                "detail": str(exc),
                "at_bar": i,
            }
        direction = str(signal.get("direction", "FLAT")).upper()
        if direction == "FLAT":
            continue
        score = float(signal.get("score", 1.0))
        if score < cfg.min_score:
            continue
        atr = float(signal.get("atr", 0.0))
        if not math.isfinite(atr) or atr <= 0:
            continue

        # 3. Open a position with ATR-based SL/TP
        if direction == "LONG":
            entry_price = bar_close * (1.0 + cfg.slippage_pct)
            sl = entry_price - atr * cfg.sl_atr_mult
            tp = entry_price + atr * cfg.tp_atr_mult
        else:
            entry_price = bar_close * (1.0 - cfg.slippage_pct)
            sl = entry_price + atr * cfg.sl_atr_mult
            tp = entry_price - atr * cfg.tp_atr_mult

        risk_per_unit = abs(entry_price - sl)
        if risk_per_unit <= 0:
            continue
        risk_dollars = balance * cfg.risk_per_trade_pct / 100.0
        units = risk_dollars / risk_per_unit

        open_positions.append(_OpenPosition(
            side=direction,
            entry_time=bar_time,
            entry_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            units=units,
        ))

    # Force-close at end of series
    if open_positions:
        last_bar = ohlcv[-1]
        last_close = float(last_bar.get("close", 0.0))
        last_time = _parse_dt(last_bar.get("time"))
        for pos in open_positions:
            pnl = (
                (last_close - pos.entry_price) * pos.units
                if pos.side == "LONG"
                else (pos.entry_price - last_close) * pos.units
            ) - cfg.commission_per_trade
            closed.append(_ClosedTrade(
                side=pos.side,
                entry_time=pos.entry_time,
                exit_time=last_time,
                entry_price=pos.entry_price,
                exit_price=last_close,
                stop_loss=pos.stop_loss,
                take_profit=pos.take_profit,
                pnl=pnl,
                exit_reason="EOD",
            ))
            balance += pnl

    metrics = _compute_metrics(closed, cfg.initial_balance)
    return {
        "ok": True,
        "config": {
            "initial_balance": cfg.initial_balance,
            "risk_per_trade_pct": cfg.risk_per_trade_pct,
            "sl_atr_mult": cfg.sl_atr_mult,
            "tp_atr_mult": cfg.tp_atr_mult,
            "warmup_bars": cfg.warmup_bars,
            "min_score": cfg.min_score,
            "max_open_positions": cfg.max_open_positions,
        },
        "total_bars": len(ohlcv),
        "metrics": metrics,
        "trades": [t.to_dict() for t in closed],
    }


__all__ = ["BacktestConfig", "SignalFn", "run_backtest"]
