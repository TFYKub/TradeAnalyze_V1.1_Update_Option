"""
Greeks Enrichment Pipeline
===========================
Takes raw option-chain rows (from option_chain.py) and attaches
Black-Scholes Greeks + signal hints to each row.

For Deribit rows that already carry greeks from the exchange,
we use those directly (they account for crypto's continuous funding).
For yfinance rows, we always compute BS greeks from the IV field.
"""

import logging

from engines.greeks_engine import black_scholes_greeks, greeks_signal_score

logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.05


def enrich_with_greeks(rows: list[dict], spot: float) -> list[dict]:
    """
    Attach greeks + signal_hints to each row in-place.

    Parameters
    ----------
    rows : list of option rows from fetch_option_chain()
    spot : current spot price of the underlying

    Returns the same list with extra keys added to each row.
    """

    enriched = []

    for row in rows:
        row = dict(row)   # shallow copy

        dte    = row.get("dte", 0)
        T      = max(dte / 365, 1 / 365)
        iv     = row.get("iv", 0.0)
        strike = row.get("strike", 0.0)
        opt_t  = row.get("option_type", "call")
        source = row.get("source", "yfinance")

        # ── Use exchange-provided greeks for Deribit ──────────────────────────
        if source == "deribit" and row.get("_deribit_delta"):
            greeks = {
                "delta": round(float(row.get("_deribit_delta", 0)), 5),
                "gamma": round(float(row.get("_deribit_gamma", 0)), 6),
                "vega":  round(float(row.get("_deribit_vega",  0)), 5),
                "theta": round(float(row.get("_deribit_theta", 0)), 5),
                "rho":   None,   # Deribit doesn't expose rho
            }
        elif iv > 0:
            greeks = black_scholes_greeks(
                S=spot,
                K=strike,
                T=T,
                sigma=iv,
                r=RISK_FREE_RATE,
                option_type=opt_t,
            )
        else:
            # Fall back to BS with a synthetic IV from bid/ask mid
            mid = row.get("mid", 0)
            if mid > 0 and spot > 0 and strike > 0:
                # Very rough IV proxy using option mid / spot (not proper inversion)
                # Better to skip than produce garbage greeks
                greeks = {}
            else:
                greeks = {}

        row["delta"] = greeks.get("delta")
        row["gamma"] = greeks.get("gamma")
        row["theta"] = greeks.get("theta")
        row["vega"]  = greeks.get("vega")
        row["rho"]   = greeks.get("rho")

        # Signal hints (only when greeks are available)
        if greeks:
            hints = greeks_signal_score(greeks, opt_t)
            row.update(hints)
        else:
            row["moneyness"]          = None
            row["high_gamma"]         = None
            row["theta_category"]     = None
            row["vega_category"]      = None
            row["direction_bias"]     = None

        # Clean up internal Deribit keys
        for k in ("_deribit_delta", "_deribit_gamma", "_deribit_vega", "_deribit_theta"):
            row.pop(k, None)

        enriched.append(row)

    return enriched
