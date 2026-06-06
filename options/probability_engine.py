"""
Probability Engine
==================
Monte Carlo 10,000 paths — Geometric Brownian Motion

Outputs per strike range:
  prob_above / prob_below / prob_between / pop
Also produces strategy_pops dict for ev_engine batch processing.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import NamedTuple
import numpy as np

logger = logging.getLogger(__name__)
N_SIMULATIONS = 10_000
RNG_SEED = 42


@dataclass(frozen=True)
class ProbabilityResult:
    simulations:   int
    dte:           int
    prob_above:    float
    prob_below:    float
    prob_between:  float
    pop:           float
    paths:         int
    strategy_pops: dict[str, float] = field(default_factory=dict)


class StrikeRange(NamedTuple):
    lower: float
    upper: float


def _gbm_terminal(price: float, iv: float, dte: int, sims: int = N_SIMULATIONS, seed: int = RNG_SEED) -> np.ndarray:
    t     = dte / 365.0
    drift = -0.5 * iv**2 * t
    vol   = iv * math.sqrt(t)
    rng   = np.random.default_rng(seed)
    return price * np.exp(drift + vol * rng.standard_normal(sims))


def compute_probabilities(
    price: float, iv: float, dte: int,
    strike_range: StrikeRange, direction: str,
    simulations: int = N_SIMULATIONS,
) -> ProbabilityResult:
    import math
    terminal = _gbm_terminal(price, iv, dte, sims=simulations)
    lower, upper = strike_range.lower, strike_range.upper
    above   = float((terminal > upper).mean() * 100)
    below   = float((terminal < lower).mean() * 100)
    between = float(((terminal >= lower) & (terminal <= upper)).mean() * 100)
    if direction == "LONG":
        pop = above
    elif direction == "SHORT":
        pop = below
    else:
        pop = between
    return ProbabilityResult(
        simulations=simulations, dte=dte,
        prob_above=round(above, 1), prob_below=round(below, 1),
        prob_between=round(between, 1), pop=round(pop, 1), paths=simulations,
    )


def quick_pop(price: float, strike: float, iv: float, dte: int, direction: str) -> float:
    """Fast single-strike POP (2,000 paths for speed in bulk scoring)."""
    import math
    sr = StrikeRange(lower=min(price, strike), upper=max(price, strike))
    r = compute_probabilities(price, iv, dte, sr, direction, simulations=2_000)
    return r.pop


def compute_strategy_pops(
    price: float, iv: float, dte: int,
    expected_move: float,
    simulations: int = N_SIMULATIONS,
) -> dict[str, float]:
    """
    Compute POP for all 14 strategies in one batch using the same terminal price array.
    Returns {strategy_name: pop_float}
    """
    import math
    terminal = _gbm_terminal(price, iv, dte, sims=simulations)

    em1 = expected_move
    em2 = expected_move * 1.5

    def above(k):  return float((terminal > k).mean() * 100)
    def below(k):  return float((terminal < k).mean() * 100)
    def between(lo, hi): return float(((terminal >= lo) & (terminal <= hi)).mean() * 100)

    sc = price + em1;  bc = price + em2
    sp = price - em1;  bp = price - em2
    atm = price

    pops = {
        "LONG_CALL":         above(atm),
        "BULL_CALL_SPREAD":  above(sc),
        "CASH_SECURED_PUT":  above(sp * 0.97),
        "PUT_CREDIT_SPREAD": above(sp),
        "RISK_REVERSAL":     above(sc),
        "IRON_CONDOR":       between(sp, sc),
        "IRON_BUTTERFLY":    between(atm - em1*0.4, atm + em1*0.4),
        "SHORT_STRANGLE":    between(sp, sc),
        "LONG_STRADDLE":     100 - between(atm - em1*0.5, atm + em1*0.5),
        "LONG_STRANGLE":     100 - between(sp, sc),
        "LONG_PUT":          below(atm),
        "PUT_DEBIT_SPREAD":  below(sp),
        "BEAR_CALL_SPREAD":  below(sc * 0.98),
        "COVERED_CALL":      below(sc * 0.97),
    }
    return {k: round(v, 1) for k, v in pops.items()}


import math  # required at module level for _gbm_terminal
