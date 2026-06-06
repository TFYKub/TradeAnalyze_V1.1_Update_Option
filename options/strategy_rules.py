"""
Strategy Selection Rules Engine
=================================
7 Rule-Based conditions mapping Regime × IV Rank → Best strategy

Rule evaluation order:
  1. BULL + low IV    → BULL_CALL_SPREAD
  2. BULL + high IV   → CASH_SECURED_PUT
  3. RANGE + high IV  → IRON_CONDOR
  4. RANGE + low IV   → LONG_STRADDLE
  5. CORRECTION       → PUT_DEBIT_SPREAD (if IV < 40)
  6. BEAR + low IV    → LONG_PUT
  7. BEAR + high IV   → BEAR_CALL_SPREAD

Each rule has required conditions and generates a ranked candidate list.
All candidates are evaluated even when a rule matches — the top 3
are returned by composite score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuleMatch:
    rule_id:   int
    rule_name: str
    matched:   bool
    reason:    str
    candidates: list[str]   # strategy names to build and score


# ──────────────────────────────────────────────────────────────────────────────
# RULES
# ──────────────────────────────────────────────────────────────────────────────
_RULES: list[dict] = [
    {
        "id": 1,
        "name": "Bull + Low IV → Debit Spread",
        "conditions": {
            "regime": {"BULL", "STRONG_BULL"},
            "bull_prob_min": 0.55,
            "iv_rank_max": 35,
            "ev_positive": True,
            "pop_min": 55,
        },
        "primary": "BULL_CALL_SPREAD",
        "candidates": ["BULL_CALL_SPREAD", "LONG_CALL", "RISK_REVERSAL"],
    },
    {
        "id": 2,
        "name": "Bull + High IV → Credit Strategy",
        "conditions": {
            "regime": {"BULL", "STRONG_BULL"},
            "bull_prob_min": 0.55,
            "iv_rank_min": 65,
            "ev_positive": True,
        },
        "primary": "CASH_SECURED_PUT",
        "candidates": ["CASH_SECURED_PUT", "PUT_CREDIT_SPREAD", "BULL_CALL_SPREAD"],
    },
    {
        "id": 3,
        "name": "Range + High IV → Iron Condor",
        "conditions": {
            "regime": {"RANGE", "CORRECTION"},
            "iv_rank_min": 55,
        },
        "primary": "IRON_CONDOR",
        "candidates": ["IRON_CONDOR", "IRON_BUTTERFLY", "SHORT_STRANGLE"],
    },
    {
        "id": 4,
        "name": "Range + Low IV → Long Vol",
        "conditions": {
            "regime": {"RANGE", "CORRECTION"},
            "iv_rank_max": 30,
        },
        "primary": "LONG_STRADDLE",
        "candidates": ["LONG_STRADDLE", "LONG_STRANGLE"],
    },
    {
        "id": 5,
        "name": "Correction + Moderate IV → Debit Spread",
        "conditions": {
            "regime": {"CORRECTION"},
            "iv_rank_max": 45,
        },
        "primary": "PUT_DEBIT_SPREAD",
        "candidates": ["PUT_DEBIT_SPREAD", "LONG_PUT", "BEAR_CALL_SPREAD"],
    },
    {
        "id": 6,
        "name": "Bear + Low IV → Long Put",
        "conditions": {
            "regime": {"BEAR", "STRONG_BEAR"},
            "iv_rank_max": 35,
        },
        "primary": "LONG_PUT",
        "candidates": ["LONG_PUT", "PUT_DEBIT_SPREAD", "BEAR_CALL_SPREAD"],
    },
    {
        "id": 7,
        "name": "Bear + High IV → Bear Credit Spread",
        "conditions": {
            "regime": {"BEAR", "STRONG_BEAR"},
            "iv_rank_min": 60,
        },
        "primary": "BEAR_CALL_SPREAD",
        "candidates": ["BEAR_CALL_SPREAD", "PUT_CREDIT_SPREAD", "COVERED_CALL"],
    },
]


def evaluate_rules(
    regime:      str,
    regime_prob: float,   # probability of current regime (0–1)
    iv_rank:     float,   # 0–100
) -> list[RuleMatch]:
    """
    Evaluate all 7 rules and return list of matches (may be more than one).

    Parameters
    ----------
    regime      : HMM regime string
    regime_prob : probability of current regime (0–1)
    iv_rank     : IV Rank 0–100

    Returns
    -------
    All matching RuleMatch objects, sorted by rule id.
    """

    matches: list[RuleMatch] = []

    for rule in _RULES:
        cond = rule["conditions"]

        # Regime check
        if regime not in cond.get("regime", set()):
            continue

        # Probability check
        if "bull_prob_min" in cond and regime_prob < cond["bull_prob_min"]:
            continue

        # IV rank checks
        if "iv_rank_min" in cond and iv_rank < cond["iv_rank_min"]:
            continue
        if "iv_rank_max" in cond and iv_rank > cond["iv_rank_max"]:
            continue

        reason = (
            f"Rule {rule['id']}: {rule['name']} | "
            f"regime={regime} regime_prob={regime_prob:.0%} iv_rank={iv_rank:.0f}"
        )
        matches.append(RuleMatch(
            rule_id    = rule["id"],
            rule_name  = rule["name"],
            matched    = True,
            reason     = reason,
            candidates = rule["candidates"],
        ))

    return matches


def get_candidate_strategies(
    regime:      str,
    regime_prob: float,
    iv_rank:     float,
) -> tuple[list[str], list[RuleMatch]]:
    """
    Return (candidate_strategy_names, matched_rules).

    Merges candidates from all matching rules, deduplicates while
    preserving priority order (first rule's primary strategy first).
    """

    matches = evaluate_rules(regime, regime_prob, iv_rank)

    if not matches:
        # Fallback: return broadly applicable set
        logger.warning(
            "No rules matched (regime=%s iv_rank=%.0f) — using fallback candidates",
            regime, iv_rank,
        )
        fallback = ["BULL_CALL_SPREAD", "IRON_CONDOR", "LONG_PUT"]
        return fallback, []

    seen: set[str] = set()
    ordered: list[str] = []
    for m in matches:
        for s in m.candidates:
            if s not in seen:
                seen.add(s)
                ordered.append(s)

    return ordered, matches
