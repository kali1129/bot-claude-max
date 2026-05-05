"""Backtest harness — comparativa current strategies vs signal_aggregator.

Pulls historical M15/H4/D1 bars from MT5 and simulates BOTH the existing
"all strategies, score gate, ATR SL/TP" engine and the new aggregator on
the same data, side by side.

Usage (from inside the trading-mt5-mcp folder, with Wine + Python + MT5
available on the PATH or via the auto_trader virtualenv):

    python tests/backtest_aggregator.py \\
        --symbols EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD \\
        --days 60 \\
        --equity 100 \\
        --profile conservative \\
        --report report.json

Output:
    Per-strategy summary (WR, PnL, MaxDD, Profit Factor) printed to stdout
    plus a JSON dump of every simulated trade for offline analysis.

Notes / caveats:
  - This is a SIMPLIFIED simulator. It runs propose() on each closed M15
    bar; signals are evaluated as if entered on the bar's close price.
    Spread is approximated as a fixed pct of price (configurable).
  - SL/TP hits are detected by walking forward bar-by-bar, comparing
    high/low against levels. Intra-bar tie-break: SL takes precedence
    over TP (worst-case for the strategy — avoids overstating wins).
  - The aggregator's soft-stop is checked at every M15 bar close using the
    bar's worst adverse excursion as the candidate floating PnL.
  - The current-engine sim ignores the kelly/expectancy/regime filters in
    auto_trader; it just takes the highest-scoring proposal that passes
    min_score, like the live bot does.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# === Bootstrap path (mirror of auto_trader.py) ============================
HERE = Path(__file__).resolve().parent
BOT_ROOT = HERE.parent
SCAFFOLDS = BOT_ROOT.parent
sys.path.insert(0, str(BOT_ROOT))
sys.path.insert(0, str(SCAFFOLDS / "_shared"))

import importlib.util as _ilu  # noqa: E402

_ANALYSIS_DIR = SCAFFOLDS / "analysis-mcp" / "lib"
_pkg = _ilu.module_from_spec(
    _ilu.spec_from_loader("analysis_lib", loader=None, is_package=True))
_pkg.__path__ = [str(_ANALYSIS_DIR)]
sys.modules["analysis_lib"] = _pkg


def _load(name, path):
    spec = _ilu.spec_from_file_location(name, path)
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_load("analysis_lib.indicators", _ANALYSIS_DIR / "indicators.py")
_load("analysis_lib.structure", _ANALYSIS_DIR / "structure.py")

import strategies as strat_engine  # noqa: E402
from strategies.base import Signal  # noqa: F401, E402

try:
    import MetaTrader5 as mt5  # noqa: E402
    HAS_MT5 = True
except ImportError:
    HAS_MT5 = False

# Fixed spread approximation (decimal, fraction of price). The live bot
# already applies a spread filter; we use a conservative 0.02% here.
SPREAD_PCT = 0.0002


# === Data layer ===========================================================

def fetch_bars(symbol: str, timeframe: int, count: int) -> List[dict]:
    """Pull historical bars from MT5 in the same dict shape strategies expect."""
    if not HAS_MT5:
        raise RuntimeError("MetaTrader5 not available — backtest needs MT5 terminal")
    mt5.symbol_select(symbol, True)
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None or len(rates) == 0:
        return []
    out = []
    for r in rates:
        out.append({
            "time": datetime.fromtimestamp(int(r["time"]), tz=timezone.utc).isoformat(),
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": int(r["tick_volume"]),
        })
    return out


def symbol_meta(symbol: str) -> dict:
    if not HAS_MT5:
        # sensible defaults for forex
        return {"tick_size": 0.00001, "tick_value": 1.0,
                "volume_step": 0.01, "volume_min": 0.01,
                "contract_size": 100000.0}
    mt5.symbol_select(symbol, True)
    info = mt5.symbol_info(symbol)
    if info is None:
        return {"tick_size": 0.00001, "tick_value": 1.0,
                "volume_step": 0.01, "volume_min": 0.01,
                "contract_size": 100000.0}
    return {
        "tick_size":     float(info.trade_tick_size or info.point or 0.00001),
        "tick_value":    float(info.trade_tick_value or 1.0),
        "volume_step":   float(info.volume_step or 0.01),
        "volume_min":    float(info.volume_min or 0.01),
        "contract_size": float(info.trade_contract_size or 100000.0),
    }


# === Simulator ============================================================

def _pnl_usd(side: str, entry: float, exit_px: float, lots: float,
             tick_size: float, tick_value: float) -> float:
    """Compute closed-trade PnL using the broker's tick math."""
    if side == "buy":
        diff = exit_px - entry
    else:
        diff = entry - exit_px
    if tick_size <= 0:
        return 0.0
    return lots * (diff / tick_size) * tick_value


