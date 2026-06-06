"""
Option Strategy Engine
=======================
สองฟังก์ชัน:

1. generate_option_trade(price, regime, atr)
   — Legacy: ใช้ regime อย่างเดียว (ยังคงไว้ backward compat)

2. generate_option_trade_v2(price, direction, regime, iv_env, dominant_dte, atr)
   — NEW: ใช้ direction จาก FuturesOrchestrator (7-gate approved)
          ผสม IV environment จาก Greek chain
          เลือก strikes จาก dominant DTE

เกณฑ์การเลือก Strategy
-----------------------
direction=LONG  + HIGH_IV  → BULL_CALL_SPREAD    (premium แพง, spread ดีกว่า naked)
direction=LONG  + NORMAL   → BULL_CALL_SPREAD
direction=LONG  + LOW_IV   → LONG_CALL           (premium ถูก, buy naked ดีกว่า)
direction=SHORT + HIGH_IV  → BEAR_CALL_SPREAD    (short premium)
direction=SHORT + NORMAL   → PUT_DEBIT_SPREAD
direction=SHORT + LOW_IV   → LONG_PUT
direction=NO_TRADE + HIGH_IV → IRON_CONDOR      (earn theta ใน high IV)
direction=NO_TRADE + LOW_IV  → NO_TRADE
direction=NO_TRADE + NORMAL  → NO_TRADE

Strike selection:
  ATM = current price (rounded to nearest 5 for stocks)
  LONG:  buy_call=ATM, sell_call=ATM+5% (spread width ≈ 1 ATR)
  SHORT: buy_put=ATM,  sell_put=ATM-5%
  IRON_CONDOR: sell_call=ATM+5%, buy_call=ATM+8%
               sell_put=ATM-5%,  buy_put=ATM-8%
  POP (Probability of Profit) estimated from spread width vs premium
"""

from __future__ import annotations
import math


def _round_strike(price: float, tick: float = 1.0) -> int:
    """Round to nearest tick (default 1.0 for general use)."""
    return round(price / tick) * int(tick)


def _atm(price: float) -> int:
    return _round_strike(price)


# ──────────────────────────────────────────────────────────────────────────────
# V1 — legacy (regime only)
# ──────────────────────────────────────────────────────────────────────────────
def generate_option_trade(price: float, regime: str, atr: float) -> dict:
    """Legacy option strategy from regime only. Kept for backward compatibility."""
    return generate_option_trade_v2(
        price        = price,
        direction    = "LONG" if regime in ("STRONG_BULL", "BULL") else
                       "SHORT" if regime in ("STRONG_BEAR", "BEAR") else "NO_TRADE",
        regime       = regime,
        iv_env       = "NORMAL_IV",
        dominant_dte = 30,
        atr          = atr,
    )


