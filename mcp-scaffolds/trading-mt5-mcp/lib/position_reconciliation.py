"""Position reconciliation between MT5 and the backend journal.

Replacement for xm-mt5-trading-platform/src/execution/reconciliation.py.

The legacy module was 724 LOC of SQLite + file-bridge plumbing, tightly
coupled to MT5 state file exchange. The new bot uses the MetaTrader5 Python
package directly + Mongo journal, so that pipeline is irrelevant.

What is kept: the *concept* of reconciling two views of "open positions" and
flagging discrepancies. This module is pure (no IO) and accepts both views
as plain dicts so the trading-mt5-mcp can call it after polling MT5 and the
backend journal independently.

Returns a structured diff:
  - missing_in_journal: positions live in MT5 but not in the journal
  - missing_in_mt5    : positions in the journal that MT5 no longer reports
  - mismatched        : same ticket but key fields differ (volume, sl, tp, type)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class PositionDiff:
    """Outcome of reconciling MT5 open positions vs. backend journal."""

    matched: tuple[int, ...]
    missing_in_journal: tuple[int, ...]
    missing_in_mt5: tuple[int, ...]
    mismatched: tuple[dict[str, Any], ...]

    @property
    def in_sync(self) -> bool:
        return (
            not self.missing_in_journal
            and not self.missing_in_mt5
            and not self.mismatched
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": True,
            "in_sync": self.in_sync,
            "matched_count": len(self.matched),
            "matched_tickets": list(self.matched),
            "missing_in_journal": list(self.missing_in_journal),
            "missing_in_mt5": list(self.missing_in_mt5),
            "mismatched": [dict(m) for m in self.mismatched],
        }


_RECONCILIATION_FIELDS = ("symbol", "type", "volume", "sl", "tp")


def _ticket(record: Mapping[str, Any]) -> int | None:
    """Extract a ticket id robust to different naming conventions."""
    for key in ("ticket", "deal_ticket", "position_id", "position_ticket", "id"):
        value = record.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _field(record: Mapping[str, Any], field: str) -> Any:
    """Read a key with a few legacy aliases."""
    if field in record:
        return record[field]
    aliases = {
        "type": ("side", "direction"),
        "sl": ("stop_loss",),
        "tp": ("take_profit",),
        "volume": ("lot", "lots"),
    }.get(field, ())
    for alias in aliases:
        if alias in record:
            return record[alias]
    return None


def _normalize_value(value: Any) -> Any:
    """Coerce values for cross-system comparison.

    - Numbers are coerced to float and rounded to 6 decimals.
    - Strings are upper-cased and stripped (handles 'buy' vs 'BUY').
    - None passes through.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    if isinstance(value, str):
        return value.strip().upper()
    return value


def reconcile_positions(
    *,
    mt5_positions: Iterable[Mapping[str, Any]],
    journal_positions: Iterable[Mapping[str, Any]],
    fields: tuple[str, ...] = _RECONCILIATION_FIELDS,
) -> PositionDiff:
    """Return a structured diff between MT5 and journal views.

    Both inputs are iterables of dicts. Each dict must carry a ticket
    identifier under one of: ticket, deal_ticket, position_id,
    position_ticket, id.

    Tickets present in both are compared field-by-field across `fields`.
    """
    mt5_by_ticket: dict[int, Mapping[str, Any]] = {}
    journal_by_ticket: dict[int, Mapping[str, Any]] = {}

    for record in mt5_positions:
        t = _ticket(record)
        if t is not None:
            mt5_by_ticket[t] = record

    for record in journal_positions:
        t = _ticket(record)
        if t is not None:
            journal_by_ticket[t] = record

    mt5_tickets = set(mt5_by_ticket.keys())
    journal_tickets = set(journal_by_ticket.keys())
    matched = mt5_tickets & journal_tickets
    missing_in_journal = mt5_tickets - journal_tickets
    missing_in_mt5 = journal_tickets - mt5_tickets

    mismatched: list[dict[str, Any]] = []
    for ticket in sorted(matched):
        m_rec = mt5_by_ticket[ticket]
        j_rec = journal_by_ticket[ticket]
        diffs: dict[str, dict[str, Any]] = {}
        for field in fields:
            m_val = _normalize_value(_field(m_rec, field))
            j_val = _normalize_value(_field(j_rec, field))
            if m_val != j_val:
                diffs[field] = {"mt5": m_val, "journal": j_val}
        if diffs:
            mismatched.append({"ticket": ticket, "diffs": diffs})

    return PositionDiff(
        matched=tuple(sorted(matched)),
        missing_in_journal=tuple(sorted(missing_in_journal)),
        missing_in_mt5=tuple(sorted(missing_in_mt5)),
        mismatched=tuple(mismatched),
    )


__all__ = ["PositionDiff", "reconcile_positions"]
