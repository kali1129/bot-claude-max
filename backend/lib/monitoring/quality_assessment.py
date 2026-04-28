"""Quality-assessment helpers for repeatable supervised-demo scoring.

Port of xm-mt5-trading-platform/src/monitoring/quality_assessment.py.
The legacy module was 181 LOC and is one of the smallest, cleanest files
in the legacy monitoring/ folder — a good "audit at a glance" tool.

The bot nuevo's discipline-score endpoint covers a subset of this idea
(rule-adherence). Quality assessment is broader: it scores categories
like 'data feed health', 'execution layer', 'news gate', etc., each with
multiple checks. Returns:
  - per-check rating: pass | partial | unknown | fail
  - per-category weighted score
  - overall rating + unattended-readiness verdict
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal


CheckStatus = Literal["pass", "partial", "unknown", "fail"]

STATUS_POINTS: dict[CheckStatus, float] = {
    "pass": 1.0,
    "partial": 0.65,
    "unknown": 0.4,
    "fail": 0.0,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def make_check(
    name: str,
    status: CheckStatus,
    evidence: str,
    *,
    recommendation: str | None = None,
    blocker: bool = False,
    weight: float = 1.0,
) -> dict[str, Any]:
    """Build one check record."""
    return {
        "name": name,
        "status": status,
        "evidence": evidence,
        "recommendation": recommendation,
        "blocker": blocker,
        "weight": weight,
    }


def score_category(name: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Score a list of checks into a category record.

    Score = weighted average of STATUS_POINTS (0..1). All weights default 1.0.
    """
    if not checks:
        return {
            "name": name,
            "score": 0.0,
            "status": "unknown",
            "blockers": 0,
            "checks": [],
        }
    total_weight = sum(float(c.get("weight", 1.0)) for c in checks)
    if total_weight <= 0:
        return {
            "name": name,
            "score": 0.0,
            "status": "unknown",
            "blockers": 0,
            "checks": list(checks),
        }
    weighted = sum(
        STATUS_POINTS.get(c["status"], 0.0) * float(c.get("weight", 1.0))
        for c in checks
    )
    score = weighted / total_weight

    if any(c.get("blocker") and c.get("status") in ("fail", "unknown") for c in checks):
        status = "blocker"
    elif score >= 0.85:
        status = "pass"
    elif score >= 0.6:
        status = "partial"
    elif score >= 0.4:
        status = "unknown"
    else:
        status = "fail"

    return {
        "name": name,
        "score": round(score, 4),
        "status": status,
        "blockers": sum(1 for c in checks if c.get("blocker") and c["status"] in ("fail", "unknown")),
        "checks": list(checks),
    }


def determine_overall_rating(categories: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate category scores into an overall rating."""
    if not categories:
        return {"score": 0.0, "rating": "unknown"}

    avg = sum(float(c["score"]) for c in categories) / len(categories)
    has_blockers = any(c.get("status") == "blocker" for c in categories)

    if has_blockers:
        rating = "blocker"
    elif avg >= 0.85:
        rating = "pass"
    elif avg >= 0.6:
        rating = "partial"
    elif avg >= 0.4:
        rating = "review"
    else:
        rating = "fail"

    return {
        "score": round(avg, 4),
        "rating": rating,
        "has_blockers": has_blockers,
        "categories_count": len(categories),
    }


def determine_unattended_readiness(
    categories: list[dict[str, Any]],
    overall: dict[str, Any],
    *,
    min_overall_score: float = 0.85,
) -> dict[str, Any]:
    """Decide whether the system is safe to run unattended.

    Conservative by default: any blocker → not ready, regardless of score.
    """
    has_blockers = bool(overall.get("has_blockers"))
    score = float(overall.get("score", 0.0))
    weak_categories = [c["name"] for c in categories if c.get("score", 0.0) < min_overall_score]

    ready = (not has_blockers) and (score >= min_overall_score)
    return {
        "ready": ready,
        "reason": (
            "BLOCKERS_PRESENT" if has_blockers
            else "SCORE_BELOW_MIN" if score < min_overall_score
            else "OK"
        ),
        "min_overall_score": min_overall_score,
        "weak_categories": weak_categories,
    }


def build_report(
    *,
    categories: list[dict[str, Any]],
    min_overall_score: float = 0.85,
) -> dict[str, Any]:
    """Convenience: run scoring + readiness + wrap into a single report."""
    overall = determine_overall_rating(categories)
    readiness = determine_unattended_readiness(
        categories, overall, min_overall_score=min_overall_score,
    )
    return {
        "ok": True,
        "generated_at_utc": utc_now().isoformat(),
        "overall": overall,
        "readiness": readiness,
        "categories": categories,
    }


__all__ = [
    "STATUS_POINTS",
    "make_check",
    "score_category",
    "determine_overall_rating",
    "determine_unattended_readiness",
    "build_report",
]