def _sl_tp_hit(side: str, entry: float, sl: float, tp: float,
               bar: dict) -> Optional[Tuple[str, float]]:
    """Has SL or TP been touched in this bar? Returns (event, exit_price) or None."""
    high, low = float(bar["high"]), float(bar["low"])
    if side == "buy":
        sl_hit = low <= sl if sl > 0 else False
        tp_hit = high >= tp if tp > 0 else False
    else:
        sl_hit = high >= sl if sl > 0 else False
        tp_hit = low <= tp if tp > 0 else False
    if sl_hit and tp_hit:
        # Worst-case tie-break — assume SL hits first.
        return ("SL", sl)
    if sl_hit:
        return ("SL", sl)
    if tp_hit:
        return ("TP", tp)
    return None


def _adverse_pnl_during_bar(side: str, entry: float, lots: float, bar: dict,
                             tick_size: float, tick_value: float) -> float:
    """Worst floating PnL the position could have shown during this bar."""
    high, low = float(bar["high"]), float(bar["low"])
    worst_price = low if side == "buy" else high
    return _pnl_usd(side, entry, worst_price, lots, tick_size, tick_value)


def _calc_lots(balance: float, risk_pct: float, entry: float, sl: float,
               meta: dict) -> float:
    """Mirror of risk_sizing.calc_position_size — returns lots rounded down to step."""
    if entry <= 0 or sl <= 0:
        return 0.0
    sl_dist = abs(entry - sl)
    if sl_dist <= 0:
        return 0.0
    risk_usd = balance * (risk_pct / 100.0)
    tv, ts = meta["tick_value"], meta["tick_size"]
    if tv <= 0 or ts <= 0:
        return 0.0
    lots_raw = risk_usd / ((sl_dist / ts) * tv)
    step = meta["volume_step"]
    lots_floor = int(lots_raw / step) * step
    return max(meta["volume_min"], round(lots_floor, 4)) if lots_floor >= meta["volume_min"] else 0.0


