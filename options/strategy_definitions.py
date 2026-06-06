"""
Option Strategy Definitions
============================
Defines all 14 supported strategies with:
  - Strike selection logic (using Expected Move bands)
  - Max Profit / Max Loss calculation
  - Breakeven formula
  - EV calculation: (POP × AvgWin) - ((1-POP) × AvgLoss)
  - Composite score: 30%EV + 25%POP + 20%Kelly + 15%RegimeConf + 10%RR

Supported strategies:

BULLISH:
  long_call            — Buy ATM call
  bull_call_spread     — Buy ATM call, Sell OTM call (+1 SD)
  cash_secured_put     — Sell OTM put (-0.5 SD), hold cash
  put_credit_spread    — Sell OTM put, Buy further OTM put (wing)
  risk_reversal        — Sell OTM put, Buy OTM call

NEUTRAL:
  iron_condor          — Sell ±1 SD, Buy ±1.5 SD
  iron_butterfly       — Sell ATM both sides, Buy ±1 SD
  short_strangle       — Sell ±1 SD (naked)
  long_straddle        — Buy ATM call + put
  long_strangle        — Buy OTM call + put (±1 SD)

BEARISH:
  long_put             — Buy ATM put
  put_debit_spread     — Buy ATM put, Sell OTM put (-1 SD)
  bear_call_spread     — Sell ATM call, Buy OTM call (+1 SD)
  covered_call         — Own stock, Sell OTM call (+0.5 SD)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from options.expected_move_engine import ExpectedMoveResult
from options.probability_engine import StrikeRange, quick_pop

logger = logging.getLogger(__name__)

STRATEGY_DIRECTION_MAP: dict[str, str] = {
    "long_call":         "LONG",
    "bull_call_spread":  "LONG",
    "cash_secured_put":  "LONG",
    "put_credit_spread": "LONG",
    "risk_reversal":     "LONG",
    "iron_condor":       "NEUTRAL",
    "iron_butterfly":    "NEUTRAL",
    "short_strangle":    "NEUTRAL",
    "long_straddle":     "NEUTRAL",
    "long_strangle":     "NEUTRAL",
    "long_put":          "SHORT",
    "put_debit_spread":  "SHORT",
    "bear_call_spread":  "SHORT",
    "covered_call":      "SHORT",
}


@dataclass
class StrategyResult:
    name:        str
    display:     str             # human-friendly name
    direction:   str             # LONG | SHORT | NEUTRAL
    strikes:     dict[str, float]
    max_profit:  float           # positive = profit (points)
    max_loss:    float           # positive = loss (points)
    breakeven:   float | list[float]
    pop:         float           # 0–100
    ev:          float           # Expected Value in points
    rr:          float           # max_profit / max_loss
    kelly:       float           # full Kelly fraction
    half_kelly:  float
    quarter_kelly: float
    composite_score: float       # 0–100 ranking score
    rationale:   str
    legs:        list[str]       = field(default_factory=list)


def _safe_rr(profit: float, loss: float) -> float:
    return round(profit / loss, 2) if loss > 0 else 0.0


def _kelly(pop_frac: float, rr: float) -> tuple[float, float, float]:
    """Full / Half / Quarter Kelly."""
    w = max(0.001, min(0.999, pop_frac))
    l = 1 - w
    r = max(0.01, rr)
    k = max(0.0, (w * r - l) / r)
    return round(k, 4), round(k * 0.5, 4), round(k * 0.25, 4)


def _ev(pop_frac: float, max_profit: float, max_loss: float) -> float:
    """EV = POP × AvgWin - (1-POP) × AvgLoss (in points)."""
    return round(pop_frac * max_profit - (1 - pop_frac) * max_loss, 2)


def _composite(
    ev: float,
    pop: float,
    kelly: float,
    regime_conf: float,
    rr: float,
    max_ev_ref: float = 50.0,
) -> float:
    """
    Composite score 0–100:
      30% EV (normalised)
      25% POP
      20% Kelly (normalised)
      15% Regime Confidence
      10% RR (normalised)
    """
    ev_score     = min(100.0, max(0.0, (ev / max_ev_ref) * 100)) if max_ev_ref > 0 else 0.0
    pop_score    = min(100.0, max(0.0, pop))
    kelly_score  = min(100.0, max(0.0, kelly * 400))   # Kelly 0.25 → 100
    regime_score = min(100.0, max(0.0, regime_conf))
    rr_score     = min(100.0, max(0.0, rr / 4.0 * 100))  # RR 4.0 → 100

    score = (
        ev_score     * 0.30
        + pop_score    * 0.25
        + kelly_score  * 0.20
        + regime_score * 0.15
        + rr_score     * 0.10
    )
    return round(score, 1)


# ──────────────────────────────────────────────────────────────────────────────
# BULLISH STRATEGIES
# ──────────────────────────────────────────────────────────────────────────────

def long_call(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    K    = round(price)
    pop  = quick_pop(price, K * 1.005, iv, em.dte, "LONG")    # profit if price > ATM (slightly above)
    prem = round(price * iv * math.sqrt(em.dte / 365) * 0.4, 2)  # rough ATM call price proxy
    mp   = float("inf")   # unlimited; cap at 5× premium for EV/RR
    ml   = prem
    rr   = _safe_rr(prem * 3, prem)                           # realistic expected gain
    ev   = _ev(pop / 100, prem * 3, prem)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="long_call", display="Long Call", direction="LONG",
        strikes={"buy_call": K},
        max_profit=prem * 3, max_loss=prem, breakeven=K + prem,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale="Unlimited upside, risk = premium paid",
        legs=[f"Buy {K} Call @~{prem}"],
    )


def bull_call_spread(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    buy_k  = round(price)
    sell_k = round(em.upper_1sd)
    width  = sell_k - buy_k
    # Rough premium: buy ATM costs ~0.35× width, sell OTM gets ~0.15× width
    net_debit = round(width * 0.35 - width * 0.15, 2)
    mp     = round(width - net_debit, 2)
    ml     = net_debit
    pop    = quick_pop(price, sell_k, iv, em.dte, "LONG")
    rr     = _safe_rr(mp, ml)
    ev     = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="bull_call_spread", display="Bull Call Spread", direction="LONG",
        strikes={"buy_call": buy_k, "sell_call": sell_k},
        max_profit=mp, max_loss=ml, breakeven=buy_k + net_debit,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Defined-risk bull play, max profit at {sell_k}+",
        legs=[f"Buy {buy_k} Call / Sell {sell_k} Call"],
    )


def cash_secured_put(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    sell_k = round(em.lower_1sd * 0.95)   # slightly below 1 SD
    prem   = round(price * iv * math.sqrt(em.dte / 365) * 0.20, 2)
    mp     = prem
    ml     = max(1.0, sell_k - prem)
    pop    = quick_pop(price, sell_k, iv, em.dte, "SHORT")
    rr     = _safe_rr(mp, ml)
    ev     = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="cash_secured_put", display="Cash Secured Put", direction="LONG",
        strikes={"sell_put": sell_k},
        max_profit=prem, max_loss=sell_k - prem, breakeven=sell_k - prem,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Collect premium, willing to own stock at {sell_k}",
        legs=[f"Sell {sell_k} Put @{prem}"],
    )


def put_credit_spread(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    sell_k = round(em.lower_1sd)
    buy_k  = round(em.lower_1_5sd)
    width  = sell_k - buy_k
    net_cr = round(width * 0.35, 2)
    mp     = net_cr
    ml     = round(width - net_cr, 2)
    pop    = quick_pop(price, sell_k, iv, em.dte, "SHORT")
    rr     = _safe_rr(mp, ml)
    ev     = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="put_credit_spread", display="Put Credit Spread", direction="LONG",
        strikes={"sell_put": sell_k, "buy_put": buy_k},
        max_profit=mp, max_loss=ml, breakeven=sell_k - net_cr,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Sell put credit spread: sell {sell_k}P / buy {buy_k}P",
        legs=[f"Sell {sell_k} Put / Buy {buy_k} Put"],
    )


def risk_reversal(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    buy_c  = round(em.upper_1sd)
    sell_p = round(em.lower_1sd)
    # Roughly zero net cost (put premium ≈ call premium at equidistant strikes)
    mp     = float("inf")
    ml     = sell_p
    pop    = quick_pop(price, buy_c, iv, em.dte, "LONG")
    rr     = _safe_rr(em.expected_move * 2, sell_p * 0.10)
    ev     = _ev(pop / 100, em.expected_move * 2, sell_p * 0.10)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="risk_reversal", display="Risk Reversal", direction="LONG",
        strikes={"buy_call": buy_c, "sell_put": sell_p},
        max_profit=em.expected_move * 2, max_loss=sell_p, breakeven=buy_c,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Sell {sell_p}P / Buy {buy_c}C — zero-cost bullish",
        legs=[f"Sell {sell_p} Put / Buy {buy_c} Call"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# NEUTRAL STRATEGIES
# ──────────────────────────────────────────────────────────────────────────────

def iron_condor(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    sc = round(em.upper_1sd)
    bc = round(em.upper_1_5sd)
    sp = round(em.lower_1sd)
    bp = round(em.lower_1_5sd)
    call_width = bc - sc
    put_width  = sp - bp
    net_cr = round((call_width + put_width) * 0.30, 2)
    ml     = round(max(call_width, put_width) - net_cr, 2)
    mp     = net_cr
    pop    = quick_pop(price, sc, iv, em.dte, "NEUTRAL")
    rr     = _safe_rr(mp, ml)
    ev     = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="iron_condor", display="Iron Condor", direction="NEUTRAL",
        strikes={"sell_call": sc, "buy_call": bc, "sell_put": sp, "buy_put": bp},
        max_profit=mp, max_loss=ml, breakeven=[sp - net_cr, sc + net_cr],
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Range play: profit if {sp}–{sc} at expiry",
        legs=[f"Sell {sc}C / Buy {bc}C / Sell {sp}P / Buy {bp}P"],
    )


def iron_butterfly(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    atm = round(price)
    wing = round(em.expected_move)
    bc  = atm + wing
    bp  = atm - wing
    net_cr = round(wing * 0.40, 2)
    ml     = round(wing - net_cr, 2)
    mp     = net_cr
    pop    = quick_pop(price, atm + wing * 0.3, iv, em.dte, "NEUTRAL")
    rr     = _safe_rr(mp, ml)
    ev     = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="iron_butterfly", display="Iron Butterfly", direction="NEUTRAL",
        strikes={"sell_call": atm, "buy_call": bc, "sell_put": atm, "buy_put": bp},
        max_profit=mp, max_loss=ml, breakeven=[atm - net_cr, atm + net_cr],
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Pin play: max profit if price pins at {atm}",
        legs=[f"Sell {atm}C / Buy {bc}C / Sell {atm}P / Buy {bp}P"],
    )


def short_strangle(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    sc   = round(em.upper_1sd)
    sp   = round(em.lower_1sd)
    prem = round(price * iv * math.sqrt(em.dte / 365) * 0.25, 2)
    mp   = prem
    ml   = price * 0.20   # uncapped but practically bounded
    pop  = quick_pop(price, sc, iv, em.dte, "NEUTRAL")
    rr   = _safe_rr(mp, ml)
    ev   = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="short_strangle", display="Short Strangle", direction="NEUTRAL",
        strikes={"sell_call": sc, "sell_put": sp},
        max_profit=prem, max_loss=ml, breakeven=[sp - prem, sc + prem],
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Collect premium selling ±1SD: {sp}P / {sc}C (NAKED — high risk)",
        legs=[f"Sell {sc} Call / Sell {sp} Put"],
    )


def long_straddle(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    atm  = round(price)
    prem = round(price * iv * math.sqrt(em.dte / 365) * 0.80, 2)
    ml   = prem
    mp   = float("inf")
    pop  = 100 - quick_pop(price, atm - prem * 0.5, iv, em.dte, "NEUTRAL")
    rr   = _safe_rr(em.expected_move * 1.5, prem)
    ev   = _ev(pop / 100, em.expected_move * 1.5, prem)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="long_straddle", display="Long Straddle", direction="NEUTRAL",
        strikes={"buy_call": atm, "buy_put": atm},
        max_profit=em.expected_move * 3, max_loss=prem, breakeven=[atm - prem, atm + prem],
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Buy volatility: profit if price moves >{prem:.1f} either way",
        legs=[f"Buy {atm} Call + {atm} Put @~{prem}"],
    )


def long_strangle(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    bc   = round(em.upper_1sd)
    bp   = round(em.lower_1sd)
    prem = round(price * iv * math.sqrt(em.dte / 365) * 0.50, 2)
    ml   = prem
    rr   = _safe_rr(em.expected_move * 2, prem)
    pop  = round((100 - quick_pop(price, bc, iv, em.dte, "NEUTRAL")) * 1.15, 1)
    ev   = _ev(pop / 100, em.expected_move * 2, prem)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="long_strangle", display="Long Strangle", direction="NEUTRAL",
        strikes={"buy_call": bc, "buy_put": bp},
        max_profit=em.expected_move * 3, max_loss=prem, breakeven=[bp - prem, bc + prem],
        pop=round(min(pop, 85.0), 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Cheaper straddle: buy {bp}P + {bc}C, need big move",
        legs=[f"Buy {bc} Call / Buy {bp} Put @~{prem}"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# BEARISH STRATEGIES
# ──────────────────────────────────────────────────────────────────────────────

def long_put(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    K    = round(price)
    prem = round(price * iv * math.sqrt(em.dte / 365) * 0.4, 2)
    mp   = round(K - prem, 2)
    ml   = prem
    pop  = quick_pop(price, K * 0.995, iv, em.dte, "SHORT")
    rr   = _safe_rr(prem * 3, prem)
    ev   = _ev(pop / 100, prem * 3, prem)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="long_put", display="Long Put", direction="SHORT",
        strikes={"buy_put": K},
        max_profit=mp, max_loss=prem, breakeven=K - prem,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale="Directional bearish, risk = premium paid",
        legs=[f"Buy {K} Put @~{prem}"],
    )


def put_debit_spread(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    buy_k  = round(price)
    sell_k = round(em.lower_1sd)
    width  = buy_k - sell_k
    net_db = round(width * 0.35, 2)
    mp     = round(width - net_db, 2)
    ml     = net_db
    pop    = quick_pop(price, sell_k, iv, em.dte, "SHORT")
    rr     = _safe_rr(mp, ml)
    ev     = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="put_debit_spread", display="Put Debit Spread", direction="SHORT",
        strikes={"buy_put": buy_k, "sell_put": sell_k},
        max_profit=mp, max_loss=ml, breakeven=buy_k - net_db,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Defined-risk bear play, max profit at {sell_k}",
        legs=[f"Buy {buy_k} Put / Sell {sell_k} Put"],
    )


def bear_call_spread(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    sell_k = round(em.upper_1sd * 0.98)
    buy_k  = round(em.upper_1_5sd)
    width  = buy_k - sell_k
    net_cr = round(width * 0.35, 2)
    mp     = net_cr
    ml     = round(width - net_cr, 2)
    pop    = quick_pop(price, sell_k, iv, em.dte, "SHORT")
    rr     = _safe_rr(mp, ml)
    ev     = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="bear_call_spread", display="Bear Call Spread", direction="SHORT",
        strikes={"sell_call": sell_k, "buy_call": buy_k},
        max_profit=mp, max_loss=ml, breakeven=sell_k + net_cr,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Sell call credit: sell {sell_k}C / buy {buy_k}C",
        legs=[f"Sell {sell_k} Call / Buy {buy_k} Call"],
    )


def covered_call(em: ExpectedMoveResult, price: float, iv: float, regime_conf: float) -> StrategyResult:
    sell_k = round(em.upper_1sd * 0.97)
    prem   = round(price * iv * math.sqrt(em.dte / 365) * 0.18, 2)
    mp     = round(sell_k - price + prem, 2)
    ml     = round(price - prem, 2)   # downside on stock ownership
    pop    = quick_pop(price, sell_k, iv, em.dte, "SHORT")
    rr     = _safe_rr(mp, ml)
    ev     = _ev(pop / 100, mp, ml)
    k, hk, qk = _kelly(pop / 100, rr)
    return StrategyResult(
        name="covered_call", display="Covered Call", direction="SHORT",
        strikes={"sell_call": sell_k},
        max_profit=mp, max_loss=ml, breakeven=price - prem,
        pop=round(pop, 1), ev=ev, rr=rr,
        kelly=k, half_kelly=hk, quarter_kelly=qk,
        composite_score=_composite(ev, pop, k, regime_conf, rr),
        rationale=f"Own stock, sell {sell_k}C to generate income",
        legs=[f"Own stock / Sell {sell_k} Call @{prem}"],
    )


# ──────────────────────────────────────────────────────────────────────────────
# REGISTRY  (name → builder function)
# ──────────────────────────────────────────────────────────────────────────────
STRATEGY_BUILDERS: dict = {
    "long_call":         long_call,
    "bull_call_spread":  bull_call_spread,
    "cash_secured_put":  cash_secured_put,
    "put_credit_spread": put_credit_spread,
    "risk_reversal":     risk_reversal,
    "iron_condor":       iron_condor,
    "iron_butterfly":    iron_butterfly,
    "short_strangle":    short_strangle,
    "long_straddle":     long_straddle,
    "long_strangle":     long_strangle,
    "long_put":          long_put,
    "put_debit_spread":  put_debit_spread,
    "bear_call_spread":  bear_call_spread,
    "covered_call":      covered_call,
}
