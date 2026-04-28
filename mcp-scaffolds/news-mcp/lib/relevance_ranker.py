"""Relevance ranking for normalized headlines.

Port of xm-mt5-trading-platform/src/news/relevance_ranker.py.

Adapted: takes NormalizedHeadline from the local headline_normalizer (no
legacy `news.headline_normalizer` import). API surface preserved.
"""
from __future__ import annotations

from dataclasses import dataclass

from .headline_normalizer import NormalizedHeadline


def infer_asset_class(symbol: str) -> str | None:
    """Heuristic asset-class inference from symbol shape."""
    normalized = symbol.upper()
    if len(normalized) == 6 and normalized.isalpha():
        return "FX"
    if normalized.startswith(("XAU", "XAG", "XPT", "XPD")):
        return "METALS"
    if normalized.endswith(("USD", "USDT")) and normalized.startswith(
        ("BTC", "ETH", "SOL")
    ):
        return "CRYPTO"
    if any(char.isdigit() for char in normalized):
        return "INDICES"
    return None


@dataclass(frozen=True, slots=True)
class RankedHeadline:
    """Normalized headline with deterministic relevance scoring for one symbol."""

    symbol: str
    score: float
    reasons: tuple[str, ...]
    headline: NormalizedHeadline
    asset_class: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "score": self.score,
            "reasons": list(self.reasons),
            "asset_class": self.asset_class,
            "headline": self.headline.to_dict(),
        }


class RelevanceRanker:
    """Ranks normalized headlines for one tradable symbol.

    Score components:
      EXPLICIT_SYMBOL_MATCH (+0.75)  — symbol appears in normalized.symbols
      ASSET_CLASS_MATCH    (+0.20)  — same asset class
      MACRO_THEME_MATCH    (+0.15)  — overlapping configured macro themes
      DIRECT_TEXT_MATCH    (+0.90)  — symbol literal in title text
    Final score capped at 1.0; entries below `minimum_score` dropped.
    """

    def __init__(
        self,
        *,
        symbol_aliases: dict[str, list[str]] | None = None,
        asset_class_by_symbol: dict[str, str] | None = None,
        macro_themes_by_symbol: dict[str, list[str]] | None = None,
        minimum_score: float = 0.35,
    ) -> None:
        self.symbol_aliases = {
            symbol.upper(): list(aliases)
            for symbol, aliases in (symbol_aliases or {}).items()
        }
        self.asset_class_by_symbol = {
            symbol.upper(): asset_class.upper()
            for symbol, asset_class in (asset_class_by_symbol or {}).items()
        }
        self.macro_themes_by_symbol = {
            symbol.upper(): [theme.lower() for theme in themes]
            for symbol, themes in (macro_themes_by_symbol or {}).items()
        }
        self.minimum_score = minimum_score

    def asset_class_for_symbol(self, symbol: str) -> str | None:
        normalized = symbol.upper()
        return self.asset_class_by_symbol.get(normalized) or infer_asset_class(normalized)

    def _is_known_symbol(self, symbol: str) -> bool:
        normalized = symbol.upper()
        return normalized in self.symbol_aliases or normalized in self.asset_class_by_symbol

    def rank(
        self,
        *,
        symbol: str,
        headlines: list[NormalizedHeadline],
    ) -> list[RankedHeadline]:
        normalized_symbol = symbol.upper()
        asset_class = self.asset_class_for_symbol(normalized_symbol)
        configured_themes = set(self.macro_themes_by_symbol.get(normalized_symbol, []))
        allow_asset_class_fallback = self._is_known_symbol(normalized_symbol)
        ranked: list[RankedHeadline] = []

        for headline in headlines:
            score = 0.0
            reasons: list[str] = []
            if normalized_symbol in headline.symbols:
                score += 0.75
                reasons.append("EXPLICIT_SYMBOL_MATCH")

            if (
                allow_asset_class_fallback
                and asset_class is not None
                and asset_class in headline.asset_classes
            ):
                score += 0.20
                reasons.append("ASSET_CLASS_MATCH")

            shared_themes = configured_themes.intersection(
                theme.lower() for theme in headline.macro_themes
            )
            if shared_themes:
                score += 0.15
                reasons.append("MACRO_THEME_MATCH")

            if normalized_symbol.lower() in headline.normalized_title.replace(" ", ""):
                score += 0.90
                reasons.append("DIRECT_TEXT_MATCH")

            if score < self.minimum_score:
                continue
            ranked.append(
                RankedHeadline(
                    symbol=normalized_symbol,
                    score=min(score, 1.0),
                    reasons=tuple(reasons),
                    headline=headline,
                    asset_class=asset_class,
                )
            )

        ranked.sort(
            key=lambda item: (item.score, item.headline.published_at),
            reverse=True,
        )
        return ranked


__all__ = ["RankedHeadline", "RelevanceRanker", "infer_asset_class"]
