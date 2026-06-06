"""
Option Strategy Selector Engine
=================================
Rule-based selector + composite ranking

RULES (in priority order):
  RULE 1  BULL + bull_prob > 60% + IV_rank < 30 + EV>0 + POP>55 → bull_call_spread
  RULE 2  BULL + bull_prob > 60% + IV_rank > 70 + EV>0          → cash_secured_put
  RULE 3  RANGE + IV_rank > 60                                   → iron_condor
  RULE 4  RANGE + IV_rank < 25                                   → long_straddle
  RULE 5  CORRECTION + IV_rank < 40                             → put_debit_spread
  RULE 6  BEAR + IV_rank < 30                                    → long_put
  RULE 7  BEAR + IV_rank > 60                                    → bear_call_spread

After rule selection, also evaluate ALL regime-appropriate candidates
and return top 3 by composite score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from options.expected_move_engine import ExpectedMoveResult
from options.strategy_definitions import (
    STRATEGY_BUILDERS,
    StrategyResult,
    long_call, bull_call_spread, cash_secured_put, put_credit_spread, risk_reversal,
    iron_condor, iron_butterfly, short_strangle, long_straddle, long_strangle,
    long_put, put_debit_spread, bear_call_spread, covered_call,
)

logger = logging.getLogger(__name__)

# Candidates to evaluate per regime
_REGIME_CANDIDATES: dict[str, list[str]] = {
    "STRONG_BULL": ["long_call", "bull_call_spread", "put_credit_spread", "risk_reversal", "cash_secured_put"],
    "BULL":        ["bull_call_spread", "cash_secured_put", "put_credit_spread", "long_call", "risk_reversal"],
    "RANGE":       ["iron_condor", "iron_butterfly", "short_strangle", "long_straddle", "long_strangle"],
    "CORRECTION":  ["put_debit_spread", "bear_call_spread", "long_put", "iron_condor"],
    "BEAR":        ["long_put", "bear_call_spread", "put_debit_spread", "covered_call"],
    "STRONG_BEAR": ["long_put", "put_debit_spread", "bear_call_spread", "long_strangle"],
}


@dataclass
class SelectionResult:
    rule_selected:   str                    # rule that fired, e.g. "RULE_1"
    primary:         StrategyResult         # top-ranked strategy
    top_3:           list[StrategyResult]   # top 3 by composite score
    candidates_eval: int                    # number of strategies evaluated
    regime:          str
    iv_rank:         float
    regime_conf:     float


def select_strategy(
    regime:      str,
    regime_conf: float,       # 0–100
    bull_prob:   float,       # 0–1
    iv_rank:     float,       # 0–100
    em:          ExpectedMoveResult,
    price:       float,
    iv:          float,
) -> SelectionResult:
    """
    Apply 7 rules then evaluate all regime-appropriate candidates.

    Parameters
    ----------
    regime       : current Markov regime
    regime_conf  : HMM confidence 0–100
    bull_prob    : probability of BULL state (from RegimeResult.regime_probs_all)
    iv_rank      : IV Rank 0–100
    em           : ExpectedMoveResult
    price        : current spot price
    iv           : annualised IV

    Returns
    -------
    SelectionResult with primary strategy + top 3 ranked
    """

    def build(name: str) -> StrategyResult:
        return STRATEGY_BUILDERS[name](em, price, iv, regime_conf)

    # ── Apply rules ───────────────────────────────────────────────────────────
    rule_name = "COMPOSITE_RANK"   # default: no hard rule fires, rank everything

    if regime in ("BULL", "STRONG_BULL"):
        if bull_prob > 0.60 and iv_rank < 30:
            rule_name = "RULE_1_BULL_LOW_IV"
        elif bull_prob > 0.60 and iv_rank > 70:
            rule_name = "RULE_2_BULL_HIGH_IV"

    elif regime == "RANGE":
        if iv_rank > 60:
            rule_name = "RULE_3_RANGE_HIGH_IV"
        elif iv_rank < 25:
            rule_name = "RULE_4_RANGE_LOW_IV"

    elif regime == "CORRECTION":
        if iv_rank < 40:
            rule_name = "RULE_5_CORRECTION"

    elif regime in ("BEAR", "STRONG_BEAR"):
        if iv_rank < 30:
            rule_name = "RULE_6_BEAR_LOW_IV"
        elif iv_rank > 60:
            rule_name = "RULE_7_BEAR_HIGH_IV"

    # ── Evaluate all regime candidates ────────────────────────────────────────
    candidate_names = _REGIME_CANDIDATES.get(regime, list(STRATEGY_BUILDERS.keys()))
    evaluated: list[StrategyResult] = []

    for name in candidate_names:
        try:
            s = build(name)
            # Filter: require EV > 0 and POP > 40
            if s.ev > 0 and s.pop > 40:
                evaluated.append(s)
        except Exception as exc:
            logger.debug("Strategy %s build failed: %s", name, exc)

    # Sort by composite score descending
    evaluated.sort(key=lambda s: s.composite_score, reverse=True)

    # Use rule-selected primary if it exists in evaluated, else use top composite
    rule_primary_map = {
        "RULE_1_BULL_LOW_IV":  "bull_call_spread",
        "RULE_2_BULL_HIGH_IV": "cash_secured_put",
        "RULE_3_RANGE_HIGH_IV": "iron_condor",
        "RULE_4_RANGE_LOW_IV": "long_straddle",
        "RULE_5_CORRECTION":   "put_debit_spread",
        "RULE_6_BEAR_LOW_IV":  "long_put",
        "RULE_7_BEAR_HIGH_IV": "bear_call_spread",
    }

    primary: StrategyResult | None = None
    if rule_name in rule_primary_map:
        target = rule_primary_map[rule_name]
        # Find in evaluated list; if EV/POP filter removed it, rebuild anyway
        primary = next((s for s in evaluated if s.name == target), None)
        if primary is None:
            try:
                primary = build(target)
                evaluated.insert(0, primary)
                evaluated.sort(key=lambda s: s.composite_score, reverse=True)
            except Exception:
                pass

    if primary is None and evaluated:
        primary = evaluated[0]

    if primary is None:
        # Ultimate fallback: force iron_condor if no candidates pass filters
        primary = build("iron_condor")
        evaluated = [primary]

    top_3 = evaluated[:3]

    logger.info(
        "Strategy selected: %s (rule=%s) | score=%.1f pop=%.1f ev=%.2f | candidates=%d",
        primary.display, rule_name, primary.composite_score,
        primary.pop, primary.ev, len(evaluated),
    )

    return SelectionResult(
        rule_selected   = rule_name,
        primary         = primary,
        top_3           = top_3,
        candidates_eval = len(candidate_names),
        regime          = regime,
        iv_rank         = iv_rank,
        regime_conf     = regime_conf,
    )
