"""Expectancy + win-rate from history of closed deals."""
from __future__ import annotations

from statistics import mean

from . import state_manager as sm


def expectancy(last_n: int = 30) -> dict:
    """Reads deals.jsonl and returns aggregate stats over the last N deals."""
    deals = sm.load_history()[-last_n:]
    if not deals:
        return {
            "n": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "avg_win_R": 0.0, "avg_loss_R": 0.0, "expectancy": 0.0,
            "verdict": "NO_DATA",
        }
    wins = [d for d in deals if d.get("profit", 0.0) > 0]
    losses = [d for d in deals if d.get("profit", 0.0) < 0]
    n = len(deals)
    wr = len(wins) / n
    avg_win_R = mean(d.get("r_multiple", 0.0) for d in wins) if wins else 0.0
    avg_loss_R = mean(d.get("r_multiple", 0.0) for d in losses) if losses else 0.0
    exp_R = wr * avg_win_R + (1 - wr) * avg_loss_R
    if exp_R > 0.30:
        verdict = "POSITIVE"
    elif exp_R > 0.0:
        verdict = "MARGINAL"
    else:
        verdict = "NEGATIVE"
    return {
        "n": n, "wins": len(wins), "losses": len(losses),
        "win_rate": round(wr * 100, 1),
        "avg_win_R": round(avg_win_R, 2),
        "avg_loss_R": round(avg_loss_R, 2),
        "expectancy": round(exp_R, 2),
        "verdict": verdict,
    }
