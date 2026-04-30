"""Shared invariants for the trading stack.

Edit ONLY when the user explicitly raises the rule in the dashboard's
Rules section *and* commits the change. Do not import this module and
shadow values locally — the whole point is one place to look.
"""
from dataclasses import dataclass

__version__ = "2.1.0"

MAX_RISK_PER_TRADE_PCT: float = 5.0
MAX_DAILY_LOSS_PCT:     float = 999.0  # 2026-04-28: stress test mode by
                                        # explicit user authorization. Was 3.
                                        # The guard remains, the cap is just
                                        # effectively unreachable. Bot can
                                        # blow the demo balance — that's the
                                        # point of the stress test.
MAX_OPEN_POSITIONS:     int   = 7    # 2026-04-30: multi-strategy 24h test. Was 2.
MIN_RR:                 float = 0.3    # 2026-04-30: lowered for 24h test. Was 2.0.
MAX_CONSECUTIVE_LOSSES: int   = 999    # 2026-04-28: stress test. Was 3.
                                        # Anti-tilt removed for "test how
                                        # far the strategy goes" run.
MAX_TRADES_PER_DAY:     int   = 999  # 2026-04-28: raised by explicit user
                                      # authorization in chat for the 24h
                                      # max-performance test. Original value
                                      # was 5 (anti-overtrading). The guard
                                      # in lib/guards.py is preserved as a
                                      # mechanism — only the cap is lifted
                                      # for this test window.
BLOCKED_HOUR_START_UTC: int   = 0    # 2026-04-30: disabled for 24h test   # blackout: 22:00–07:00 UTC (NY close → London open)
BLOCKED_HOUR_END_UTC:   int   = 0    # 2026-04-30: disabled for 24h test


@dataclass(frozen=True)
class RuleSnapshot:
    """Immutable snapshot of all rule values for logging/auditing."""
    version: str
    max_risk_per_trade_pct: float
    max_daily_loss_pct: float
    max_open_positions: int
    min_rr: float
    max_trades_per_day: int
    max_consecutive_losses: int
    blocked_hours: tuple


def snapshot() -> RuleSnapshot:
    return RuleSnapshot(
        version=__version__,
        max_risk_per_trade_pct=MAX_RISK_PER_TRADE_PCT,
        max_daily_loss_pct=MAX_DAILY_LOSS_PCT,
        max_open_positions=MAX_OPEN_POSITIONS,
        min_rr=MIN_RR,
        max_trades_per_day=MAX_TRADES_PER_DAY,
        max_consecutive_losses=MAX_CONSECUTIVE_LOSSES,
        blocked_hours=(BLOCKED_HOUR_START_UTC, BLOCKED_HOUR_END_UTC),
    )


def is_blocked_hour(utc_hour: int) -> bool:
    """Wrap-around aware. If start == end → no blackout at all."""
    if BLOCKED_HOUR_START_UTC == BLOCKED_HOUR_END_UTC:
        return False
    if BLOCKED_HOUR_START_UTC <= BLOCKED_HOUR_END_UTC:
        return BLOCKED_HOUR_START_UTC <= utc_hour < BLOCKED_HOUR_END_UTC
    return utc_hour >= BLOCKED_HOUR_START_UTC or utc_hour < BLOCKED_HOUR_END_UTC


PRE_BLACKOUT_BUFFER_MIN = 30  # refuse new entries within 30 min of blackout


def minutes_until_blackout(utc_hour: int, utc_minute: int) -> int:
    """How many minutes until BLOCKED_HOUR_START_UTC. Returns a large
    sentinel (9999) if start == end (no blackout configured)."""
    if BLOCKED_HOUR_START_UTC == BLOCKED_HOUR_END_UTC:
        return 9999
    now_min = utc_hour * 60 + utc_minute
    start_min = BLOCKED_HOUR_START_UTC * 60
    delta = (start_min - now_min) % (24 * 60)
    return int(delta)


def is_pre_blackout(utc_hour: int, utc_minute: int) -> bool:
    """True iff we're inside the pre-blackout buffer (about to enter blackout)."""
    if BLOCKED_HOUR_START_UTC == BLOCKED_HOUR_END_UTC:
        return False
    return 0 < minutes_until_blackout(utc_hour, utc_minute) <= PRE_BLACKOUT_BUFFER_MIN


def rr(entry: float, sl: float, tp: float) -> float:
    """Reward-to-risk ratio. Positive number; 0 if invalid geometry."""
    risk = abs(entry - sl)
    if risk == 0:
        return 0.0
    reward = abs(tp - entry)
    return reward / risk


def passes_rr(entry: float, sl: float, tp: float, min_rr: float = MIN_RR) -> bool:
    return rr(entry, sl, tp) >= min_rr


def max_risk_dollars(balance: float, risk_pct=None) -> float:
    pct = risk_pct if risk_pct is not None else MAX_RISK_PER_TRADE_PCT
    if pct > MAX_RISK_PER_TRADE_PCT:
        pct = MAX_RISK_PER_TRADE_PCT
    return round(balance * pct / 100.0, 2)
