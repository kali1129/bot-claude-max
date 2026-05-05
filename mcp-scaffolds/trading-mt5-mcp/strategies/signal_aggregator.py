"""Signal Aggregator — meta-strategy.

Idea: the 4 base strategies (trend_rider, mean_reverter, breakout_hunter,
score_v3) are GOOD at picking entries but BAD at managing exits — average
loss > average win and TP rarely hits before SL. The aggregator inverts
that: it reuses their entry signals but replaces the exit logic with:

  - NO real SL on the broker (a wide protective SL is placed as a crash
    safety-net, but the soft-stop in auto_trader.py is what closes losers).
  - TP = +1% of equity_at_entry, computed in price terms once we know lot
    size. Most signals are good enough that price eventually visits a +1%
    profit if given time without being stopped out.
  - One position at a time, globally — the auto_trader blocks all new
    entries until the current aggregator position closes.

This file only PRODUCES the signal. The aggregator-specific guards (single
position, no-SL, soft-stop) live in auto_trader.py + aggregator_state.py.

Marker: every signal carries `extra.aggregator = True` so auto_trader can
route it through the aggregator code path.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from .base import Signal, Strategy
from .breakout_hunter import BreakoutHunter
from .mean_reverter import MeanReverter
from .score_v3 import ScoreV3
from .trend_rider import TrendRider

log = logging.getLogger("strategies.signal_aggregator")

# Backstop SL distance as fraction of price. The soft-stop in auto_trader is
# the real risk control; this only protects against bot crash + broker
# disconnect. Set wide enough that no normal market move triggers it but
# not so wide the broker rejects it.
_BACKSTOP_SL_PCT = {
    "default": 0.05,   # 5% adverse move → forex
    "crypto":  0.20,   # 20% adverse move → BTCUSD/ETHUSD daily ATR can be 5%+
}
_CRYPTO_SYMBOLS = {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT", "BTCEUR"}


def _backstop_sl_pct(symbol: str) -> float:
    return _BACKSTOP_SL_PCT["crypto"] if symbol.upper() in _CRYPTO_SYMBOLS \
        else _BACKSTOP_SL_PCT["default"]


class SignalAggregator(Strategy):
    id = "signal_aggregator"
    name = "Signal Aggregator (no-SL hold-to-TP)"
    description = (
        "Toma la mejor señal de las otras estrategias, no coloca SL real, "
        "apunta a +1% del capital. Cierra solo por TP o por soft-stop "
        "(drawdown del capital al entrar) según el perfil seleccionado."
    )
    strategy_type = "meta"
    color = "purple"

    theoretical_wr = 0.0           # to be measured by backtest
    theoretical_rr = 0.0
    theoretical_expectancy = 0.0

    # Internal floor — kept very low so the aggregator just emits whatever
    # the sub-strategies produce. The REAL min_score gate is applied by
    # auto_trader.py from strategy_config.json (live) or by the backtest
    # caller (offline). Filtering twice masked all signals in early tests.
    min_score = 0
    sl_atr_mult = 0.0              # informational only
    tp_atr_mult = 0.0

    # Symbols & hours: union of sub-strategies' preferences. We let the
    # sub-strategies do their own filtering inside propose().
    preferred_symbols = None
    blocked_symbols = frozenset()
    trading_hours = []             # 24/7 (each sub-strategy enforces its own)
    schedule_desc = "Sigue ventanas de las sub-estrategias"

    def __init__(self):
        self._subs: List[Strategy] = [
            TrendRider(),
            MeanReverter(),
            BreakoutHunter(),
            ScoreV3(),
        ]

    def propose(self, symbol, tick, bars_m15, bars_h4, bars_d1) -> List[Signal]:
        if not tick or tick.get("ok") is False:
            return []

        # Aggregator-level allowlist. The 60-day backtest only validated
        # EURUSD (conservative) and GBPUSD (aggressive) as profitable; any
        # other symbol is rejected here. Override via strategy_config.json
        # → aggregator.allowed_symbols.
        try:
            import aggregator_state  # local import to avoid circular at boot
            if not aggregator_state.is_symbol_allowed(symbol):
                return []
        except Exception:  # noqa: BLE001
            # If state lookup fails, default to a hard-coded allowlist so
            # we NEVER trade unvalidated symbols by accident.
            if symbol.upper() not in ("EURUSD", "GBPUSD"):
                return []

        # Collect signals from all sub-strategies that allow this symbol.
        # We deliberately DO NOT filter by trading_hours here — the
        # aggregator is meant to opportunistically reuse any high-score
        # signal regardless of the sub-strategy's preferred session.
        # If a signal scores well outside its native window, the score
        # itself reflects that quality (and the soft-stop is the safety
        # net). Skipping the hour filter also keeps backtest results
        # bar-time-correct (the live wall-clock would otherwise leak in).
        candidates = []
        for sub in self._subs:
            sym_ok, _ = sub.is_symbol_allowed(symbol)
            if not sym_ok:
                continue
            try:
                sigs = sub.propose(symbol, tick, bars_m15, bars_h4, bars_d1)
            except Exception as exc:  # noqa: BLE001
                log.debug("sub %s failed for %s: %s", sub.id, symbol, exc)
                continue
            for s in sigs:
                candidates.append((sub.id, s))

        if not candidates:
            return []

        # Pick the highest score. Tie-break: prefer trend_rider > breakout >
        # score_v3 > mean_reverter (matches risk profile preference).
        priority = {"trend_rider": 0, "breakout_hunter": 1,
                    "score_v3": 2, "mean_reverter": 3}
        candidates.sort(key=lambda x: (-x[1].score, priority.get(x[0], 99)))
        source_id, best = candidates[0]
        # No internal min_score filter — the caller (auto_trader / backtest)
        # decides the gate. The aggregator just publishes the best signal.

        # === Override SL: backstop only ===
        # Place a wide SL that satisfies broker requirements but is far
        # enough that intraday noise won't hit it. The real exit logic
        # is the soft-stop in auto_trader.
        sl_pct = _backstop_sl_pct(symbol)
        if best.side == "buy":
            backstop_sl = best.entry * (1.0 - sl_pct)
        else:
            backstop_sl = best.entry * (1.0 + sl_pct)

        # === Override TP: placeholder ===
        # The real TP price level depends on lot size (which auto_trader
        # decides). We pass a sentinel value here that auto_trader will
        # OVERRIDE post-sizing. The placeholder still has to satisfy the
        # SL_TP_SIDE guard (correct side of entry). We use a conservative
        # 0.5% favorable move; auto_trader recomputes before placing.
        if best.side == "buy":
            placeholder_tp = best.entry * 1.005
        else:
            placeholder_tp = best.entry * 0.995

        new_signal = Signal(
            symbol=symbol,
            side=best.side,
            entry=best.entry,
            sl=round(backstop_sl, 5),
            tp=round(placeholder_tp, 5),
            atr=best.atr,
            score=best.score,
            rec="TAKE" if best.score >= self.min_score else "WAIT",
            breakdown=best.breakdown,
            strategy_id=self.id,
            extra={
                "aggregator": True,
                "source_strategy": source_id,
                "source_score": best.score,
                "source_breakdown": dict(best.breakdown or {}),
                "backstop_sl_pct": sl_pct,
                "placeholder_tp": True,   # auto_trader will recompute
            },
        )
        return [new_signal]

    def hard_filter(self, signal, tick):
        # Defer to base — the sub-strategies already filtered their own
        # hours/symbols.
        return super().hard_filter(signal, tick)
