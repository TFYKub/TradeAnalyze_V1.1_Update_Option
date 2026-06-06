"""
Institutional Option Strategy Selection Engine
================================================
Pipeline:
  1. Rule Engine (7 rules) → candidate strategy names
  2. Select strikes (from chain or estimated)
  3. Build StrategySetup (exact payoff math)
  4. Batch POP via Monte Carlo
  5. Compute EV + Kelly per strategy
  6. Composite score → top 3

Composite Score:
  30% EV  +  25% POP  +  20% Kelly  +  15% RegimeConf  +  10% RR
"""
from __future__ import annotations
import logging
import math
from dataclasses import dataclass, replace as dc_replace
from options.ev_engine import compute_ev_batch
from options.expected_move_engine import ExpectedMoveResult, choose_dte_for_strategy
from options.probability_engine import ProbabilityResult, compute_strategy_pops
from options.strategy_models import (
    StrategySetup,
    build_long_call, build_bull_call_spread, build_cash_secured_put,
    build_put_credit_spread, build_risk_reversal, build_iron_condor,
    build_iron_butterfly, build_short_strangle, build_long_straddle,
    build_long_strangle, build_long_put, build_put_debit_spread,
    build_bear_call_spread, build_covered_call,
)
from options.strike_selector import StrikeSet, select_strikes
from options.volatility_engine import VolatilityResult

logger = logging.getLogger(__name__)
MIN_POP = 40.0


@dataclass(frozen=True)
class StrategyRanking:
    symbol:            str
    regime:            str
    confidence:        float
    iv_rank:           float
    iv_environment:    str
    expected_move:     float
    expected_move_pct: float
    top_strategies:    list[StrategySetup]
    rule_triggered:    str
    trade_allowed:     bool
    no_trade_reason:   str


# ── Rule engine ───────────────────────────────────────────────────────────────
def _apply_rules(regime: str, regime_probs: dict[str, float], iv_rank: float) -> tuple[list[str], str]:
    bull_p = regime_probs.get("BULL", 0) + regime_probs.get("STRONG_BULL", 0)

    rule_hit   = "COMPOSITE_RANK"
    candidates: list[str] = []

    if regime in ("BULL", "STRONG_BULL"):
        if bull_p > 0.55 and iv_rank < 35:
            candidates.append("BULL_CALL_SPREAD"); rule_hit = "Rule1: BULL+LowIV"
        if bull_p > 0.55 and iv_rank > 65:
            candidates.append("CASH_SECURED_PUT")
            if rule_hit == "COMPOSITE_RANK": rule_hit = "Rule2: BULL+HighIV"
    if regime == "RANGE":
        if iv_rank > 55:
            candidates.append("IRON_CONDOR"); rule_hit = "Rule3: RANGE+HighIV"
        if iv_rank < 30:
            candidates.append("LONG_STRADDLE")
            if rule_hit == "COMPOSITE_RANK": rule_hit = "Rule4: RANGE+LowIV"
    if regime == "CORRECTION" and iv_rank < 45:
        candidates.append("PUT_DEBIT_SPREAD"); rule_hit = "Rule5: CORRECTION"
    if regime in ("BEAR", "STRONG_BEAR"):
        if iv_rank < 35:
            candidates.append("LONG_PUT"); rule_hit = "Rule6: BEAR+LowIV"
        if iv_rank > 60:
            candidates.append("BEAR_CALL_SPREAD")
            if rule_hit == "COMPOSITE_RANK": rule_hit = "Rule7: BEAR+HighIV"

    extras = {
        "STRONG_BULL": ["BULL_CALL_SPREAD", "PUT_CREDIT_SPREAD", "RISK_REVERSAL", "LONG_CALL"],
        "BULL":        ["BULL_CALL_SPREAD", "PUT_CREDIT_SPREAD", "CASH_SECURED_PUT", "LONG_CALL"],
        "RANGE":       ["IRON_CONDOR", "IRON_BUTTERFLY", "SHORT_STRANGLE", "LONG_STRADDLE", "LONG_STRANGLE"],
        "CORRECTION":  ["PUT_DEBIT_SPREAD", "BEAR_CALL_SPREAD", "LONG_PUT", "IRON_CONDOR"],
        "BEAR":        ["LONG_PUT", "BEAR_CALL_SPREAD", "PUT_DEBIT_SPREAD"],
        "STRONG_BEAR": ["LONG_PUT", "BEAR_CALL_SPREAD", "PUT_DEBIT_SPREAD", "LONG_STRANGLE"],
    }
    seen: set[str] = set(candidates)
    for s in extras.get(regime, []):
        if s not in seen:
            seen.add(s); candidates.append(s)

    return candidates, rule_hit


