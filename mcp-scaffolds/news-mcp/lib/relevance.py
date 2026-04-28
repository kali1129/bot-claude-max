"""Keyword-based relevance score (0..100). Crude but auditable."""
from __future__ import annotations

KEYWORDS = {
    "USD": [("FOMC", 30), ("Fed ", 25), ("federal reserve", 25), ("Powell", 20),
            ("CPI", 25), ("inflation", 15), ("NFP", 30), ("non-farm", 25),
            ("unemployment", 15), ("jobs", 15), ("GDP", 15), ("retail sales", 10),
            ("rate hike", 25), ("rate cut", 25)],
    "EUR": [("ECB", 30), ("Lagarde", 20), ("eurozone", 15), ("germany", 10),
            ("france", 10), ("PMI", 10)],
    "GBP": [("BoE", 30), ("Bailey", 20), ("uk inflation", 20), ("brexit", 10)],
    "JPY": [("BoJ", 30), ("Ueda", 20), ("yen intervention", 25)],
    "CAD": [("BoC", 30), ("oil", 15)],
    "AUD": [("RBA", 30), ("china", 10), ("iron ore", 10)],
    "NZD": [("RBNZ", 30)],
    "CHF": [("SNB", 30)],
}


def score_headline(headline: str, symbol_or_currency: str) -> dict:
    """0..100 relevance + matched keywords."""
    if not headline:
        return {"score": 0, "matched": []}
    headline_l = headline.lower()
    sc = symbol_or_currency.upper()

    # If a full MT5 symbol is provided, expand to currencies via symbol_map.
    from .symbol_map import currencies_for
    cur_list = currencies_for(sc) or [sc]

    matched = []
    score = 0
    for cur in cur_list:
        for kw, w in KEYWORDS.get(cur, []):
            if kw.lower() in headline_l:
                matched.append({"keyword": kw.strip(), "currency": cur, "weight": w})
                score += w
    return {"score": min(score, 100), "matched": matched}