def _calc_lots_aggregator(balance: float, entry: float, sl_backstop: float,
                           meta: dict, max_drawdown_pct: float,
                           target_pct: float) -> float:
    """For aggregator: lot size such that the target_pct of equity is
    REACHABLE in a sensible price move (not 0.0001 of price = unreachable).

    Strategy:
      - Pick the smallest lot size where TP at target_pct equity sits at
        a price distance of at least 0.05% of entry (for forex, ~5 pips).
      - Cap at lot size where a max_drawdown_pct loss = a price distance
        no greater than the backstop SL distance (so backstop can't be
        triggered before the soft-stop fires).
      - On tiny accounts the volume_min floor wins → minimum exposure.
    """
    if entry <= 0:
        return 0.0
    sl_dist = abs(entry - sl_backstop)
    if sl_dist <= 0:
        return 0.0
    tv, ts = meta["tick_value"], meta["tick_size"]
    if tv <= 0 or ts <= 0:
        return 0.0
    step = meta["volume_step"]
    vmin = meta["volume_min"]

    # Cap by backstop: lots * (sl_dist/ts) * tv <= balance * max_drawdown_pct * 0.95
    # (i.e. backstop loss < soft-stop loss with 5% safety margin).
    backstop_loss_cap = balance * max_drawdown_pct * 0.95
    lots_max_by_backstop = backstop_loss_cap / ((sl_dist / ts) * tv)

    # Cap by reachable TP: ensure TP price distance >= 0.05% of entry, so
    # the broker actually has a chance to fill before the bar's noise.
    min_tp_dist = entry * 0.0005
    target_usd = balance * target_pct
    lots_max_by_tp_distance = target_usd * ts / (min_tp_dist * tv) if min_tp_dist > 0 else 0.0

    # The aggregator wants to deploy capital — pick the more permissive cap
    # so we actually trade. But never below vmin and never above broker max.
    lots_raw = max(lots_max_by_backstop, lots_max_by_tp_distance)
    lots_floor = int(lots_raw / step) * step

    if lots_floor < vmin:
        # Cuenta demasiado chica para el backstop ideal — usamos lot mínimo
        # y aceptamos que el backstop quede más cerca del soft-stop.
        return vmin
    return round(min(lots_floor, meta.get("volume_max", 100.0)), 4)


