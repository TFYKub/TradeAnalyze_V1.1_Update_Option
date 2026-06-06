"""
Strike Selector
================
Picks optimal strikes for each strategy from the live option chain.
Falls back to ATM-based estimation when chain data is unavailable.

Selection rules per strategy:
  LONG_CALL          → ATM call (delta closest to 0.50)
  BULL_CALL_SPREAD   → buy ATM, sell OTM at +1 expected_move / 5%
  CASH_SECURED_PUT   → sell OTM put at -1 expected_move (delta ~0.30)
  PUT_CREDIT_SPREAD  → sell OTM put, buy further OTM (width = ~spread_pct)
  RISK_REVERSAL      → sell OTM put, buy OTM call at ±1 sigma
  IRON_CONDOR        → short strikes at ±1 sigma, wings at ±2 sigma
  IRON_BUTTERFLY     → short ATM, wings at ±1 spread_pct
  SHORT_STRANGLE     → sell OTM call/put at ±1 sigma
  LONG_STRADDLE      → buy ATM call + ATM put
  LONG_STRANGLE      → buy OTM call + OTM put at ±1 sigma
  LONG_PUT           → ATM put (delta closest to -0.50)
  PUT_DEBIT_SPREAD   → buy ATM put, sell OTM put (width ≈ spread_pct)
  BEAR_CALL_SPREAD   → sell OTM call, buy further OTM
  COVERED_CALL       → sell OTM call at +0.5 sigma above spot
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SPREAD_PCT   = 0.05   # default spread width (5% of spot)
WING_PCT     = 0.08   # iron condor outer wing (8% from spot)


@dataclass(frozen=True)
class StrikeSet:
    """Resolved strikes and mid-premiums for one strategy."""
    strategy:    str
    buy_call:    float | None
    sell_call:   float | None
    buy_put:     float | None
    sell_put:    float | None
    buy_call_prem:  float
    sell_call_prem: float
    buy_put_prem:   float
    sell_put_prem:  float
    source:      str   # "chain" | "estimated"


def select_strikes(
    strategy:      str,
    spot:          float,
    enriched_chain: list[dict],
    dte_target:    int,
    expected_move: float,
) -> StrikeSet:
    """
    Select strikes for a given strategy.

    Parameters
    ----------
    strategy       : strategy name (e.g. "IRON_CONDOR")
    spot           : current price
    enriched_chain : enriched option rows from greeks_pipeline
    dte_target     : target DTE bucket
    expected_move  : 1-sigma expected move ($)
    """

    chain_for_dte = [
        r for r in enriched_chain
        if r.get("dte_bucket") == dte_target
    ] if enriched_chain else []

    if chain_for_dte:
        return _from_chain(strategy, spot, chain_for_dte, expected_move)
    return _estimated(strategy, spot, expected_move)


def _lookup(chain: list[dict], opt_type: str, target_strike: float) -> dict:
    """Return the row whose strike is closest to target_strike."""
    subset = [r for r in chain if r.get("option_type") == opt_type]
    if not subset:
        return {}
    return min(subset, key=lambda r: abs(float(r.get("strike", 0)) - target_strike))


def _mid(row: dict) -> float:
    mid = row.get("mid", 0)
    if mid and float(mid) > 0:
        return float(mid)
    bid = float(row.get("bid", 0) or 0)
    ask = float(row.get("ask", 0) or 0)
    return (bid + ask) / 2 if bid > 0 or ask > 0 else _estimate_premium(float(row.get("strike", 0)))


def _estimate_premium(strike: float) -> float:
    """Fallback premium estimate ≈ 2% of strike (very rough)."""
    return round(strike * 0.02, 2)


def _from_chain(strategy: str, spot: float, chain: list[dict], em: float) -> StrikeSet:
    """Build StrikeSet from real chain data."""

    em1 = em
    em2 = em * 1.6   # 2-sigma approx

    atm_call_row = _lookup(chain, "call", spot)
    atm_put_row  = _lookup(chain, "put",  spot)
    otm_call_row = _lookup(chain, "call", spot + em1)
    otm_put_row  = _lookup(chain, "put",  spot - em1)
    wing_call_row = _lookup(chain, "call", spot + em2)
    wing_put_row  = _lookup(chain, "put",  spot - em2)

    def _s(row) -> float:
        return float(row.get("strike", 0)) if row else 0.0

    def _p(row) -> float:
        return _mid(row) if row else 0.0

    s = strategy.upper()

    _z = StrikeSet(strategy=s, buy_call=None, sell_call=None,
                   buy_put=None, sell_put=None,
                   buy_call_prem=0, sell_call_prem=0,
                   buy_put_prem=0, sell_put_prem=0, source="chain")

    if s == "LONG_CALL":
        return StrikeSet(s, _s(atm_call_row), None, None, None,
                         _p(atm_call_row), 0, 0, 0, "chain")

    if s == "BULL_CALL_SPREAD":
        return StrikeSet(s, _s(atm_call_row), _s(otm_call_row), None, None,
                         _p(atm_call_row), _p(otm_call_row), 0, 0, "chain")

    if s == "CASH_SECURED_PUT":
        return StrikeSet(s, None, None, None, _s(otm_put_row),
                         0, 0, 0, _p(otm_put_row), "chain")

    if s == "PUT_CREDIT_SPREAD":
        return StrikeSet(s, None, None, _s(wing_put_row), _s(otm_put_row),
                         0, 0, _p(wing_put_row), _p(otm_put_row), "chain")

    if s == "RISK_REVERSAL":
        return StrikeSet(s, _s(otm_call_row), None, None, _s(otm_put_row),
                         _p(otm_call_row), 0, 0, _p(otm_put_row), "chain")

    if s == "IRON_CONDOR":
        return StrikeSet(s, _s(wing_call_row), _s(otm_call_row),
                         _s(wing_put_row), _s(otm_put_row),
                         _p(wing_call_row), _p(otm_call_row),
                         _p(wing_put_row), _p(otm_put_row), "chain")

    if s == "IRON_BUTTERFLY":
        return StrikeSet(s, _s(otm_call_row), _s(atm_call_row),
                         _s(otm_put_row), _s(atm_put_row),
                         _p(otm_call_row), _p(atm_call_row),
                         _p(otm_put_row), _p(atm_put_row), "chain")

    if s == "SHORT_STRANGLE":
        return StrikeSet(s, None, _s(otm_call_row), None, _s(otm_put_row),
                         0, _p(otm_call_row), 0, _p(otm_put_row), "chain")

    if s in ("LONG_STRADDLE", "LONG_STRANGLE"):
        bc = _s(otm_call_row) if s == "LONG_STRANGLE" else _s(atm_call_row)
        bp = _s(otm_put_row)  if s == "LONG_STRANGLE" else _s(atm_put_row)
        return StrikeSet(s, bc, None, bp, None,
                         _p(otm_call_row if s == "LONG_STRANGLE" else atm_call_row),
                         0,
                         _p(otm_put_row if s == "LONG_STRANGLE" else atm_put_row),
                         0, "chain")

    if s == "LONG_PUT":
        return StrikeSet(s, None, None, _s(atm_put_row), None,
                         0, 0, _p(atm_put_row), 0, "chain")

    if s == "PUT_DEBIT_SPREAD":
        return StrikeSet(s, None, None, _s(atm_put_row), _s(otm_put_row),
                         0, 0, _p(atm_put_row), _p(otm_put_row), "chain")

    if s == "BEAR_CALL_SPREAD":
        return StrikeSet(s, _s(wing_call_row), _s(otm_call_row), None, None,
                         _p(wing_call_row), _p(otm_call_row), 0, 0, "chain")

    if s == "COVERED_CALL":
        return StrikeSet(s, None, _s(otm_call_row), None, None,
                         0, _p(otm_call_row), 0, 0, "chain")

    return _z


def _estimated(strategy: str, spot: float, em: float) -> StrikeSet:
    """Estimate strikes from spot + expected move when no chain available."""

    sp  = spot * SPREAD_PCT    # 5% spread
    wp  = spot * WING_PCT      # 8% wing

    em1 = max(em, sp)
    em2 = max(em * 1.6, wp)

    def _prem(strike: float, is_call: bool) -> float:
        itm  = spot - strike if is_call else strike - spot
        pct  = max(0.5, abs(itm) / spot * 50)   # very rough Black-Scholes approx
        base = spot * 0.015
        return round(max(0.01 * spot, base * max(0.3, 1 - pct / 100)), 2)

    s = strategy.upper()
    atm  = round(spot)
    c1   = round(spot + em1)
    c2   = round(spot + em2)
    p1   = round(spot - em1)
    p2   = round(spot - em2)
    ac   = _prem(atm, True);  ap = _prem(atm, False)
    oc   = _prem(c1,  True);  op = _prem(p1, False)
    wc   = _prem(c2,  True);  wp_p = _prem(p2, False)

    mapping = {
        "LONG_CALL":         StrikeSet(s, atm, None, None, None, ac, 0, 0, 0, "estimated"),
        "BULL_CALL_SPREAD":  StrikeSet(s, atm, c1, None, None, ac, oc, 0, 0, "estimated"),
        "CASH_SECURED_PUT":  StrikeSet(s, None, None, None, p1, 0, 0, 0, op, "estimated"),
        "PUT_CREDIT_SPREAD": StrikeSet(s, None, None, p2, p1, 0, 0, wp_p, op, "estimated"),
        "RISK_REVERSAL":     StrikeSet(s, c1, None, None, p1, oc, 0, 0, op, "estimated"),
        "IRON_CONDOR":       StrikeSet(s, c2, c1, p2, p1, wc, oc, wp_p, op, "estimated"),
        "IRON_BUTTERFLY":    StrikeSet(s, c1, atm, p1, atm, oc, ac, op, ap, "estimated"),
        "SHORT_STRANGLE":    StrikeSet(s, None, c1, None, p1, 0, oc, 0, op, "estimated"),
        "LONG_STRADDLE":     StrikeSet(s, atm, None, atm, None, ac, 0, ap, 0, "estimated"),
        "LONG_STRANGLE":     StrikeSet(s, c1, None, p1, None, oc, 0, op, 0, "estimated"),
        "LONG_PUT":          StrikeSet(s, None, None, atm, None, 0, 0, ap, 0, "estimated"),
        "PUT_DEBIT_SPREAD":  StrikeSet(s, None, None, atm, p1, 0, 0, ap, op, "estimated"),
        "BEAR_CALL_SPREAD":  StrikeSet(s, c2, c1, None, None, wc, oc, 0, 0, "estimated"),
        "COVERED_CALL":      StrikeSet(s, None, c1, None, None, 0, oc, 0, 0, "estimated"),
    }

    return mapping.get(s, StrikeSet(s, None, None, None, None, 0, 0, 0, 0, "estimated"))
