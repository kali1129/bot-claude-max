"""Trace ID helpers.

Port of xm-mt5-trading-platform/src/common/ids.py.
"""
from __future__ import annotations

from uuid import uuid4


def new_trace_id(prefix: str = "trace") -> str:
    """Create a short trace identifier for audit and routing."""
    return f"{prefix}-{uuid4().hex[:12]}"


__all__ = ["new_trace_id"]
