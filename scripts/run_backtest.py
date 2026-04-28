"""CLI runner for the deterministic backtest engine.

Usage examples:
    # Synthetic uptrend, always-long signal
    python scripts/run_backtest.py \\
        --signal-spec '{"kind": "always_long"}' \\
        --bars-from-csv data/eurusd_m15.csv \\
        --initial-balance 1000 --warmup-bars 50

    # Inline OHLCV from a JSON file
    python scripts/run_backtest.py \\
        --signal-spec '{"kind": "atr_threshold", "atr_pct_min": 0.001}' \\
        --bars-from-json data/eurusd_m15.json

CSV format: comma-separated with header row including
`time,open,high,low,close,volume,spread`. `time` may be ISO-8601 or epoch.
"""
from __future__ import annotations

import argparse
import csv
import json
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic backtest.")
    parser.add_argument("--bars-from-csv", type=Path)
    parser.add_argument("--bars-from-json", type=Path)
    parser.add_argument("--signal-spec", default='{"kind": "always_flat"}',
                        help="JSON-encoded signal spec")
    parser.add_argument("--initial-balance", type=float, default=800.0)
    parser.add_argument("--risk-per-trade-pct", type=float, default=1.0)
    parser.add_argument("--sl-atr-mult", type=float, default=1.5)
    parser.add_argument("--tp-atr-mult", type=float, default=2.5)
    parser.add_argument("--warmup-bars", type=int, default=50)
    parser.add_argument("--max-open-positions", type=int, default=1)
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--out-json", type=Path, default=None,
                        help="If set, write the full result (with trades) here")
    args = parser.parse_args()

    if not args.bars_from_csv and not args.bars_from_json:
        print("ERROR: provide --bars-from-csv or --bars-from-json", file=sys.stderr)
        return 2

    if args.bars_from_csv:
        ohlcv = _load_csv(args.bars_from_csv)
    else:
        ohlcv = _load_json(args.bars_from_json)
    print(f"Loaded {len(ohlcv)} bars", file=sys.stderr)

    _add_lib_to_path()
    from bot_lib.backtest.engine import run_backtest  # noqa: E402

    config = {
        "initial_balance": args.initial_balance,
        "risk_per_trade_pct": args.risk_per_trade_pct,
        "sl_atr_mult": args.sl_atr_mult,
        "tp_atr_mult": args.tp_atr_mult,
        "warmup_bars": args.warmup_bars,
        "max_open_positions": args.max_open_positions,
        "min_score": args.min_score,
    }
    spec = json.loads(args.signal_spec)
    signal_fn = _signal_fn_from_spec(spec)

    result = run_backtest(ohlcv=ohlcv, signal_fn=signal_fn, config=config)

    # Print metrics summary to stdout
    if result.get("ok"):
        m = result["metrics"]
        print("--- BACKTEST RESULT ---")
        print(f"  Bars              : {result['total_bars']}")
        print(f"  Trades            : {m['trades']} (W:{m['wins']} L:{m['losses']})")
        print(f"  Win rate          : {m['win_rate'] * 100:.2f}%")
        print(f"  Total PnL         : {m['total_pnl']:+.2f}")
        print(f"  Expectancy        : {m['expectancy']:+.4f}")
        print(f"  Profit factor     : {m['profit_factor']:.2f}")
        print(f"  Max drawdown pct  : {m['max_drawdown_pct']:.2f}%")
        print(f"  Sharpe            : {m['sharpe']:.4f}")
        print(f"  Ending balance    : {m['ending_balance']:.2f}")
    else:
        print(f"--- BACKTEST FAILED: {result.get('reason')} ---")
        print(result.get("detail", ""))

    if args.out_json:
        args.out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(f"Wrote full result to {args.out_json}", file=sys.stderr)

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
