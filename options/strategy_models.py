"""
Option Strategy Models
========================
Dataclasses and max-profit / max-loss / breakeven calculations
for all 14 supported strategies.

Each strategy model:
  - Takes exact strike prices + premium
  - Returns max_profit, max_loss, breakeven(s), theoretical_pop
  - No IV or MC dependency — pure payoff math

Used by:
  - ev_engine.py   (to compute EV per strategy)
  - selection_engine.py (to display trade setup)
  - formatter / sheet writer

Strategies supported:
  Bullish:  LONG_CALL, BULL_CALL_SPREAD, CASH_SECURED_PUT,
            PUT_CREDIT_SPREAD, RISK_REVERSAL
  Neutral:  IRON_CONDOR, IRON_BUTTERFLY, SHORT_STRANGLE,
            LONG_STRADDLE, LONG_STRANGLE
  Bearish:  LONG_PUT, PUT_DEBIT_SPREAD, BEAR_CALL_SPREAD, COVERED_CALL
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategySetup:
    """Complete description of one option strategy position."""
    name:          str
    direction:     str               # "BULLISH" | "NEUTRAL" | "BEARISH"
    legs:          list[dict]        # each: {type, action, strike, premium, qty}

    # Payoff metrics
    max_profit:    float             # positive = credit received / max gain
    max_loss:      float             # positive = maximum dollar loss
    breakevens:    list[float]       # price(s) at which P&L = 0
    net_premium:   float             # positive = credit, negative = debit

    # Probability & sizing
    pop:           float             # 0–100
    ev:            float             # Expected Value in $ (filled later)
    rr:            float             # max_profit / max_loss
    kelly:         float             # Kelly fraction (filled later)
    half_kelly:    float             # Kelly × 0.5
    quarter_kelly: float             # Kelly × 0.25

    # Meta
    dte:           int
    strike_summary: str              # human-readable e.g. "Buy 195C / Sell 200C"
    regime_fit:    str               # which regime this strategy fits
    score:         float = 0.0      # composite score (filled by selection engine)
    rationale:     str   = ""


# ──────────────────────────────────────────────────────────────────────────────
# STRATEGY BUILDERS
# Each function returns a partially-filled StrategySetup (ev/kelly filled later)
# ──────────────────────────────────────────────────────────────────────────────

def build_long_call(spot: float, strike: float, premium: float, dte: int) -> StrategySetup:
    max_profit = math.inf
    max_loss   = premium
    be         = strike + premium
    rr         = 0   # unlimited profit
    return StrategySetup(
        name="LONG_CALL", direction="BULLISH",
        legs=[{"type":"call","action":"buy","strike":strike,"premium":premium,"qty":1}],
        max_profit=max_profit, max_loss=max_loss,
        breakevens=[round(be,2)], net_premium=-premium,
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte, strike_summary=f"Buy {strike:.0f}C",
        regime_fit="BULL/STRONG_BULL",
    )


def build_bull_call_spread(
    spot: float, buy_strike: float, sell_strike: float,
    buy_prem: float, sell_prem: float, dte: int,
) -> StrategySetup:
    net_debit  = buy_prem - sell_prem
    max_profit = (sell_strike - buy_strike) - net_debit
    max_loss   = net_debit
    be         = buy_strike + net_debit
    rr         = round(max_profit / max_loss, 2) if max_loss > 0 else 0
    return StrategySetup(
        name="BULL_CALL_SPREAD", direction="BULLISH",
        legs=[
            {"type":"call","action":"buy","strike":buy_strike,"premium":buy_prem,"qty":1},
            {"type":"call","action":"sell","strike":sell_strike,"premium":sell_prem,"qty":1},
        ],
        max_profit=round(max_profit,2), max_loss=round(max_loss,2),
        breakevens=[round(be,2)], net_premium=round(-net_debit,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte,
        strike_summary=f"Buy {buy_strike:.0f}C / Sell {sell_strike:.0f}C",
        regime_fit="BULL",
    )


def build_cash_secured_put(spot: float, strike: float, premium: float, dte: int) -> StrategySetup:
    max_profit = premium
    max_loss   = strike - premium   # assigned at strike, premium offsets
    be         = strike - premium
    rr         = round(max_profit / max_loss, 3) if max_loss > 0 else 0
    return StrategySetup(
        name="CASH_SECURED_PUT", direction="BULLISH",
        legs=[{"type":"put","action":"sell","strike":strike,"premium":premium,"qty":1}],
        max_profit=round(max_profit,2), max_loss=round(max_loss,2),
        breakevens=[round(be,2)], net_premium=round(premium,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte, strike_summary=f"Sell {strike:.0f}P (CSP)",
        regime_fit="BULL (high IV)",
    )


def build_put_credit_spread(
    spot: float, sell_strike: float, buy_strike: float,
    sell_prem: float, buy_prem: float, dte: int,
) -> StrategySetup:
    net_credit = sell_prem - buy_prem
    max_profit = net_credit
    max_loss   = (sell_strike - buy_strike) - net_credit
    be         = sell_strike - net_credit
    rr         = round(max_profit / max_loss, 3) if max_loss > 0 else 0
    return StrategySetup(
        name="PUT_CREDIT_SPREAD", direction="BULLISH",
        legs=[
            {"type":"put","action":"sell","strike":sell_strike,"premium":sell_prem,"qty":1},
            {"type":"put","action":"buy","strike":buy_strike,"premium":buy_prem,"qty":1},
        ],
        max_profit=round(max_profit,2), max_loss=round(max_loss,2),
        breakevens=[round(be,2)], net_premium=round(net_credit,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte,
        strike_summary=f"Sell {sell_strike:.0f}P / Buy {buy_strike:.0f}P",
        regime_fit="BULL (high IV)",
    )


def build_risk_reversal(
    spot: float, sell_put_strike: float, buy_call_strike: float,
    put_prem: float, call_prem: float, dte: int,
) -> StrategySetup:
    net = put_prem - call_prem   # usually small debit or credit
    max_profit = math.inf
    max_loss   = sell_put_strike - abs(net)
    be_up      = buy_call_strike + max(0, -net)
    be_dn      = sell_put_strike - max(0, net)
    return StrategySetup(
        name="RISK_REVERSAL", direction="BULLISH",
        legs=[
            {"type":"put","action":"sell","strike":sell_put_strike,"premium":put_prem,"qty":1},
            {"type":"call","action":"buy","strike":buy_call_strike,"premium":call_prem,"qty":1},
        ],
        max_profit=max_profit, max_loss=round(max_loss,2),
        breakevens=[round(be_dn,2), round(be_up,2)], net_premium=round(net,2),
        pop=0, ev=0, rr=0, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte,
        strike_summary=f"Sell {sell_put_strike:.0f}P / Buy {buy_call_strike:.0f}C",
        regime_fit="STRONG_BULL",
    )


def build_iron_condor(
    spot: float,
    sell_call: float, buy_call: float,
    sell_put:  float, buy_put:  float,
    sc_prem: float, bc_prem: float,
    sp_prem: float, bp_prem: float,
    dte: int,
) -> StrategySetup:
    net_credit = (sc_prem + sp_prem) - (bc_prem + bp_prem)
    call_width = buy_call - sell_call
    put_width  = sell_put - buy_put
    max_loss   = max(call_width, put_width) - net_credit
    be_up      = sell_call + net_credit
    be_dn      = sell_put  - net_credit
    rr         = round(net_credit / max_loss, 3) if max_loss > 0 else 0
    return StrategySetup(
        name="IRON_CONDOR", direction="NEUTRAL",
        legs=[
            {"type":"call","action":"sell","strike":sell_call,"premium":sc_prem,"qty":1},
            {"type":"call","action":"buy", "strike":buy_call, "premium":bc_prem,"qty":1},
            {"type":"put", "action":"sell","strike":sell_put, "premium":sp_prem,"qty":1},
            {"type":"put", "action":"buy", "strike":buy_put,  "premium":bp_prem,"qty":1},
        ],
        max_profit=round(net_credit,2), max_loss=round(max_loss,2),
        breakevens=[round(be_dn,2), round(be_up,2)], net_premium=round(net_credit,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte,
        strike_summary=(f"Sell {sell_call:.0f}C/{sell_put:.0f}P "
                        f"Buy {buy_call:.0f}C/{buy_put:.0f}P"),
        regime_fit="RANGE (high IV)",
    )


def build_iron_butterfly(
    spot: float, atm: float,
    wing_call: float, wing_put: float,
    sell_call_prem: float, sell_put_prem: float,
    buy_call_prem: float,  buy_put_prem: float,
    dte: int,
) -> StrategySetup:
    net_credit = (sell_call_prem + sell_put_prem) - (buy_call_prem + buy_put_prem)
    wing_width = wing_call - atm
    max_loss   = wing_width - net_credit
    rr         = round(net_credit / max_loss, 3) if max_loss > 0 else 0
    return StrategySetup(
        name="IRON_BUTTERFLY", direction="NEUTRAL",
        legs=[
            {"type":"call","action":"sell","strike":atm,      "premium":sell_call_prem,"qty":1},
            {"type":"put", "action":"sell","strike":atm,      "premium":sell_put_prem,"qty":1},
            {"type":"call","action":"buy", "strike":wing_call,"premium":buy_call_prem,"qty":1},
            {"type":"put", "action":"buy", "strike":wing_put, "premium":buy_put_prem,"qty":1},
        ],
        max_profit=round(net_credit,2), max_loss=round(max_loss,2),
        breakevens=[round(atm - net_credit,2), round(atm + net_credit,2)],
        net_premium=round(net_credit,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte, strike_summary=f"Iron Butterfly @ {atm:.0f}",
        regime_fit="RANGE",
    )


def build_short_strangle(
    spot: float, sell_call: float, sell_put: float,
    call_prem: float, put_prem: float, dte: int,
) -> StrategySetup:
    net_credit = call_prem + put_prem
    max_profit = net_credit
    max_loss   = math.inf
    rr         = 0
    return StrategySetup(
        name="SHORT_STRANGLE", direction="NEUTRAL",
        legs=[
            {"type":"call","action":"sell","strike":sell_call,"premium":call_prem,"qty":1},
            {"type":"put", "action":"sell","strike":sell_put, "premium":put_prem,"qty":1},
        ],
        max_profit=round(max_profit,2), max_loss=max_loss,
        breakevens=[round(sell_put - net_credit,2), round(sell_call + net_credit,2)],
        net_premium=round(net_credit,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte, strike_summary=f"Sell {sell_call:.0f}C / Sell {sell_put:.0f}P",
        regime_fit="RANGE (high IV)",
    )


def build_long_straddle(
    spot: float, atm: float,
    call_prem: float, put_prem: float, dte: int,
) -> StrategySetup:
    total_debit = call_prem + put_prem
    max_profit  = math.inf
    max_loss    = total_debit
    return StrategySetup(
        name="LONG_STRADDLE", direction="NEUTRAL",
        legs=[
            {"type":"call","action":"buy","strike":atm,"premium":call_prem,"qty":1},
            {"type":"put", "action":"buy","strike":atm,"premium":put_prem, "qty":1},
        ],
        max_profit=max_profit, max_loss=round(max_loss,2),
        breakevens=[round(atm - total_debit,2), round(atm + total_debit,2)],
        net_premium=round(-total_debit,2),
        pop=0, ev=0, rr=0, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte, strike_summary=f"Buy {atm:.0f} Straddle",
        regime_fit="RANGE (low IV, pre-event)",
    )


def build_long_strangle(
    spot: float, buy_call: float, buy_put: float,
    call_prem: float, put_prem: float, dte: int,
) -> StrategySetup:
    total_debit = call_prem + put_prem
    max_profit  = math.inf
    max_loss    = total_debit
    return StrategySetup(
        name="LONG_STRANGLE", direction="NEUTRAL",
        legs=[
            {"type":"call","action":"buy","strike":buy_call,"premium":call_prem,"qty":1},
            {"type":"put", "action":"buy","strike":buy_put, "premium":put_prem, "qty":1},
        ],
        max_profit=max_profit, max_loss=round(max_loss,2),
        breakevens=[round(buy_put - total_debit,2), round(buy_call + total_debit,2)],
        net_premium=round(-total_debit,2),
        pop=0, ev=0, rr=0, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte, strike_summary=f"Buy {buy_call:.0f}C / {buy_put:.0f}P",
        regime_fit="RANGE (low IV)",
    )


def build_long_put(spot: float, strike: float, premium: float, dte: int) -> StrategySetup:
    max_profit = strike - premium
    max_loss   = premium
    be         = strike - premium
    rr         = round(max_profit / max_loss, 2) if max_loss > 0 else 0
    return StrategySetup(
        name="LONG_PUT", direction="BEARISH",
        legs=[{"type":"put","action":"buy","strike":strike,"premium":premium,"qty":1}],
        max_profit=round(max_profit,2), max_loss=round(max_loss,2),
        breakevens=[round(be,2)], net_premium=round(-premium,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte, strike_summary=f"Buy {strike:.0f}P",
        regime_fit="BEAR/STRONG_BEAR (low IV)",
    )


def build_put_debit_spread(
    spot: float, buy_strike: float, sell_strike: float,
    buy_prem: float, sell_prem: float, dte: int,
) -> StrategySetup:
    net_debit  = buy_prem - sell_prem
    max_profit = (buy_strike - sell_strike) - net_debit
    max_loss   = net_debit
    be         = buy_strike - net_debit
    rr         = round(max_profit / max_loss, 2) if max_loss > 0 else 0
    return StrategySetup(
        name="PUT_DEBIT_SPREAD", direction="BEARISH",
        legs=[
            {"type":"put","action":"buy", "strike":buy_strike, "premium":buy_prem, "qty":1},
            {"type":"put","action":"sell","strike":sell_strike,"premium":sell_prem,"qty":1},
        ],
        max_profit=round(max_profit,2), max_loss=round(max_loss,2),
        breakevens=[round(be,2)], net_premium=round(-net_debit,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte,
        strike_summary=f"Buy {buy_strike:.0f}P / Sell {sell_strike:.0f}P",
        regime_fit="BEAR/CORRECTION",
    )


def build_bear_call_spread(
    spot: float, sell_strike: float, buy_strike: float,
    sell_prem: float, buy_prem: float, dte: int,
) -> StrategySetup:
    net_credit = sell_prem - buy_prem
    max_profit = net_credit
    max_loss   = (buy_strike - sell_strike) - net_credit
    be         = sell_strike + net_credit
    rr         = round(max_profit / max_loss, 3) if max_loss > 0 else 0
    return StrategySetup(
        name="BEAR_CALL_SPREAD", direction="BEARISH",
        legs=[
            {"type":"call","action":"sell","strike":sell_strike,"premium":sell_prem,"qty":1},
            {"type":"call","action":"buy", "strike":buy_strike, "premium":buy_prem, "qty":1},
        ],
        max_profit=round(max_profit,2), max_loss=round(max_loss,2),
        breakevens=[round(be,2)], net_premium=round(net_credit,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte,
        strike_summary=f"Sell {sell_strike:.0f}C / Buy {buy_strike:.0f}C",
        regime_fit="BEAR (high IV)",
    )


def build_covered_call(
    spot: float, sell_strike: float, premium: float, dte: int,
) -> StrategySetup:
    max_profit = (sell_strike - spot) + premium
    max_loss   = spot - premium   # price drops to 0
    be         = spot - premium
    rr         = round(max_profit / max_loss, 3) if max_loss > 0 else 0
    return StrategySetup(
        name="COVERED_CALL", direction="BEARISH",
        legs=[
            {"type":"stock","action":"long","strike":spot,"premium":spot,"qty":1},
            {"type":"call","action":"sell","strike":sell_strike,"premium":premium,"qty":1},
        ],
        max_profit=round(max_profit,2), max_loss=round(max_loss,2),
        breakevens=[round(be,2)], net_premium=round(premium,2),
        pop=0, ev=0, rr=rr, kelly=0, half_kelly=0, quarter_kelly=0,
        dte=dte, strike_summary=f"Long Stock + Sell {sell_strike:.0f}C",
        regime_fit="BEAR/RANGE",
    )
