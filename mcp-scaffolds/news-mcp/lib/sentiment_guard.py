"""Sentiment and conflict checks for relevant headline sets.

Port of xm-mt5-trading-platform/src/news/sentiment_guard.py.

Adapted: ImpactLevel from `_shared.common.enums`, RankedHeadline from
the local relevance_ranker. No legacy imports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_SHARED_PARENT = _HERE.parent.parent  # mcp-scaffolds/
if str(_SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(_SHARED_PARENT))

from _shared.common.enums import ImpactLevel  # noqa: E402

from .relevance_ranker import RankedHeadline


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class SentimentGuardResult:
    """Conflict, freshness, and impact summary for one symbol."""

    source_count: int
    fresh_headlines: tuple[RankedHeadline, ...]
    stale_headlines: tuple[RankedHeadline, ...]
    conflicting: bool
    sentiment_state: str   # neutral | positive | negative | conflicting | stale
    highest_impact: ImpactLevel
    reasons: tuple[str, ...] = ()
    confidence_info: dict[str, object] = field(default_factory=dict)

    @property
    def stale_only(self) -> bool:
        return not self.fresh_headlines and bool(self.stale_headlines)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": True,
            "source_count": self.source_count,
            "fresh_count": len(self.fresh_headlines),
            "stale_count": len(self.stale_headlines),
            "fresh_headlines": [r.to_dict() for r in self.fresh_headlines],
            "stale_headlines": [r.to_dict() for r in self.stale_headlines],
            "conflicting": self.conflicting,
            "sentiment_state": self.sentiment_state,
            "highest_impact": self.highest_impact.value,
            "reasons": list(self.reasons),
            "confidence_info": dict(self.confidence_info),
        }


class SentimentGuard:
    """Detects stale or conflicting headline sets before trading."""

    def evaluate(
        self,
        *,
        headlines: list[RankedHeadline],
        as_of: datetime,
        stale_after_minutes: int,
    ) -> SentimentGuardResult:
        reference = _ensure_utc(as_of)
        fresh: list[RankedHeadline] = []
        stale: list[RankedHeadline] = []
        source_names: set[str] = set()
        sentiment_labels: set[str] = set()
        highest_impact = ImpactLevel.LOW

        for ranked in headlines:
            source_names.add(ranked.headline.source)
            if ranked.headline.is_stale(
                as_of=reference, stale_after_minutes=stale_after_minutes
            ):
                stale.append(ranked)
                continue
            fresh.append(ranked)
            if ranked.headline.sentiment_label in {"positive", "negative"}:
                sentiment_labels.add(ranked.headline.sentiment_label)
            if ranked.headline.impact_level == ImpactLevel.HIGH:
                highest_impact = ImpactLevel.HIGH
            elif (
                ranked.headline.impact_level == ImpactLevel.MEDIUM
                and highest_impact != ImpactLevel.HIGH
            ):
                highest_impact = ImpactLevel.MEDIUM

        conflicting = len(sentiment_labels) > 1
        reasons: list[str] = []
        if stale and not fresh:
            reasons.append("STALE_HEADLINES")
        if conflicting:
            reasons.append("CONFLICTING_HEADLINES")
        if not headlines:
            reasons.append("NO_RELEVANT_HEADLINES")

        sentiment_state = "neutral"
        if conflicting:
            sentiment_state = "conflicting"
        elif "positive" in sentiment_labels:
            sentiment_state = "positive"
        elif "negative" in sentiment_labels:
            sentiment_state = "negative"
        elif stale and not fresh:
            sentiment_state = "stale"

        return SentimentGuardResult(
            source_count=len(source_names),
            fresh_headlines=tuple(fresh),
            stale_headlines=tuple(stale),
            conflicting=conflicting,
            sentiment_state=sentiment_state,
            highest_impact=highest_impact,
            reasons=tuple(reasons),
            confidence_info={
                "fresh_count": len(fresh),
                "stale_count": len(stale),
                "source_count": len(source_names),
                "conflicting": conflicting,
            },
        )


__all__ = ["SentimentGuard", "SentimentGuardResult"]
