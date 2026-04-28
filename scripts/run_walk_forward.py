"""Walk-forward validation runner.

Splits the OHLCV series into N rolling windows and runs `run_backtest`
on each. Reports per-window metrics + a stability summary (variance of
expectancy, win rate, profit factor across windows).

Walk-forward is the cheapest defense against overfitting: a strategy
that wins consistently across non-overlapping in-sample/out-of-sample
windows is more likely to generalize than one that only wins on the full
history.

Usage:
    python scripts/run_walk_forward.py \\
        --bars-from-csv data/eurusd_m15.csv \\
        --signal-spec '{"kind": "atr_threshold", "atr_pct_min": 0.001}' \\
        --windows 5 --warmup-bars 50 \\
        --out-json reports/walk_forward.json
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path


def _add_lib_to_path() -> None:
    here = Path(__file__).resolve().parent
    repo = here.parent
    backend = repo / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))


def _load_csv(path: Path) -> list[dict]:
    bars: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            bars.append({
                "time": row.get("time") or row.get("timestamp") or row.get("date"),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row.get("volume", 0.0)),
                "spread": float(row.get("spread", 0.0)),
            })
    return bars


def _load_json(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def _signal_fn_from_spec(spec: dict):
    kind = str(spec.get("kind", "always_flat")).lower()
    if kind == "always_long":
        def _fn(ohlcv):
            if len(ohlcv) < 2:
                return {"direction": "FLAT", "atr": 0.0}
            last_close = float(ohlcv[-1].get("close", 0.0))
            return {"direction": "LONG", "atr": last_close * 0.005, "score": 1.0}
        return _fn
    if kind == "atr_threshold":
        atr_pct_min = float(spec.get("atr_pct_min", 0.001))
        def _fn(ohlcv):
            if len(ohlcv) < 2:
                return {"direction": "FLAT", "atr": 0.0}
            last_close = float(ohlcv[-1].get("close", 0.0))
            atr = last_close * 0.005
            atr_pct = (atr / last_close) if last_close else 0.0
            if atr_pct < atr_pct_min:
                return {"direction": "FLAT", "atr": 0.0}
            return {"direction": "LONG", "atr": atr, "score": 1.0}
        return _fn
    def _flat(ohlcv):
        return {"direction": "FLAT", "atr": 0.0}
    return _flat


def split_windows(bars: list[dict], n: int, *, overlap: int = 0) -> list[list[dict]]:
    """Slice bars into N contiguous (or overlapping) windows."""
    if n < 1:
        raise ValueError("n must be >= 1")
    size = len(bars) // n
    if size < 2:
        raise ValueError(f"Cannot split {len(bars)} bars into {n} non-trivial windows")
    out: list[list[dict]] = []
    for i in range(n):
        start = i * size
        end = start + size + overlap
        end = min(end, len(bars))
        out.append(bars[start:end])
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward backtest.")
    parser.add_argument("--bars-from-csv", type=Path)
    parser.add_argument("--bars-from-json", type=Path)
    parser.add_argument("--signal-spec", default='{"kind": "always_flat"}')
    parser.add_argument("--windows", type=int, default=5)
    parser.add_argument("--initial-balance", type=float, default=800.0)
    parser.add_argument("--warmup-bars", type=int, default=30)
    parser.add_argument("--sl-atr-mult", type=float, default=1.5)
    parser.add_argument("--tp-atr-mult", type=float, default=2.5)
    parser.add_argument("--out-json", type=Path, default=None)
    args = parser.parse_args()

    if not args.bars_from_csv and not args.bars_from_json:
        print("ERROR: provide --bars-from-csv or --bars-from-json", file=sys.stderr)
        return 2

    if args.bars_from_csv:
        all_bars = _load_csv(args.bars_from_csv)
    else:
        all_bars = _load_json(args.bars_from_json)

    print(f"Total bars: {len(all_bars)}; windows: {args.windows}", file=sys.stderr)

    _add_lib_to_path()
    from bot_lib.backtest.engine import run_backtest  # noqa: E402

    spec = json.loads(args.signal_spec)
    signal_fn = _signal_fn_from_spec(spec)
    config = {
        "initial_balance": args.initial_balance,
        "warmup_bars": args.warmup_bars,
        "sl_atr_mult": args.sl_atr_mult,
        "tp_atr_mult": args.tp_atr_mult,
    }

    windows = split_windows(all_bars, args.windows)
    per_window: list[dict] = []
    for idx, win in enumerate(windows):
        result = run_backtest(ohlcv=win, signal_fn=signal_fn, config=config)
        if not result.get("ok"):
            per_window.append({
                "window": idx, "ok": False, "reason": result.get("reason"),
                "detail": result.get("detail"),
            })
            continue
        m = result["metrics"]
        per_window.append({
            "window": idx,
            "ok": True,
            "bars": len(win),
            "trades": m["trades"],
            "win_rate": m["win_rate"],
            "total_pnl": m["total_pnl"],
            "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "sharpe": m["sharpe"],
            "ending_balance": m["ending_balance"],
        })

    successful = [w for w in per_window if w.get("ok") and w.get("trades", 0) > 0]
    summary: dict = {"successful_windows": len(successful), "total_windows": len(windows)}
    if successful:
        for key in ("win_rate", "expectancy", "profit_factor", "max_drawdown_pct", "sharpe"):
            values = [w[key] for w in successful]
            summary[f"{key}_mean"] = round(statistics.mean(values), 4)
            summary[f"{key}_stdev"] = (
                round(statistics.stdev(values), 4) if len(values) > 1 else 0.0
            )

    print("--- WALK-FORWARD RESULT ---")
    for w in per_window:
        if not w.get("ok"):
            print(f"  Window {w['window']}: FAILED ({w.get('reason')})")
            continue
        print(
            f"  Window {w['window']:>2}: trades={w['trades']:>4} "
            f"WR={w['win_rate'] * 100:>5.2f}% "
            f"PnL={w['total_pnl']:+8.2f} "
            f"PF={w['profit_factor']:>5.2f} "
            f"MaxDD={w['max_drawdown_pct']:>5.2f}%"
        )
    print("--- SUMMARY ---")
    for k, v in summary.items():
        print(f"  {k}: {v}")

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps({"per_window": per_window, "summary": summary}, indent=2),
            encoding="utf-8",
        )
        print(f"Wrote {args.out_json}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
