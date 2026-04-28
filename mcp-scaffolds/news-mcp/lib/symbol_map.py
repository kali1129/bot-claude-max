"""MT5 symbol → currency / category."""

SYMBOL_MAP = {
    "EURUSD": ["EUR", "USD"],
    "GBPUSD": ["GBP", "USD"],
    "USDJPY": ["USD", "JPY"],
    "USDCAD": ["USD", "CAD"],
    "USDCHF": ["USD", "CHF"],
    "AUDUSD": ["AUD", "USD"],
    "NZDUSD": ["NZD", "USD"],
    "EURJPY": ["EUR", "JPY"],
    "GBPJPY": ["GBP", "JPY"],
    "EURGBP": ["EUR", "GBP"],
    # Metals
    "XAUUSD": ["USD"],
    "XAGUSD": ["USD"],
    "GOLD":   ["USD"],
    "SILVER": ["USD"],
    # Indices
    "NAS100": ["USD"],
    "US30":   ["USD"],
    "SPX500": ["USD"],
    "SP500":  ["USD"],
    "GER40":  ["EUR"],
    "DAX":    ["EUR"],
    "UK100":  ["GBP"],
    "JPN225": ["JPY"],
    # Crypto
    "BTCUSD": ["USD"],
    "ETHUSD": ["USD"],
    # Oil
    "USOIL":  ["USD"],
    "WTI":    ["USD"],
    "BRENT":  ["USD"],
}


def currencies_for(symbol: str):
    """Returns the list of currencies whose news affects the given symbol."""
    return SYMBOL_MAP.get(symbol.upper(), [])
