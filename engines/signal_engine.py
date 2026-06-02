def generate_signal(price: float, atr: float, regime: str) -> dict:
    """
    Build a trade signal dict for the given market regime.

    Returns keys: position, entry, sl, tp1, tp2, target, risk, holding_days, active
    """

    def build(position, entry, stop, tp1, tp2, target, risk, days, active=True):
        return {
            "position": position,
            "entry": entry,
            "sl": stop,
            "tp1": tp1,
            "tp2": tp2,
            "target": target,
            "risk": risk,
            "holding_days": days,
            "active": active,
        }

    if regime in ("STRONG_BULL", "BULL"):
        return build(
            position="LONG",
            entry=price,
            stop=price - atr,
            tp1=price + atr,
            tp2=price + atr * 2,
            target=price + atr * 2,
            risk=atr,
            days=30,
            active=True,
        )

    if regime == "BEAR":
        return build(
            position="SHORT",
            entry=price,
            stop=price + atr,
            tp1=price - atr,
            tp2=price - atr * 2,
            target=price - atr * 2,
            risk=atr,
            days=30,
            active=True,
        )

    # CORRECTION | RANGE | SIDEWAY | anything else → no trade
    return build(
        position="WAIT",
        entry=price,
        stop=price,
        tp1=price,
        tp2=price,
        target=price,
        risk=0,
        days=0,
        active=False,
    )
