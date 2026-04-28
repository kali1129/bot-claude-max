"""Market-data quality checks.

Port of xm-mt5-trading-platform/src/market_data/quality_checks.py.

Adapted for the new bot's blueprint:
- Takes List[Dict] OHLCV (the analysis-mcp convention) instead of legacy
  MarketBarSeries class.
- Takes a quote dict instead of QuoteState class.
- Returns plain dicts (no MarketDataQualityReport), MCP-tool-friendly.
- Drops the symbol/timeframe regex validation that depended on legacy
  enums; keeps a permissive symbol regex inline.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any, Mapping, Sequence


_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9._-]{3,32}$")

# Timeframe → seconds. Mirrors _shared/common/timeframes.py without the import
# (this file may run inside trading-mt5-mcp where _shared is already on path,
# but keeping it self-contained avoids a circular bootstrap headache).
_TIMEFRAME_SECONDS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "M30": 1800,
    "H1": 3600,
    "H4": 14400,
    "D1": 86400,
}


@dataclass(slots=True)
class QualityThresholds:
    """Thresholds used by the quality checker."""

    stale_after_seconds: int = 30
    max_spread_points: float | None = None
    allow_zero_volume: bool = False


@dataclass(slots=True)
class QualityFlag:
    """One quality issue found."""

    code: str
    severity: str  # "error" | "warning"
    message: str
    affected_timestamps: list[str]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "affected_timestamps": list(self.affected_timestamps),
            "metadata": dict(self.metadata),
        }


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return _ensure_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str):
        s = value.replace("Z", "+00:00")
        try:
            return _ensure_utc(datetime.fromisoformat(s))
        except ValueError:
            pass
    raise ValueError(f"Unsupported timestamp value: {value!r}")


def _normalize_tf(tf: str) -> str | None:
    norm = tf.strip().upper() if isinstance(tf, str) else ""
    return norm if norm in _TIMEFRAME_SECONDS else None


def _build_report(
    *,
    symbol: str | None,
    timeframe: str | None,
    flags: list[QualityFlag],
) -> dict[str, Any]:
    has_errors = any(f.severity.lower() == "error" for f in flags)
    has_warnings = any(f.severity.lower() == "warning" for f in flags)
    return {
        "ok": True,
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "has_errors": has_errors,
        "has_warnings": has_warnings,
        "flags": [f.to_dict() for f in flags],
    }


def validate_symbol(symbol: str) -> dict[str, Any]:
    """Validate symbol formatting."""
    flags: list[QualityFlag] = []
    if not symbol or not _SYMBOL_PATTERN.fullmatch(symbol.upper()):
        flags.append(QualityFlag(
            code="INVALID_SYMBOL",
            severity="error",
            message=f"Symbol '{symbol}' is not valid for the market-data pipeline.",
            affected_timestamps=[],
            metadata={},
        ))
    return _build_report(symbol=symbol, timeframe=None, flags=flags)


def validate_timeframe(timeframe: str) -> dict[str, Any]:
    """Validate timeframe strings (M1, M5, M15, M30, H1, H4, D1)."""
    flags: list[QualityFlag] = []
    if _normalize_tf(timeframe) is None:
        flags.append(QualityFlag(
            code="INVALID_TIMEFRAME",
            severity="error",
            message=f"Timeframe '{timeframe}' is not supported.",
            affected_timestamps=[],
            metadata={},
        ))
    return _build_report(symbol="", timeframe=timeframe, flags=flags)


def check_bar_series(
    symbol: str,
    timeframe: str,
    bars: Sequence[Mapping[str, Any]],
    *,
    as_of: datetime | None = None,
    thresholds: QualityThresholds | None = None,
) -> dict[str, Any]:
    """Check ordered OHLCV bars for gaps, duplicates, stale state, anomalies.

    Each bar dict needs: time (datetime/iso/epoch), high, low, close.
    Optional: volume, spread (points).
    """
    cfg = thresholds or QualityThresholds()
    flags: list[QualityFlag] = []

    sym_report = validate_symbol(symbol)
    tf_report = validate_timeframe(timeframe)
    for f in sym_report["flags"]:
        flags.append(QualityFlag(**f))
    for f in tf_report["flags"]:
        flags.append(QualityFlag(**f))
    if any(f.severity == "error" for f in flags):
        return _build_report(symbol=symbol, timeframe=timeframe, flags=flags)

    if not bars:
        flags.append(QualityFlag(
            code="EMPTY_SERIES",
            severity="error",
            message="Bar series is empty.",
            affected_timestamps=[],
            metadata={},
        ))
        return _build_report(symbol=symbol, timeframe=timeframe, flags=flags)

    expected_seconds = _TIMEFRAME_SECONDS[_normalize_tf(timeframe)]
    seen: set[str] = set()
    previous_ts: datetime | None = None

    for bar in bars:
        try:
            ts = _parse_dt(bar.get("time"))
        except ValueError as exc:
            flags.append(QualityFlag(
                code="INVALID_TIMESTAMP",
                severity="error",
                message=str(exc),
                affected_timestamps=[],
                metadata={},
            ))
            continue
        ts_iso = ts.isoformat()

        if ts_iso in seen:
            flags.append(QualityFlag(
                code="DUPLICATE_BAR",
                severity="error",
                message=f"Duplicate bar at {ts_iso}.",
                affected_timestamps=[ts_iso],
                metadata={},
            ))
        seen.add(ts_iso)

        if previous_ts is not None:
            delta = (ts - previous_ts).total_seconds()
            if delta < 0:
                flags.append(QualityFlag(
                    code="OUT_OF_ORDER_TIMESTAMPS",
                    severity="error",
                    message="Bar timestamps are out of order.",
                    affected_timestamps=[previous_ts.isoformat(), ts_iso],
                    metadata={},
                ))
            elif delta > expected_seconds:
                missing = int(delta // expected_seconds) - 1
                if missing > 0:
                    flags.append(QualityFlag(
                        code="MISSING_BARS",
                        severity="warning",
                        message=(
                            f"Detected {missing} missing bar(s) between "
                            f"{previous_ts.isoformat()} and {ts_iso}."
                        ),
                        affected_timestamps=[previous_ts.isoformat(), ts_iso],
                        metadata={"missing_bars": missing},
                    ))

        volume = float(bar.get("volume", 0.0))
        if not cfg.allow_zero_volume and volume <= 0:
            flags.append(QualityFlag(
                code="ZERO_VOLUME_ANOMALY",
                severity="warning",
                message=f"Bar at {ts_iso} has non-positive volume.",
                affected_timestamps=[ts_iso],
                metadata={},
            ))

        spread = float(bar.get("spread", 0.0))
        if cfg.max_spread_points is not None and spread > cfg.max_spread_points:
            flags.append(QualityFlag(
                code="SPREAD_OUTLIER",
                severity="warning",
                message=(
                    f"Bar spread {spread} exceeds threshold {cfg.max_spread_points}."
                ),
                affected_timestamps=[ts_iso],
                metadata={"spread_points": spread},
            ))

        previous_ts = ts

    reference = _ensure_utc(as_of) if as_of is not None else datetime.now(timezone.utc)
    if previous_ts is not None and (reference - previous_ts).total_seconds() > cfg.stale_after_seconds:
        flags.append(QualityFlag(
            code="STALE_MARKET_STATE",
            severity="warning",
            message=(
                f"Latest bar is stale by more than {cfg.stale_after_seconds} seconds."
            ),
            affected_timestamps=[previous_ts.isoformat()],
            metadata={},
        ))

    return _build_report(symbol=symbol, timeframe=timeframe, flags=flags)


def check_quote(
    quote: Mapping[str, Any],
    *,
    as_of: datetime | None = None,
    thresholds: QualityThresholds | None = None,
) -> dict[str, Any]:
    """Check quote freshness, spread and bid/ask sanity.

    `quote` dict needs: symbol, timestamp (datetime/iso/epoch), bid, ask.
    Optional: spread (points).
    """
    cfg = thresholds or QualityThresholds()
    flags: list[QualityFlag] = []
    symbol = str(quote.get("symbol", ""))

    sym_report = validate_symbol(symbol)
    for f in sym_report["flags"]:
        flags.append(QualityFlag(**f))

    try:
        ts = _parse_dt(quote.get("timestamp"))
    except ValueError as exc:
        flags.append(QualityFlag(
            code="INVALID_TIMESTAMP",
            severity="error",
            message=str(exc),
            affected_timestamps=[],
            metadata={},
        ))
        return _build_report(symbol=symbol, timeframe=None, flags=flags)

    bid = float(quote.get("bid", 0.0))
    ask = float(quote.get("ask", 0.0))
    spread_points = float(quote.get("spread", 0.0))

    reference = _ensure_utc(as_of) if as_of is not None else datetime.now(timezone.utc)
    if (reference - ts).total_seconds() > cfg.stale_after_seconds:
        flags.append(QualityFlag(
            code="STALE_MARKET_STATE",
            severity="warning",
            message=f"Quote is older than {cfg.stale_after_seconds} seconds.",
            affected_timestamps=[ts.isoformat()],
            metadata={},
        ))

    if cfg.max_spread_points is not None and spread_points > cfg.max_spread_points:
        flags.append(QualityFlag(
            code="SPREAD_OUTLIER",
            severity="warning",
            message=(
                f"Quote spread {spread_points} exceeds threshold {cfg.max_spread_points}."
            ),
            affected_timestamps=[ts.isoformat()],
            metadata={"spread_points": spread_points},
        ))

    if bid <= 0 or ask <= 0 or ask < bid:
        flags.append(QualityFlag(
            code="INVALID_QUOTE",
            severity="error",
            message="Quote bid/ask values are invalid.",
            affected_timestamps=[ts.isoformat()],
            metadata={"bid": bid, "ask": ask},
        ))

    return _build_report(symbol=symbol, timeframe=None, flags=flags)


__all__ = [
    "QualityThresholds",
    "QualityFlag",
    "validate_symbol",
    "validate_timeframe",
    "check_bar_series",
    "check_quote",
]
