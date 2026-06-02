def generate_option_trade(price: float, regime: str, atr: float) -> dict:
    """
    Return a flat options-trade dict for the given market regime.

    Schema keys: strategy, direction, entry, target,
                 buy_call, sell_call, buy_put, sell_put, dte, pop
    """

    price = float(price)

    if regime == "STRONG_BULL":
        return {
            "strategy": "BULL_CALL_SPREAD",
            "direction": "BULLISH",
            "entry": round(price),
            "target": round(price * 1.08),
            "buy_call": round(price * 1.00),
            "sell_call": round(price * 1.05),
            "buy_put": None,
            "sell_put": None,
            "dte": 30,
            "pop": 62,
        }

    if regime == "BULL":
        return {
            "strategy": "CALL_DEBIT_SPREAD",
            "direction": "BULLISH",
            "entry": round(price * 0.98),
            "target": round(price * 1.06),
            "buy_call": round(price * 0.98),
            "sell_call": round(price * 1.03),
            "buy_put": None,
            "sell_put": None,
            "dte": 30,
            "pop": 58,
        }

    if regime == "BEAR":
        return {
            "strategy": "PUT_DEBIT_SPREAD",
            "direction": "BEARISH",
            "entry": round(price * 1.02),
            "target": round(price * 0.94),
            "buy_call": None,
            "sell_call": None,
            "buy_put": round(price * 1.02),
            "sell_put": round(price * 0.97),
            "dte": 30,
            "pop": 57,
        }

    if regime in ("CORRECTION", "RANGE", "SIDEWAY"):
        return {
            "strategy": "IRON_CONDOR",
            "direction": "NEUTRAL",
            "entry": round(price),
            "target": round(price),
            "buy_call": round(price * 1.08),
            "sell_call": round(price * 1.05),
            "buy_put": round(price * 0.92),
            "sell_put": round(price * 0.95),
            "dte": 45,
            "pop": 65,
        }

    # Default safe mode
    return {
        "strategy": "NO_TRADE",
        "direction": "WAIT",
        "entry": round(price),
        "target": round(price),
        "buy_call": None,
        "sell_call": None,
        "buy_put": None,
        "sell_put": None,
        "dte": 0,
        "pop": 0,
    }
