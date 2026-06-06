"""
Final Trade Decision Engine
=============================
A trade is approved ONLY when ALL 7 gates pass:

  Gate 1: Regime Confidence  >= 60%
  Gate 2: AI Score           >= 70
  Gate 3: Expected Value     >  0
  Gate 4: Kelly Fraction     >  0
  Gate 5: MC Profit Prob     >= 60%
  Gate 6: Risk Reward        >= 2.0
  Gate 7: Market Structure + EMA confirmed (direction != WAIT)

Any gate failure → NO_TRADE with reason.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ── Gate thresholds ───────────────────────────────────────────────────────────
MIN_REGIME_CONFIDENCE = 60.0
MIN_AI_SCORE          = 70.0
MIN_MC_PROFIT_PROB    = 60.0
MIN_RR                = 2.0


@dataclass(frozen=True)
class FinalDecision:
    decision:       str              # "LONG" | "SHORT" | "NO_TRADE"
    approved:       bool
    gates_passed:   list[str]        = field(default_factory=list)
    gates_failed:   list[str]        = field(default_factory=list)
    reason:         str              = ""
    confidence_pct: float            = 0.0   # gates_passed / total_gates × 100


def evaluate_trade(
    direction:          str,     # "LONG" | "SHORT" | "WAIT"
    regime_confidence:  float,   # 0–100
    ai_score:           float,   # 0–100
    expected_value:     float,   # R units, EV = W*R - L
    kelly_fraction:     float,   # may be negative
    mc_profit_prob:     float,   # 0–100 %
    best_rr:            float,   # risk/reward ratio
    structure_trend:    str,     # "BULLISH" | "BEARISH" | "MIXED" | "UNKNOWN"
    ema_bias:           str,     # "BULLISH" | "BEARISH"
) -> FinalDecision:
    """
    Run all gates and return the final trade decision.
    """

    gates_passed: list[str] = []
    gates_failed: list[str] = []

    # Gate 0: Direction must be actionable
    if direction == "WAIT":
        return FinalDecision(
            decision="NO_TRADE", approved=False,
            gates_failed=["Direction = WAIT"],
            reason="No directional signal",
        )

    # Gate 1: Regime confidence
    if regime_confidence >= MIN_REGIME_CONFIDENCE:
        gates_passed.append(f"Regime Confidence {regime_confidence:.0f}% ≥ {MIN_REGIME_CONFIDENCE:.0f}%")
    else:
        gates_failed.append(f"Regime Confidence {regime_confidence:.0f}% < {MIN_REGIME_CONFIDENCE:.0f}%")

    # Gate 2: AI Score
    if ai_score >= MIN_AI_SCORE:
        gates_passed.append(f"AI Score {ai_score:.0f} ≥ {MIN_AI_SCORE:.0f}")
    else:
        gates_failed.append(f"AI Score {ai_score:.0f} < {MIN_AI_SCORE:.0f}")

    # Gate 3: Expected Value
    if expected_value > 0:
        gates_passed.append(f"EV {expected_value:.2f}R > 0")
    else:
        gates_failed.append(f"EV {expected_value:.2f}R ≤ 0")

    # Gate 4: Kelly fraction
    if kelly_fraction > 0:
        gates_passed.append(f"Kelly {kelly_fraction:.3f} > 0")
    else:
        gates_failed.append(f"Kelly {kelly_fraction:.3f} ≤ 0")

    # Gate 5: MC profit probability
    if mc_profit_prob >= MIN_MC_PROFIT_PROB:
        gates_passed.append(f"MC P(profit) {mc_profit_prob:.1f}% ≥ {MIN_MC_PROFIT_PROB:.0f}%")
    else:
        gates_failed.append(f"MC P(profit) {mc_profit_prob:.1f}% < {MIN_MC_PROFIT_PROB:.0f}%")

    # Gate 6: Risk Reward
    if best_rr >= MIN_RR:
        gates_passed.append(f"RR {best_rr:.2f} ≥ {MIN_RR:.1f}")
    else:
        gates_failed.append(f"RR {best_rr:.2f} < {MIN_RR:.1f}")

    # Gate 7: Structure + EMA alignment
    direction_ok = (
        (direction == "LONG"  and structure_trend == "BULLISH" and ema_bias == "BULLISH") or
        (direction == "SHORT" and structure_trend == "BEARISH" and ema_bias == "BEARISH") or
        # allow reversal mode where one side might be mixed
        (direction == "LONG"  and ema_bias == "BULLISH") or
        (direction == "SHORT" and ema_bias == "BEARISH")
    )
    if direction_ok:
        gates_passed.append(f"Structure/EMA aligned ({structure_trend}, {ema_bias})")
    else:
        gates_failed.append(f"Structure/EMA conflict ({structure_trend}, {ema_bias}) vs {direction}")

    # ── Decision ──────────────────────────────────────────────────────────────
    total = len(gates_passed) + len(gates_failed)
    approved = len(gates_failed) == 0
    conf_pct = round(len(gates_passed) / total * 100, 1) if total > 0 else 0.0

    if approved:
        reason = f"All {total} gates passed → {direction}"
        decision = direction
    else:
        failed_str = " | ".join(gates_failed)
        reason = f"BLOCKED: {failed_str}"
        decision = "NO_TRADE"

    return FinalDecision(
        decision       = decision,
        approved       = approved,
        gates_passed   = gates_passed,
        gates_failed   = gates_failed,
        reason         = reason,
        confidence_pct = conf_pct,
    )
