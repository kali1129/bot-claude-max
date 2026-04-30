"""Hyperparameter optimization for trading strategies using Optuna.

Provides:
  - optimize_strategy(): runs Optuna study to find optimal parameters
  - walk_forward(): out-of-sample validation with sliding windows
  - monte_carlo(): bootstrap simulation of equity outcomes

All functions are CPU-bound and synchronous — call from a background
thread or process in the FastAPI endpoints.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Any, Mapping

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

from bot_lib.backtest.engine import run_backtest, BacktestConfig
from bot_lib.backtest.adapter import strategy_signal_fn, BACKTEST_STRATEGIES


# ═══════════════════════════════════════════════════════════════════
# Hyperoptimization with Optuna
# ═══════════════════════════════════════════════════════════════════

def _objective(trial, strategy_id: str, ohlcv: list, metric: str = "expectancy"):
    """Optuna objective function — maximize the chosen metric."""
    # Define parameter search space based on strategy
    sl_atr = trial.suggest_float("sl_atr_mult", 0.8, 3.0, step=0.1)
    tp_atr = trial.suggest_float("tp_atr_mult", 1.5, 6.0, step=0.1)
    min_score = trial.suggest_float("min_score", 0.3, 0.8, step=0.05)

    config = BacktestConfig(
        initial_balance=800.0,
        risk_per_trade_pct=1.0,
        sl_atr_mult=sl_atr,
        tp_atr_mult=tp_atr,
        commission_per_trade=0.10,
        slippage_pct=0.0001,
        warmup_bars=55,
        max_open_positions=1,
        min_score=min_score,
    )

    signal_fn = strategy_signal_fn(strategy_id)
    result = run_backtest(ohlcv=ohlcv, signal_fn=signal_fn, config=config)

    if not result.get("ok"):
        return -999.0

    metrics = result.get("metrics", {})
    trades = metrics.get("trades", 0)

    # Penalize too few trades (need statistical significance)
    if trades < 5:
        return -100.0 + trades

    if metric == "sharpe":
        return metrics.get("sharpe", -999.0)
    elif metric == "profit_factor":
        return metrics.get("profit_factor", 0.0)
    elif metric == "total_pnl":
        return metrics.get("total_pnl", -999.0)
    elif metric == "win_rate":
        return metrics.get("win_rate", 0.0)
    else:  # expectancy
        return metrics.get("expectancy", -999.0)


def optimize_strategy(
    strategy_id: str,
    ohlcv: list,
    n_trials: int = 50,
    metric: str = "expectancy",
) -> dict[str, Any]:
    """Run Optuna hyperparameter optimization.

    Returns:
      - best_params: dict of optimal parameters
      - best_value: the objective value at optimum
      - trials: list of trial results
      - backtest_result: full backtest with optimal params
    """
    if not HAS_OPTUNA:
        return {"error": "Optuna not installed. Run: pip install optuna"}

    study = optuna.create_study(direction="maximize", study_name=f"optimize_{strategy_id}")
    study.optimize(
        lambda trial: _objective(trial, strategy_id, ohlcv, metric),
        n_trials=n_trials,
        show_progress_bar=False,
    )

    best = study.best_trial
    best_params = best.params

    # Run final backtest with best params
    config = BacktestConfig(
        initial_balance=800.0,
        risk_per_trade_pct=1.0,
        sl_atr_mult=best_params["sl_atr_mult"],
        tp_atr_mult=best_params["tp_atr_mult"],
        commission_per_trade=0.10,
        slippage_pct=0.0001,
        warmup_bars=55,
        max_open_positions=1,
        min_score=best_params["min_score"],
    )
    signal_fn = strategy_signal_fn(strategy_id)
    final_result = run_backtest(ohlcv=ohlcv, signal_fn=signal_fn, config=config)

    # Add equity curve
    if final_result.get("ok") and final_result.get("trades"):
        equity = 800.0
        eq_curve = [{"trade": 0, "equity": equity}]
        for i, t in enumerate(final_result["trades"]):
            equity += t["pnl"]
            eq_curve.append({"trade": i + 1, "equity": round(equity, 2)})
        final_result["equity_curve"] = eq_curve

    # Collect trial summaries
    trial_summaries = []
    for t in study.trials:
        trial_summaries.append({
            "number": t.number,
            "params": t.params,
            "value": round(t.value, 4) if t.value is not None else None,
            "state": str(t.state),
        })

    return {
        "best_params": best_params,
        "best_value": round(best.value, 4),
        "n_trials": len(study.trials),
        "metric": metric,
        "strategy_id": strategy_id,
        "backtest_result": final_result,
        "trials": trial_summaries[-20:],  # last 20 for UI
        "param_importance": _param_importance(study),
    }


def _param_importance(study) -> dict:
    """Get parameter importance from Optuna study."""
    try:
        importance = optuna.importance.get_param_importances(study)
        return {k: round(v, 4) for k, v in importance.items()}
    except Exception:
        return {}


# ═══════════════════════════════════════════════════════════════════
# Walk-Forward Analysis
# ═══════════════════════════════════════════════════════════════════

def walk_forward(
    strategy_id: str,
    ohlcv: list,
    n_splits: int = 5,
    train_pct: float = 0.7,
) -> dict[str, Any]:
    """Walk-forward analysis: train on window, test on next segment.

    Splits the data into n_splits windows. For each:
      1. Train (optimize) on first train_pct of the window
      2. Test on remaining (1-train_pct) with the optimized params

    Returns out-of-sample metrics for each fold.
    """
    total_bars = len(ohlcv)
    window_size = total_bars // n_splits
    min_bars = 120  # need enough for warmup + indicators

    if window_size < min_bars:
        return {"error": f"Not enough bars. Need at least {min_bars * n_splits}, got {total_bars}"}

    folds = []
    for i in range(n_splits):
        start = i * window_size
        end = min(start + window_size, total_bars)
        if i == n_splits - 1:
            end = total_bars

        window = ohlcv[start:end]
        split_idx = int(len(window) * train_pct)

        train_data = window[:split_idx]
        test_data = window[split_idx:]

        if len(train_data) < min_bars or len(test_data) < 60:
            folds.append({
                "fold": i + 1,
                "skipped": True,
                "reason": "insufficient_bars",
            })
            continue

        # Optimize on train data (quick: 20 trials)
        if HAS_OPTUNA:
            opt_result = optimize_strategy(strategy_id, train_data, n_trials=20, metric="expectancy")
            best_params = opt_result.get("best_params", {})
        else:
            defaults = BACKTEST_STRATEGIES.get(strategy_id, {}).get("default_config", {})
            best_params = {
                "sl_atr_mult": defaults.get("sl_atr_mult", 1.5),
                "tp_atr_mult": defaults.get("tp_atr_mult", 2.5),
                "min_score": defaults.get("min_score", 0.5),
            }

        # Test with optimized params on out-of-sample
        config = BacktestConfig(
            initial_balance=800.0,
            risk_per_trade_pct=1.0,
            sl_atr_mult=best_params.get("sl_atr_mult", 1.5),
            tp_atr_mult=best_params.get("tp_atr_mult", 2.5),
            commission_per_trade=0.10,
            slippage_pct=0.0001,
            warmup_bars=55,
            max_open_positions=1,
            min_score=best_params.get("min_score", 0.5),
        )

        signal_fn = strategy_signal_fn(strategy_id)
        test_result = run_backtest(ohlcv=test_data, signal_fn=signal_fn, config=config)

        fold_data = {
            "fold": i + 1,
            "train_bars": len(train_data),
            "test_bars": len(test_data),
            "optimized_params": best_params,
        }

        if test_result.get("ok"):
            m = test_result.get("metrics", {})
            fold_data["test_metrics"] = {
                "trades": m.get("trades", 0),
                "win_rate": m.get("win_rate", 0),
                "total_pnl": m.get("total_pnl", 0),
                "profit_factor": m.get("profit_factor", 0),
                "sharpe": m.get("sharpe", 0),
                "max_drawdown_pct": m.get("max_drawdown_pct", 0),
                "expectancy": m.get("expectancy", 0),
            }
        else:
            fold_data["test_metrics"] = {"error": test_result.get("reason", "unknown")}

        folds.append(fold_data)

    # Aggregate OOS metrics
    oos_trades = sum(f.get("test_metrics", {}).get("trades", 0) for f in folds if not f.get("skipped"))
    oos_pnl = sum(f.get("test_metrics", {}).get("total_pnl", 0) for f in folds if not f.get("skipped"))
    oos_wrs = [f["test_metrics"]["win_rate"] for f in folds if not f.get("skipped") and f.get("test_metrics", {}).get("trades", 0) > 0]
    avg_oos_wr = statistics.mean(oos_wrs) if oos_wrs else 0

    return {
        "strategy_id": strategy_id,
        "n_splits": n_splits,
        "train_pct": train_pct,
        "total_bars": total_bars,
        "folds": folds,
        "aggregate": {
            "total_oos_trades": oos_trades,
            "total_oos_pnl": round(oos_pnl, 2),
            "avg_oos_win_rate": round(avg_oos_wr, 4),
            "folds_with_data": len([f for f in folds if not f.get("skipped")]),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# Monte Carlo Simulation
# ═══════════════════════════════════════════════════════════════════

def monte_carlo(
    trade_pnls: list[float],
    n_simulations: int = 1000,
    n_trades: int | None = None,
    initial_balance: float = 800.0,
) -> dict[str, Any]:
    """Monte Carlo simulation by bootstrap resampling of trade P&Ls.

    Randomly reorders trade results to generate distribution of possible
    equity outcomes. Shows confidence intervals for final balance,
    max drawdown, and risk of ruin.

    Args:
        trade_pnls: list of P&L values from closed trades
        n_simulations: number of random sequences to generate
        n_trades: trades per simulation (default: same as input)
        initial_balance: starting balance

    Returns:
        Percentile distribution of outcomes.
    """
    if not trade_pnls or len(trade_pnls) < 3:
        return {"error": "Need at least 3 trade P&Ls for Monte Carlo simulation"}

    if n_trades is None:
        n_trades = len(trade_pnls)

    final_balances = []
    max_drawdowns = []
    ruin_count = 0  # balance <= 0
    ruin_threshold = initial_balance * 0.5  # 50% loss = "ruin"
    ruin_50_count = 0

    for _ in range(n_simulations):
        balance = initial_balance
        peak = balance
        max_dd = 0.0
        ruined = False

        for _ in range(n_trades):
            pnl = random.choice(trade_pnls)
            balance += pnl
            if balance > peak:
                peak = balance
            dd = (peak - balance) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
            if balance <= 0:
                ruined = True
                break

        final_balances.append(round(balance, 2))
        max_drawdowns.append(round(max_dd * 100, 2))
        if ruined or balance <= 0:
            ruin_count += 1
        if balance <= ruin_threshold:
            ruin_50_count += 1

    # Compute percentiles
    final_balances.sort()
    max_drawdowns.sort()

    def _percentile(arr, p):
        idx = int(len(arr) * p / 100)
        idx = min(idx, len(arr) - 1)
        return arr[idx]

    # Equity distribution for histogram
    n_bins = 20
    min_bal = min(final_balances)
    max_bal = max(final_balances)
    bin_width = (max_bal - min_bal) / n_bins if max_bal > min_bal else 1
    histogram = []
    for i in range(n_bins):
        lo = min_bal + i * bin_width
        hi = lo + bin_width
        count = len([b for b in final_balances if lo <= b < hi])
        histogram.append({
            "bin_start": round(lo, 2),
            "bin_end": round(hi, 2),
            "count": count,
            "pct": round(count / n_simulations * 100, 1),
        })

    return {
        "n_simulations": n_simulations,
        "n_trades_per_sim": n_trades,
        "initial_balance": initial_balance,
        "input_trades": len(trade_pnls),
        "final_balance": {
            "p5": _percentile(final_balances, 5),
            "p10": _percentile(final_balances, 10),
            "p25": _percentile(final_balances, 25),
            "p50": _percentile(final_balances, 50),
            "p75": _percentile(final_balances, 75),
            "p90": _percentile(final_balances, 90),
            "p95": _percentile(final_balances, 95),
            "mean": round(statistics.mean(final_balances), 2),
            "std": round(statistics.stdev(final_balances), 2) if len(final_balances) > 1 else 0,
            "min": min(final_balances),
            "max": max(final_balances),
        },
        "max_drawdown_pct": {
            "p5": _percentile(max_drawdowns, 5),
            "p50": _percentile(max_drawdowns, 50),
            "p95": _percentile(max_drawdowns, 95),
            "mean": round(statistics.mean(max_drawdowns), 2),
        },
        "risk_of_ruin_pct": round(ruin_count / n_simulations * 100, 2),
        "risk_of_50pct_loss": round(ruin_50_count / n_simulations * 100, 2),
        "histogram": histogram,
    }


__all__ = ["optimize_strategy", "walk_forward", "monte_carlo"]
