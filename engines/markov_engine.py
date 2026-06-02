def classify_regime(row) -> str:
    """
    Classify the current market regime based on EMA alignment.

    Returns one of: STRONG_BULL | BULL | BEAR | CORRECTION | RANGE
    """

    price = float(row["Close"])
    ema20 = float(row["EMA20"])
    ema50 = float(row["EMA50"])
    ema200 = float(row["EMA200"])

    if price > ema20 > ema50 > ema200:
        return "STRONG_BULL"

    if price > ema20 > ema50:
        return "BULL"

    if price < ema50 < ema200:
        return "BEAR"

    if price < ema20:
        return "CORRECTION"

    return "RANGE"


def regime_strength(row) -> float:
    """Return EMA20/EMA50 spread as a fraction of price (regime momentum proxy)."""

    price = float(row["Close"])
    ema20 = float(row["EMA20"])
    ema50 = float(row["EMA50"])

    return abs(ema20 - ema50) / price