def simulate(
    *,
    symbol: str,
    bars_m15: List[dict],
    bars_h4: List[dict],
    bars_d1: List[dict],
    meta: dict,
    starting_equity: float,
    mode: str,                   # "current" or "aggregator"
    profile: str = "conservative",
    risk_pct: float = 1.0,
    target_pct: float = 0.01,
    min_score_current: int = 70,
    min_score_aggregator: int = 50,
    bar_step: int = 4,           # propose() every N M15 bars (4 = hourly)
) -> dict:
    """Walk forward through bars_m15, simulating one strategy at a time.

    The simulator carries ONE open position at most (matches both the live
    bot's per-symbol cap and the aggregator's global single-position rule).
    Multi-symbol comparisons are computed at a higher layer by combining
    per-symbol trade lists.
    """
    if mode not in ("current", "aggregator"):
        raise ValueError(f"unknown mode: {mode}")

    # Map M15 bar timestamp → most recent H4 / D1 bar (for HTF context).
    h4_iso = [b["time"] for b in bars_h4]
    d1_iso = [b["time"] for b in bars_d1]

    def _slice_until(bars: List[dict], iso_ts: List[str], cutoff_iso: str) -> List[dict]:
        idx = 0
        for i, t in enumerate(iso_ts):
            if t > cutoff_iso:
                break
            idx = i + 1
        return bars[:idx]

    soft_stop_pct = {
        "conservative": 0.10, "normal": 0.25, "aggressive": 0.50,
    }.get(profile, 0.10)

    open_pos: Optional[dict] = None
    trades: List[dict] = []
    equity_curve: List[float] = [starting_equity]
    equity = starting_equity
    peak = equity

    # The simulator needs at least 200 M15 bars of warmup before the first
    # propose call (strategies require it). Start at index 200.
    if len(bars_m15) < 220:
        return {"trades": [], "equity_curve": [starting_equity],
                "starting_equity": starting_equity, "ending_equity": starting_equity,
                "reason": "INSUFFICIENT_BARS"}

    aggregator_strat = strat_engine.REGISTRY["signal_aggregator"]
    other_strats = [s for sid, s in strat_engine.REGISTRY.items()
                    if sid != "signal_aggregator"]

    last_propose_idx = -10**9   # rate-limit propose() to bar_step

    for i in range(200, len(bars_m15) - 1):
        cur_bar = bars_m15[i]
        next_bar = bars_m15[i + 1]
        cutoff = cur_bar["time"]
        m15_window = bars_m15[: i + 1]
        h4_window = _slice_until(bars_h4, h4_iso, cutoff)
        d1_window = _slice_until(bars_d1, d1_iso, cutoff)

        close = float(cur_bar["close"])
        spread = close * SPREAD_PCT
        synthetic_tick = {
            "ok": True,
            "ask": close + spread / 2,
            "bid": close - spread / 2,
        }

        # === Manage open position (if any) ===
        if open_pos is not None:
            pos_bar = bars_m15[i]   # the bar we're now evaluating

            # Soft-stop check (aggregator only) — done BEFORE TP/SL hit so a
            # severe adverse spike that also touches TP is closed at soft-stop.
            if mode == "aggregator":
                worst_pnl = _adverse_pnl_during_bar(
                    open_pos["side"], open_pos["entry"], open_pos["lots"],
                    pos_bar, meta["tick_size"], meta["tick_value"])
                threshold = -open_pos["equity_at_entry"] * soft_stop_pct
                if worst_pnl <= threshold:
                    # Soft stop fires — exit at the threshold price (interp).
                    exit_px = open_pos["entry"] + (
                        threshold / open_pos["lots"] * meta["tick_size"] / meta["tick_value"]
                    ) * (1 if open_pos["side"] == "buy" else -1)
                    pnl = threshold
                    equity += pnl
                    trades.append({**open_pos, "exit_time": cur_bar["time"],
                                   "exit_price": round(exit_px, 5),
                                   "pnl_usd": round(pnl, 2),
                                   "exit_reason": "SOFT_STOP",
                                   "duration_bars": i - open_pos["open_index"]})
                    open_pos = None
                    equity_curve.append(equity)
                    peak = max(peak, equity)
                    continue

            # SL/TP hit detection on THIS bar
            hit = _sl_tp_hit(open_pos["side"], open_pos["entry"],
                             open_pos["sl"], open_pos["tp"], pos_bar)
            if hit is not None:
                event, exit_px = hit
                pnl = _pnl_usd(open_pos["side"], open_pos["entry"], exit_px,
                                open_pos["lots"], meta["tick_size"],
                                meta["tick_value"])
                equity += pnl
                trades.append({**open_pos, "exit_time": cur_bar["time"],
                               "exit_price": round(exit_px, 5),
                               "pnl_usd": round(pnl, 2),
                               "exit_reason": event,
                               "duration_bars": i - open_pos["open_index"]})
                open_pos = None
                equity_curve.append(equity)
                peak = max(peak, equity)
                continue

            # Otherwise: position rolls forward, equity not updated until close.
            equity_curve.append(equity)
            continue

        # === No open position — try to enter ===
        # Rate-limit propose(): re-evaluating strategies every 15 min over
        # 60 days × 4 strategies × 200-bar EMAs is ~1.5min/symbol of pure
        # numpy. Sample every `bar_step` bars (4 = hourly) — doesn't hurt
        # accuracy because consecutive M15 bars produce nearly identical
        # signals.
        if i - last_propose_idx < bar_step:
            equity_curve.append(equity)
            continue
        last_propose_idx = i

        if mode == "aggregator":
            try:
                sigs = aggregator_strat.propose(symbol, synthetic_tick,
                                                  m15_window, h4_window, d1_window)
            except Exception:
                sigs = []
            sigs = [s for s in sigs if s.score >= min_score_aggregator]
        else:
            # Mirror the live bot: hard_filter (which enforces trading_hours)
            # is currently DISABLED in auto_trader.py — strategies propose
            # 24/7 and only score gates entry. We replicate that here to keep
            # the comparison apples-to-apples.
            sigs = []
            for sub in other_strats:
                sym_ok, _ = sub.is_symbol_allowed(symbol)
                if not sym_ok:
                    continue
                try:
                    sigs.extend(sub.propose(symbol, synthetic_tick,
                                              m15_window, h4_window, d1_window))
                except Exception:
                    pass
            sigs = [s for s in sigs if s.score >= min_score_current]
            sigs.sort(key=lambda s: -s.score)

        if not sigs:
            equity_curve.append(equity)
            continue

        sig = sigs[0]

        # Sizing
        if mode == "aggregator":
            lots = _calc_lots_aggregator(equity, sig.entry, sig.sl, meta,
                                            soft_stop_pct, target_pct)
            target_usd = equity * target_pct
            tv, ts = meta["tick_value"], meta["tick_size"]
            if lots > 0 and tv > 0:
                price_distance = (target_usd * ts) / (lots * tv)
            else:
                price_distance = 0.0
            if price_distance <= 0:
                equity_curve.append(equity)
                continue
            tp = sig.entry + price_distance if sig.side == "buy" \
                else sig.entry - price_distance
            sl = sig.sl  # backstop
        else:
            lots = _calc_lots(equity, risk_pct, sig.entry, sig.sl, meta)
            sl = sig.sl
            tp = sig.tp

        if lots <= 0:
            equity_curve.append(equity)
            continue

        open_pos = {
            "open_time": next_bar["time"],
            "open_index": i + 1,
            "symbol": symbol,
            "side": sig.side,
            "entry": float(next_bar["open"]),  # fill at next bar open
            "sl": float(sl),
            "tp": float(tp),
            "lots": lots,
            "score": sig.score,
            "strategy_id": sig.strategy_id,
            "source_strategy": (sig.extra or {}).get("source_strategy"),
            "equity_at_entry": equity,
        }
        equity_curve.append(equity)

    # Force-close any dangling position at the last bar's close (mark-to-market).
    if open_pos is not None:
        last_bar = bars_m15[-1]
        exit_px = float(last_bar["close"])
        pnl = _pnl_usd(open_pos["side"], open_pos["entry"], exit_px,
                        open_pos["lots"], meta["tick_size"], meta["tick_value"])
        equity += pnl
        trades.append({**open_pos, "exit_time": last_bar["time"],
                       "exit_price": exit_px, "pnl_usd": round(pnl, 2),
                       "exit_reason": "EOD_CLOSE",
                       "duration_bars": len(bars_m15) - 1 - open_pos["open_index"]})
        equity_curve.append(equity)

    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "starting_equity": starting_equity,
        "ending_equity": equity,
    }


