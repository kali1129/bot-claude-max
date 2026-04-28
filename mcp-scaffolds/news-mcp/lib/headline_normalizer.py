"""Deterministic normalization for raw news headlines.

Port of xm-mt5-trading-platform/src/news/headline_normalizer.py.

Adapted for the bot nuevo:
- Takes a plain dict (or CollectedHeadline-shaped) instead of the legacy
  CollectedHeadline class. Backwards-compatible field names.
- ImpactLevel imported from `_shared.common.enums` (no duplicated enum).
- No dependency on legacy `news.collector`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
import sys
from pathlib import Path
from typing import Any, Mapping

# Make _shared importable from anywhere news-mcp imports this file.
_HERE = Path(__file__).resolve().parent
_SHARED_PARENT = _HERE.parent.parent  # mcp-scaffolds/
if str(_SHARED_PARENT) not in sys.path:
    sys.path.insert(0, str(_SHARED_PARENT))

from _shared.common.enums import ImpactLevel  # noqa: E402


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
        normalized = value.replace("Z", "+00:00")
        try:
            return _ensure_utc(datetime.fromisoformat(normalized))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


@dataclass(frozen=True, slots=True)
class NormalizedHeadline:
    """Structured headline used by downstream ranking and gating."""

    source: str
    headline_id: str
    title: str
    normalized_title: str
    published_at: datetime
    symbols: tuple[str, ...]
    asset_classes: tuple[str, ...]
    macro_themes: tuple[str, ...]
    impact_level: ImpactLevel
    sentiment_label: str
    confidence_info: dict[str, Any] = field(default_factory=dict)
    url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "published_at", _ensure_utc(self.published_at))

    def is_stale(self, *, as_of: datetime, stale_after_minutes: int) -> bool:
        age_minutes = (_ensure_utc(as_of) - self.published_at).total_seconds() / 60.0
        return age_minutes > stale_after_minutes

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "headline_id": self.headline_id,
            "title": self.title,
            "normalized_title": self.normalized_title,
            "published_at": self.published_at.isoformat(),
            "symbols": list(self.symbols),
            "asset_classes": list(self.asset_classes),
            "macro_themes": list(self.macro_themes),
            "impact_level": self.impact_level.value,
            "sentiment_label": self.sentiment_label,
            "confidence_info": dict(self.confidence_info),
            "url": self.url,
            "metadata": dict(self.metadata),
        }


_DEFAULT_MACRO_THEMES = {
    "inflation": ["inflation", "cpi", "pce", "prices"],
    "rates": ["rate", "rates", "fomc", "ecb", "boj", "boe", "hawkish", "dovish"],
    "growth": ["gdp", "pmi", "manufacturing", "services", "recession"],
    "labor": ["employment", "jobs", "nonfarm payrolls", "nfp", "wages"],
    "energy": ["oil", "gas", "opec"],
    "geopolitics": ["war", "sanctions", "tariff", "election", "conflict"],
    "metals": ["gold", "silver", "bullion", "xau", "xag"],
}

_HIGH_IMPACT_KW = {
    "cpi", "inflation", "nfp", "nonfarm payrolls", "rate decision", "fomc",
    "ecb", "boj", "boe", "gdp", "employment", "pce", "tariff", "war",
}
_MEDIUM_IMPACT_KW = {
    "pmi", "retail sales", "consumer confidence", "manufacturing", "services",
    "minutes", "speech", "guidance", "forecast", "downgrade", "upgrade",
}
_POSITIVE_KW = {
    "beat", "beats", "boost", "boosts", "rise", "rises", "surge", "strong",
    "hawkish", "expands", "gain", "gains",
}
_NEGATIVE_KW = {
    "drag", "drags", "lower", "miss", "misses", "fall", "falls", "drop",
    "drops", "weak", "dovish", "contracts", "cuts", "risk-off",
}


class HeadlineNormalizer:
    """Normalizes raw headlines into deterministic structured records."""

    def __init__(
        self,
        *,
        symbol_aliases: Mapping[str, list[str]] | None = None,
        asset_class_by_symbol: Mapping[str, str] | None = None,
        macro_theme_keywords: Mapping[str, list[str]] | None = None,
    ) -> None:
        self.symbol_aliases = {
            symbol.upper(): [_slug(alias) for alias in aliases]
            for symbol, aliases in (symbol_aliases or {}).items()
        }
        self.asset_class_by_symbol = {
            symbol.upper(): asset_class.upper()
            for symbol, asset_class in (asset_class_by_symbol or {}).items()
        }
        themes_source = macro_theme_keywords or _DEFAULT_MACRO_THEMES
        self.macro_theme_keywords = {
            theme: [_slug(kw) for kw in keywords]
            for theme, keywords in themes_source.items()
        }

    def _match_symbols(self, normalized_title: str) -> tuple[str, ...]:
        matches: set[str] = set()
        compact = normalized_title.replace(" ", "")
        for symbol, aliases in self.symbol_aliases.items():
            symbol_slug = _slug(symbol)
            if symbol_slug and symbol_slug in normalized_title:
                matches.add(symbol)
                continue
            if symbol.lower() in compact:
                matches.add(symbol)
                continue
            if any(alias and alias in normalized_title for alias in aliases):
                matches.add(symbol)
        return tuple(sorted(matches))

    def _classify_asset_classes(self, symbols: tuple[str, ...]) -> tuple[str, ...]:
        classes = {
            self.asset_class_by_symbol[s]
            for s in symbols
            if s in self.asset_class_by_symbol
        }
        return tuple(sorted(classes))

    def _classify_macro_themes(self, normalized_title: str) -> tuple[str, ...]:
        matches = {
            theme
            for theme, keywords in self.macro_theme_keywords.items()
            if any(kw and kw in normalized_title for kw in keywords)
        }
        return tuple(sorted(matches))

    def _classify_impact(
        self, normalized_title: str, macro_themes: tuple[str, ...]
    ) -> ImpactLevel:
        if any(kw in normalized_title for kw in _HIGH_IMPACT_KW):
            return ImpactLevel.HIGH
        if any(kw in normalized_title for kw in _MEDIUM_IMPACT_KW):
            return ImpactLevel.MEDIUM
        if macro_themes:
            return ImpactLevel.MEDIUM
        return ImpactLevel.LOW

    def _classify_sentiment(self, normalized_title: str) -> str:
        positive = any(kw in normalized_title for kw in _POSITIVE_KW)
        negative = any(kw in normalized_title for kw in _NEGATIVE_KW)
        if positive and negative:
            return "mixed"
        if positive:
            return "positive"
        if negative:
            return "negative"
        return "neutral"

    def normalize(self, headline: Mapping[str, Any]) -> NormalizedHeadline:
        """Take a raw headline dict and return the normalized record.

        Expected fields: source, headline_id (or id), title, published_at
        (datetime / iso string / epoch), url (optional), metadata (optional).
        """
        title = str(headline.get("title", ""))
        normalized_title = _slug(title)
        symbols = self._match_symbols(normalized_title)
        macro_themes = self._classify_macro_themes(normalized_title)
        asset_classes = self._classify_asset_classes(symbols)
        impact_level = self._classify_impact(normalized_title, macro_themes)
        sentiment_label = self._classify_sentiment(normalized_title)

        return NormalizedHeadline(
            source=str(headline.get("source", "unknown")),
            headline_id=str(headline.get("headline_id") or headline.get("id") or ""),
            title=title,
            normalized_title=normalized_title,
            published_at=_parse_dt(headline.get("published_at")),
            symbols=symbols,
            asset_classes=asset_classes,
            macro_themes=macro_themes,
            impact_level=impact_level,
            sentiment_label=sentiment_label,
            confidence_info={
                "source": headline.get("source", "unknown"),
                "normalization_version": "1.0",
                "symbol_matches": len(symbols),
                "macro_theme_matches": len(macro_themes),
            },
            url=headline.get("url"),
            metadata=dict(headline.get("metadata", {})),
        )

    def normalize_many(self, headlines: list[Mapping[str, Any]]) -> list[NormalizedHeadline]:
        return [self.normalize(h) for h in headlines]


__all__ = ["NormalizedHeadline", "HeadlineNormalizer"]
