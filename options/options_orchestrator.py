"""
Options Orchestrator — Full Institutional Pipeline
=====================================================
  1. Volatility Engine  → IV, IV Rank, HV20, ATR14
  2. Expected Move      → ±1SD / ±1.5SD / ±2SD bands
  3. Probability Engine → MC 10k paths, strategy_pops
  4. Selection Engine   → 7 rules + composite rank → top 3
  5. Approval gate      → EV>0, POP≥55, AI≥60, score≥60

Output: OptionsRecommendation  (integrates with LINE formatter + Sheets)
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass

import pandas as pd

from options.expected_move_engine import compute_expected_move, select_dte, ExpectedMoveResult
from options.probability_engine import ProbabilityResult, compute_strategy_pops
from options.selection_engine import StrategyRanking, select_option_strategies
from options.strategy_models import StrategySetup
from options.volatility_engine import VolatilityResult, compute_volatility

logger = logging.getLogger(__name__)


@dataclass
class OptionsRecommendation:
    symbol:          str
    price:           float
    timestamp:       str
    runtime:         float
    regime:          str
    regime_conf:     float
    bull_prob:       float
    bear_prob:       float
    range_prob:      float
    vol:             VolatilityResult
    em:              ExpectedMoveResult
    ranking:         StrategyRanking
    primary:         StrategySetup
    ai_score:        float
    trade_approved:  bool
    approval_reason: str


def _get_atm_iv(chain: list[dict], price: float, dte_bucket: int) -> float | None:
    cands = [r for r in chain if r.get("dte_bucket") == dte_bucket
             and r.get("option_type") == "call" and r.get("iv", 0) > 0]
    if not cands:
        cands = [r for r in chain if r.get("iv", 0) > 0]
    if not cands:
        return None
    atm = min(cands, key=lambda r: abs(r.get("strike", price) - price))
    return float(atm["iv"])


def run_options_analysis(
    symbol:         str,
    price:          float,
    df:             pd.DataFrame,
    regime:         str,
    regime_conf:    float,
    regime_probs:   dict[str, float],
    ai_score:       float,
    enriched_chain: list[dict],
) -> OptionsRecommendation:

    t0 = time.time()
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    bull_prob  = regime_probs.get("BULL", 0) + regime_probs.get("STRONG_BULL", 0)
    bear_prob  = regime_probs.get("BEAR", 0) + regime_probs.get("STRONG_BEAR", 0)
    range_prob = regime_probs.get("RANGE", 0)

    # ── 1. Volatility ─────────────────────────────────────────────────────────
    target_dte = select_dte(regime, 50)
    chain_iv   = _get_atm_iv(enriched_chain, price, target_dte)
    try:
        vol = compute_volatility(df, chain_iv=chain_iv)
    except Exception as exc:
        logger.warning("[%s] vol engine failed: %s", symbol, exc)
        vol = VolatilityResult(iv=0.30, iv_rank=50.0, iv_percentile=50.0,
            hv20=0.26, hv60=0.24, atr14=price*0.015, atr_pct=1.5,
            iv_vs_hv=1.15, vol_regime="NORMAL", iv_environment="NORMAL_IV", source="fallback")

    # ── 2. Expected Move ──────────────────────────────────────────────────────
    optimal_dte = select_dte(regime, vol.iv_rank)
    em = compute_expected_move(price, vol.iv, optimal_dte)

    # ── 3. Probabilities (batch MC) ───────────────────────────────────────────
    pops_dict = compute_strategy_pops(price, vol.iv, optimal_dte, em.expected_move)
    prob_result = ProbabilityResult(
        simulations=10_000, dte=optimal_dte,
        prob_above=pops_dict.get("BULL_CALL_SPREAD", 50),
        prob_below=pops_dict.get("LONG_PUT", 50),
        prob_between=pops_dict.get("IRON_CONDOR", 50),
        pop=pops_dict.get("IRON_CONDOR", 50),
        paths=10_000, strategy_pops=pops_dict,
    )

    # Dominant DTE from chain OI
    oi_by_dte: dict[int, int] = {}
    for r in enriched_chain:
        b = r.get("dte_bucket", optimal_dte)
        oi_by_dte[b] = oi_by_dte.get(b, 0) + (r.get("open_interest", 0) or 0)
    dominant_dte = max(oi_by_dte, key=oi_by_dte.get) if oi_by_dte else optimal_dte

    # ── 4. Strategy Selection ─────────────────────────────────────────────────
    ranking = select_option_strategies(
        symbol=symbol, spot=price, regime=regime, regime_probs=regime_probs,
        regime_conf=regime_conf, vol=vol, expected_move=em.expected_move,
        expected_move_pct=em.expected_move_pct, prob_result=prob_result,
        enriched_chain=enriched_chain, dominant_dte=dominant_dte,
    )

    primary = ranking.top_strategies[0] if ranking.top_strategies else None

    if primary is None:
        # Ultimate fallback
        from options.strategy_models import build_iron_condor
        from options.strike_selector import select_strikes
        strikes = select_strikes("IRON_CONDOR", price, enriched_chain, optimal_dte, em.expected_move)
        primary = build_iron_condor(price, strikes.sell_call or price*1.05,
            strikes.buy_call or price*1.08, strikes.sell_put or price*0.95,
            strikes.buy_put or price*0.92,
            strikes.sell_call_prem, strikes.buy_call_prem,
            strikes.sell_put_prem, strikes.buy_put_prem, optimal_dte)

    # ── 5. Approval ───────────────────────────────────────────────────────────
    trade_approved = (
        primary.ev > 0 and primary.pop >= 55
        and ai_score >= 60 and primary.score >= 60
    )
    if trade_approved:
        reason = f"✅ Approved: EV={primary.ev:.1f} POP={primary.pop:.0f}% AI={ai_score:.0f} Score={primary.score:.0f}"
    else:
        parts = []
        if primary.ev <= 0:       parts.append(f"EV={primary.ev:.1f}≤0")
        if primary.pop < 55:      parts.append(f"POP={primary.pop:.0f}%<55")
        if ai_score < 60:         parts.append(f"AI={ai_score:.0f}<60")
        if primary.score < 60:    parts.append(f"Score={primary.score:.0f}<60")
        reason = "⏸️ NOT approved: " + "  ".join(parts)

    runtime = round(time.time() - t0, 2)
    logger.info("[%s] options done %.1fs | %s score=%.0f pop=%.0f%% ev=%.1f | approved=%s",
                symbol, runtime, primary.name, primary.score, primary.pop, primary.ev, trade_approved)

    return OptionsRecommendation(
        symbol=symbol, price=price, timestamp=ts, runtime=runtime,
        regime=regime, regime_conf=regime_conf,
        bull_prob=round(bull_prob, 3), bear_prob=round(bear_prob, 3),
        range_prob=round(range_prob, 3),
        vol=vol, em=em, ranking=ranking, primary=primary,
        ai_score=ai_score, trade_approved=trade_approved, approval_reason=reason,
    )