def summarize(label: str, result: dict) -> dict:
    trades = result["trades"]
    n = len(trades)
    wins = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] < 0]
    pnl = sum(t["pnl_usd"] for t in trades)
    win_pnl = sum(t["pnl_usd"] for t in wins)
    loss_pnl = sum(t["pnl_usd"] for t in losses)
    wr = (len(wins) / n * 100) if n else 0
    avg_w = (win_pnl / len(wins)) if wins else 0
    avg_l = (loss_pnl / len(losses)) if losses else 0
    pf = (win_pnl / abs(loss_pnl)) if loss_pnl else float("inf") if win_pnl > 0 else 0
    eq = result["equity_curve"]
    peak, max_dd = eq[0], 0.0
    for v in eq:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    by_reason = defaultdict(int)
    for t in trades:
        by_reason[t["exit_reason"]] += 1
    return {
        "label": label,
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(wr, 1),
        "pnl_usd": round(pnl, 2),
        "avg_win": round(avg_w, 2),
        "avg_loss": round(avg_l, 2),
        "profit_factor": round(pf, 2) if pf != float("inf") else "inf",
        "starting_equity": round(result["starting_equity"], 2),
        "ending_equity": round(result["ending_equity"], 2),
        "max_drawdown": round(max_dd, 2),
        "exits_by_reason": dict(by_reason),
    }