# ──────────────────────────────────────────────────────────────────────────────
# V2 — unified (direction from 7-gate + IV env from Greeks)
# ──────────────────────────────────────────────────────────────────────────────
def generate_option_trade_v2(
    price:        float,
    direction:    str,   # LONG | SHORT | NO_TRADE
    regime:       str,
    iv_env:       str,   # HIGH_IV | NORMAL_IV | LOW_IV
    dominant_dte: int,
    atr:          float,
) -> dict:
    """
    Build option trade recommendation aligned with the futures signal direction.

    Parameters
    ----------
    price        : current spot price
    direction    : futures trade direction (LONG | SHORT | NO_TRADE)
    regime       : HMM regime string
    iv_env       : IV environment from Greek aggregation
    dominant_dte : DTE bucket with highest OI
    atr          : ATR-14 value

    Returns
    -------
    Flat dict with: strategy, rationale, direction, buy_call, sell_call,
                    buy_put, sell_put, dte, pop, entry, target, max_profit_est,
                    max_loss_est, breakeven
    """

    atm    = _atm(price)
    spread = max(1, _atm(price * 0.05))   # ≈ 5% spread width
    wing   = max(1, _atm(price * 0.03))   # iron condor wing

    # ── LONG direction ────────────────────────────────────────────────────────
    if direction == "LONG":
        if iv_env == "LOW_IV":
            # Buy outright call — cheap premium environment
            strategy  = "LONG_CALL"
            rationale = "Direction=LONG + Low IV → Buy naked call (cheap premium)"
            buy_call  = atm
            sell_call = None
            pop       = 45
            target    = atm + spread * 2
            max_profit = "Unlimited"
            max_loss   = f"Premium paid"
            breakeven  = atm   # approx (actual = strike + premium)
        else:
            # Bull Call Spread — reduce premium cost in normal/high IV
            strategy   = "BULL_CALL_SPREAD"
            rationale  = f"Direction=LONG + {iv_env} → Bull Call Spread (limit debit)"
            buy_call   = atm
            sell_call  = atm + spread
            pop        = 58 if iv_env == "NORMAL_IV" else 55
            target     = atm + spread
            max_profit = f"{sell_call - buy_call} pts"
            max_loss   = "Net debit paid"
            breakeven  = atm   # approx

        return {
            "strategy":      strategy,
            "rationale":     rationale,
            "direction":     "BULLISH",
            "buy_call":      buy_call,
            "sell_call":     sell_call,
            "buy_put":       None,
            "sell_put":      None,
            "dte":           dominant_dte,
            "pop":           pop,
            "entry":         atm,
            "target":        target,
            "max_profit":    max_profit,
            "max_loss":      max_loss,
            "breakeven":     breakeven,
        }

    # ── SHORT direction ───────────────────────────────────────────────────────
    if direction == "SHORT":
        if iv_env == "HIGH_IV":
            # Bear Call Spread — collect premium in high IV
            strategy   = "BEAR_CALL_SPREAD"
            rationale  = "Direction=SHORT + High IV → Bear Call Spread (collect premium)"
            buy_call   = atm + spread
            sell_call  = atm
            buy_put    = None
            sell_put   = None
            pop        = 60
        elif iv_env == "LOW_IV":
            # Long Put — cheap
            strategy   = "LONG_PUT"
            rationale  = "Direction=SHORT + Low IV → Buy naked put (cheap premium)"
            buy_call   = None
            sell_call  = None
            buy_put    = atm
            sell_put   = None
            pop        = 45
        else:
            # Put Debit Spread
            strategy   = "PUT_DEBIT_SPREAD"
            rationale  = "Direction=SHORT + Normal IV → Put Debit Spread"
            buy_call   = None
            sell_call  = None
            buy_put    = atm
            sell_put   = atm - spread
            pop        = 55

        target = atm - spread * 2

        return {
            "strategy":   strategy,
            "rationale":  rationale,
            "direction":  "BEARISH",
            "buy_call":   buy_call,
            "sell_call":  sell_call,
            "buy_put":    buy_put,
            "sell_put":   sell_put,
            "dte":        dominant_dte,
            "pop":        pop,
            "entry":      atm,
            "target":     target,
            "max_profit": f"{spread} pts (spread)" if sell_put or sell_call else "Unlimited",
            "max_loss":   "Net debit paid" if buy_put and not sell_put else f"{spread} pts",
            "breakeven":  atm,
        }

    # ── NO_TRADE / WAIT ───────────────────────────────────────────────────────
    if iv_env == "HIGH_IV":
        # Iron Condor — sell premium when market is neutral + IV is high
        strategy   = "IRON_CONDOR"
        rationale  = "No direction + High IV → Iron Condor (sell premium both sides)"
        pop        = 68

        return {
            "strategy":   strategy,
            "rationale":  rationale,
            "direction":  "NEUTRAL",
            "buy_call":   atm + spread + wing,
            "sell_call":  atm + spread,
            "buy_put":    atm - spread - wing,
            "sell_put":   atm - spread,
            "dte":        dominant_dte or 45,
            "pop":        pop,
            "entry":      atm,
            "target":     atm,
            "max_profit": f"{spread} pts (net credit)",
            "max_loss":   f"{wing} pts",
            "breakeven":  f"{atm - spread}–{atm + spread}",
        }

    # Truly no trade
    return {
        "strategy":   "NO_TRADE",
        "rationale":  f"direction={direction}  iv_env={iv_env} → no suitable setup",
        "direction":  "NEUTRAL",
        "buy_call":   None, "sell_call": None,
        "buy_put":    None, "sell_put":  None,
        "dte":        0, "pop": 0,
        "entry":      atm, "target": atm,
        "max_profit": "0", "max_loss": "0",
        "breakeven":  atm,
    }
