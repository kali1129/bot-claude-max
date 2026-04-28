"""Shared enums used across MCPs.

Ported subset from xm-mt5-trading-platform/src/common/enums.py. Only the
values that are referenced from at least two MCPs live here. RuntimeMode
and OrderStatus stay local to the MCPs that own those concerns.
"""
from __future__ import annotations

from enum import Enum


class ImpactLevel(str, Enum):
    """Impact levels for contextual events (news + calendar)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class GateState(str, Enum):
    """Possible outcomes of the news/context gate."""

    ALLOW = "allow"
    REDUCE_SIZE = "reduce_size"
    BLOCK_NEW_ENTRIES = "block_new_entries"
    REVIEW_REQUIRED = "review_required"


def impact_rank(level: ImpactLevel) -> int:
    return {ImpactLevel.LOW: 1, ImpactLevel.MEDIUM: 2, ImpactLevel.HIGH: 3}[level]


def max_impact(*levels: ImpactLevel) -> ImpactLevel:
    current = ImpactLevel.LOW
    for level in levels:
        if impact_rank(level) > impact_rank(current):
            current = level
    return current


__all__ = ["ImpactLevel", "GateState", "impact_rank", "max_impact"]