def print_summary(s: dict) -> None:
    print(f"\n=== {s['label']} ===")
    print(f"Trades: {s['trades']}  ({s['wins']}W / {s['losses']}L)  WR={s['win_rate']}%")
    print(f"PnL: ${s['pnl_usd']:+.2f}   start ${s['starting_equity']} -> end ${s['ending_equity']}")
    print(f"Avg win ${s['avg_win']}  Avg loss ${s['avg_loss']}  PF={s['profit_factor']}")
    print(f"MaxDD: ${s['max_drawdown']:.2f}")
    print(f"Exits: {s['exits_by_reason']}")


# === Main =================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="EURUSD,GBPUSD,USDJPY,BTCUSD,ETHUSD")
    ap.add_argument("--days", type=int, default=60,
                    help="trailing days of M15 history to pull (default 60)")
    ap.add_argument("--equity", type=float, default=100.0)
    ap.add_argument("--profile", choices=["conservative", "normal", "aggressive"],
                    default="conservative",
                    help="default profile (used for symbols without a per-symbol override)")
    ap.add_argument("--symbol-profile", action="append", default=[],
                    metavar="SYMBOL=profile",
                    help="per-symbol profile override, repeatable. e.g. "
                         "--symbol-profile EURUSD=conservative --symbol-profile GBPUSD=aggressive")
    ap.add_argument("--target-pct", type=float, default=0.01)
    ap.add_argument("--min-score-current", type=int, default=70)
    ap.add_argument("--min-score-aggregator", type=int, default=50)
    ap.add_argument("--bar-step", type=int, default=4,
                    help="evaluate strategies every N M15 bars (default 4=1h)")
    ap.add_argument("--report", default=None,
                    help="path to dump full per-trade JSON report")
    args = ap.parse_args()

    if not HAS_MT5:
        print("ERROR: MetaTrader5 module not available.", file=sys.stderr)
        sys.exit(2)
    if not mt5.initialize():
        print(f"ERROR: mt5.initialize() failed: {mt5.last_error()}", file=sys.stderr)
        sys.exit(2)

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    bars_per_m15 = args.days * 24 * 4   # 96 M15 bars/day
    bars_per_h4 = args.days * 6
    bars_per_d1 = args.days

    # Parse per-symbol profile overrides
    symbol_profiles = {}
    for spec in args.symbol_profile:
        if "=" in spec:
            sym, prof = spec.split("=", 1)
            symbol_profiles[sym.strip().upper()] = prof.strip().lower()

    def _profile_for(sym: str) -> str:
        return symbol_profiles.get(sym.upper(), args.profile)

    # Cap per-symbol equity allocation if multiple symbols share one account.
    per_symbol_equity = args.equity / max(1, len(symbols))

    by_symbol: Dict[str, dict] = {}
    for sym in symbols:
        print(f"\n--- {sym} : pulling {bars_per_m15} M15 / {bars_per_h4} H4 / "
              f"{bars_per_d1} D1 bars ---", flush=True)
        bm15 = fetch_bars(sym, mt5.TIMEFRAME_M15, bars_per_m15)
        bh4 = fetch_bars(sym, mt5.TIMEFRAME_H4, bars_per_h4)
        bd1 = fetch_bars(sym, mt5.TIMEFRAME_D1, bars_per_d1)
        if len(bm15) < 220:
            print(f"  SKIP — only {len(bm15)} M15 bars available", flush=True)
            continue
        meta = symbol_meta(sym)
        print(f"  bars: M15={len(bm15)} H4={len(bh4)} D1={len(bd1)}", flush=True)
        print(f"  meta: {meta}", flush=True)

        sym_profile = _profile_for(sym)
        import time as _t
        _t0 = _t.time()
        print(f"  [{sym}] simulating CURRENT (profile={sym_profile})...", flush=True)
        cur = simulate(symbol=sym, bars_m15=bm15, bars_h4=bh4, bars_d1=bd1,
                       meta=meta, starting_equity=per_symbol_equity,
                       mode="current", profile=sym_profile,
                       target_pct=args.target_pct,
                       min_score_current=args.min_score_current,
                       min_score_aggregator=args.min_score_aggregator,
                       bar_step=args.bar_step)
        print(f"  [{sym}] CURRENT done in {_t.time()-_t0:.1f}s "
              f"({len(cur['trades'])} trades)", flush=True)
        _t0 = _t.time()
        print(f"  [{sym}] simulating AGGREGATOR (profile={sym_profile})...", flush=True)
        agg = simulate(symbol=sym, bars_m15=bm15, bars_h4=bh4, bars_d1=bd1,
                       meta=meta, starting_equity=per_symbol_equity,
                       mode="aggregator", profile=sym_profile,
                       target_pct=args.target_pct,
                       min_score_current=args.min_score_current,
                       min_score_aggregator=args.min_score_aggregator,
                       bar_step=args.bar_step)
        print(f"  [{sym}] AGGREGATOR done in {_t.time()-_t0:.1f}s "
              f"({len(agg['trades'])} trades)", flush=True)
        by_symbol[sym] = {
            "current": summarize(f"{sym} CURRENT", cur),
            "aggregator": summarize(f"{sym} AGGREGATOR ({args.profile})", agg),
            "current_trades": cur["trades"],
            "aggregator_trades": agg["trades"],
        }

    # === Print per-symbol + portfolio rollup ===
    cur_total = []
    agg_total = []
    cur_eq = args.equity
    agg_eq = args.equity
    print("\n\n========== PER-SYMBOL ==========")
    for sym, data in by_symbol.items():
        print_summary(data["current"])
        print_summary(data["aggregator"])
        cur_total.extend(data["current_trades"])
        agg_total.extend(data["aggregator_trades"])

    cur_pnl = sum(t["pnl_usd"] for t in cur_total)
    agg_pnl = sum(t["pnl_usd"] for t in agg_total)

    def _portfolio_summary(label, trades, start_eq):
        n = len(trades)
        wins = [t for t in trades if t["pnl_usd"] > 0]
        losses = [t for t in trades if t["pnl_usd"] < 0]
        pnl = sum(t["pnl_usd"] for t in trades)
        wp = sum(t["pnl_usd"] for t in wins)
        lp = sum(t["pnl_usd"] for t in losses)
        wr = (len(wins) / n * 100) if n else 0
        pf = (wp / abs(lp)) if lp else float("inf") if wp > 0 else 0
        return {
            "label": label, "trades": n, "wins": len(wins), "losses": len(losses),
            "win_rate": round(wr, 1), "pnl_usd": round(pnl, 2),
            "avg_win": round(wp / len(wins), 2) if wins else 0,
            "avg_loss": round(lp / len(losses), 2) if losses else 0,
            "profit_factor": round(pf, 2) if pf != float("inf") else "inf",
            "starting_equity": start_eq,
            "ending_equity": round(start_eq + pnl, 2),
        }

    print("\n\n========== PORTFOLIO ==========")
    cur_port = _portfolio_summary("CURRENT (all symbols pooled)",
                                    cur_total, args.equity)
    agg_port = _portfolio_summary(f"AGGREGATOR ({args.profile}, all pooled)",
                                    agg_total, args.equity)
    print(f"\n--- {cur_port['label']} ---")
    print(json.dumps(cur_port, indent=2))
    print(f"\n--- {agg_port['label']} ---")
    print(json.dumps(agg_port, indent=2))

    if args.report:
        Path(args.report).write_text(json.dumps({
            "args": vars(args),
            "by_symbol": {sym: {"current": d["current"],
                                  "aggregator": d["aggregator"]}
                            for sym, d in by_symbol.items()},
            "portfolio": {"current": cur_port, "aggregator": agg_port},
            "all_trades": {"current": cur_total, "aggregator": agg_total},
        }, indent=2, default=str), encoding="utf-8")
        print(f"\nReport written: {args.report}")

    mt5.shutdown()


if __name__ == "__main__":
    main()
