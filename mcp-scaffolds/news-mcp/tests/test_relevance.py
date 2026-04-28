from lib.relevance import score_headline
from lib.symbol_map import currencies_for, SYMBOL_MAP


def test_fed_headline_scores_high_for_usd():
    res = score_headline("Fed signals rate hike at FOMC meeting", "USD")
    assert res["score"] >= 30


def test_eur_headline_scores_high_for_ecb():
    res = score_headline("ECB Lagarde defends rate path", "EUR")
    assert res["score"] >= 20


def test_unrelated_headline_scores_zero():
    res = score_headline("Local football team wins championship", "USD")
    assert res["score"] == 0


def test_headline_with_full_symbol():
    res = score_headline("Powell speaks on inflation", "EURUSD")
    # EURUSD currencies are EUR + USD; Powell + inflation are USD keywords.
    assert res["score"] >= 20


def test_currencies_for_known_symbol():
    assert "USD" in currencies_for("EURUSD")
    assert "EUR" in currencies_for("EURUSD")
    assert currencies_for("XAUUSD") == ["USD"]


def test_currencies_for_unknown_symbol():
    assert currencies_for("XYZ123") == []


def test_symbol_map_covers_majors():
    for s in ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD", "NAS100", "BTCUSD"):
        assert s in SYMBOL_MAP, f"{s} should be in SYMBOL_MAP"