# ── Strategy builder dispatch ─────────────────────────────────────────────────
def _build(name: str, spot: float, strikes: StrikeSet, dte: int) -> StrategySetup | None:
    bc  = strikes.buy_call  or spot
    sc  = strikes.sell_call or spot * 1.05
    bp  = strikes.buy_put   or spot
    sp  = strikes.sell_put  or spot * 0.95
    bcp = strikes.buy_call_prem;  scp = strikes.sell_call_prem
    bpp = strikes.buy_put_prem;   spp = strikes.sell_put_prem
    try:
        m = {
            "LONG_CALL":         lambda: build_long_call(spot, bc, bcp, dte),
            "BULL_CALL_SPREAD":  lambda: build_bull_call_spread(spot, bc, sc, bcp, scp, dte),
            "CASH_SECURED_PUT":  lambda: build_cash_secured_put(spot, sp, spp, dte),
            "PUT_CREDIT_SPREAD": lambda: build_put_credit_spread(spot, sp, bp, spp, bpp, dte),
            "RISK_REVERSAL":     lambda: build_risk_reversal(spot, sp, bc, spp, bcp, dte),
            "IRON_CONDOR":       lambda: build_iron_condor(spot, sc, bc, sp, bp, scp, bcp, spp, bpp, dte),
            "IRON_BUTTERFLY":    lambda: build_iron_butterfly(spot, spot, bc, bp, scp, spp, bcp, bpp, dte),
            "SHORT_STRANGLE":    lambda: build_short_strangle(spot, sc, sp, scp, spp, dte),
            "LONG_STRADDLE":     lambda: build_long_straddle(spot, spot, bcp, bpp, dte),
            "LONG_STRANGLE":     lambda: build_long_strangle(spot, bc, bp, bcp, bpp, dte),
            "LONG_PUT":          lambda: build_long_put(spot, bp, bpp, dte),
            "PUT_DEBIT_SPREAD":  lambda: build_put_debit_spread(spot, bp, sp, bpp, spp, dte),
            "BEAR_CALL_SPREAD":  lambda: build_bear_call_spread(spot, sc, bc, scp, bcp, dte),
            "COVERED_CALL":      lambda: build_covered_call(spot, sc, scp, dte),
        }
        fn = m.get(name.upper())
        return fn() if fn else None
    except Exception as exc:
        logger.debug("Build %s failed: %s", name, exc)
        return None


# ── Composite score ───────────────────────────────────────────────────────────
def _score(s: StrategySetup, regime_conf: float) -> float:
    ev_n    = min(100.0, max(0.0, 50 + s.ev * 2))
    pop_n   = float(s.pop)
    kelly_n = min(100.0, s.kelly * 400)
    rr_n    = min(100.0, (s.rr if not math.isinf(s.rr) else 5.0) / 5 * 100)
    conf_n  = float(regime_conf)
    return round(ev_n*0.30 + pop_n*0.25 + kelly_n*0.20 + conf_n*0.15 + rr_n*0.10, 1)


def _rationale(name: str, regime: str, iv_env: str, iv_rank: float) -> str:
    m = {
        "LONG_CALL":         f"LONG + {iv_env} → cheap leverage",
        "BULL_CALL_SPREAD":  f"LONG + limit premium ({iv_env})",
        "CASH_SECURED_PUT":  f"BULL + High IV ({iv_rank:.0f}) → collect premium",
        "PUT_CREDIT_SPREAD": f"BULL + defined-risk credit",
        "RISK_REVERSAL":     f"Strong conviction, zero-cost",
        "IRON_CONDOR":       f"RANGE + High IV ({iv_rank:.0f}) → sell both wings",
        "IRON_BUTTERFLY":    f"RANGE + theta decay at ATM",
        "SHORT_STRANGLE":    f"RANGE + High IV → premium both sides (⚠️ naked)",
        "LONG_STRADDLE":     f"RANGE + Low IV ({iv_rank:.0f}) → buy vol before breakout",
        "LONG_STRANGLE":     f"RANGE + Low IV → cheaper vol play",
        "LONG_PUT":          f"BEAR + Low IV ({iv_rank:.0f}) → cheap directional",
        "PUT_DEBIT_SPREAD":  f"BEAR + defined-risk debit",
        "BEAR_CALL_SPREAD":  f"BEAR + High IV ({iv_rank:.0f}) → sell call spread",
        "COVERED_CALL":      f"Reduce cost basis + income",
    }
    return m.get(name.upper(), f"regime={regime} iv_env={iv_env}")


# ── Main entry point ──────────────────────────────────────────────────────────
def select_option_strategies(
    symbol:          str,
    spot:            float,
    regime:          str,
    regime_probs:    dict[str, float],
    regime_conf:     float,
    vol:             VolatilityResult,
    expected_move:   float,
    expected_move_pct: float,
    prob_result:     ProbabilityResult,
    enriched_chain:  list[dict],
    dominant_dte:    int | None = 30,
) -> StrategyRanking:

    iv_rank = vol.iv_rank
    iv_env  = vol.iv_environment

    candidate_names, rule_hit = _apply_rules(regime, regime_probs, iv_rank)
    logger.info("[selection] %s: regime=%s iv_rank=%.0f rule=%s n=%d",
                symbol, regime, iv_rank, rule_hit, len(candidate_names))

    if not candidate_names:
        return StrategyRanking(symbol=symbol, regime=regime, confidence=regime_conf,
            iv_rank=iv_rank, iv_environment=iv_env,
            expected_move=expected_move, expected_move_pct=expected_move_pct,
            top_strategies=[], rule_triggered=rule_hit,
            trade_allowed=False, no_trade_reason="No rule matched")

    # Batch POP via MC (single terminal array for all strategies)
    pops = compute_strategy_pops(spot, vol.iv, dominant_dte or 30, expected_move)

    built: list[StrategySetup] = []
    for name in candidate_names:
        dte     = choose_dte_for_strategy(name, dominant_dte)
        strikes = select_strikes(name, spot, enriched_chain, dte, expected_move)
        setup   = _build(name, spot, strikes, dte)
        if setup is None:
            continue
        setup = dc_replace(setup, rationale=_rationale(name, regime, iv_env, iv_rank))
        built.append(setup)

    if not built:
        return StrategyRanking(symbol=symbol, regime=regime, confidence=regime_conf,
            iv_rank=iv_rank, iv_environment=iv_env,
            expected_move=expected_move, expected_move_pct=expected_move_pct,
            top_strategies=[], rule_triggered=rule_hit,
            trade_allowed=False, no_trade_reason="Build failed")

    # EV + Kelly
    built = compute_ev_batch(built, pops, expected_move)

    # Filter: POP >= MIN_POP (relax if nothing passes)
    viable = [s for s in built if s.pop >= MIN_POP] or built

    # Score + rank
    scored = sorted(
        [dc_replace(s, score=_score(s, regime_conf)) for s in viable],
        key=lambda s: s.score, reverse=True
    )
    top3 = scored[:3]

    logger.info("[selection] %s: top=%s score=%.1f pop=%.0f%% ev=%.2f",
                symbol, top3[0].name if top3 else "none",
                top3[0].score if top3 else 0,
                top3[0].pop if top3 else 0,
                top3[0].ev if top3 else 0)

    return StrategyRanking(
        symbol=symbol, regime=regime, confidence=regime_conf,
        iv_rank=iv_rank, iv_environment=iv_env,
        expected_move=expected_move, expected_move_pct=expected_move_pct,
        top_strategies=top3, rule_triggered=rule_hit,
        trade_allowed=bool(top3 and top3[0].ev > 0),
        no_trade_reason="" if top3 else "All strategies filtered",
    )
