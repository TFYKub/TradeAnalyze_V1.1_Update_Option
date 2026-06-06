"""
Monte Carlo Simulation Engine
===============================
Geometric Brownian Motion simulation — 10,000 paths minimum

Inputs:
  close_series   : pd.Series of historical closing prices
  horizon        : forward-looking days (default = 20)
  simulations    : number of GBM paths  (default = 10,000)
  entry          : trade entry price
  stop_loss      : stop loss level
  target         : take profit target
  win_rate       : historical win rate for EV/Kelly weighting

Outputs (MonteCarloResult):
  prob_profit          — probability path closes above entry
  prob_stop_hit        — probability path touches stop loss
  prob_target_hit      — probability path reaches target
  expected_return_pct  — mean return at horizon (%)
  expected_drawdown_pct— mean max drawdown (%)
  ci_95_low / high     — 95% confidence interval of final returns
  var_95               — Value-at-Risk at 95% (% of capital)
  cvar_95              — Conditional VaR (Expected Shortfall)
  sharpe_simulated     — simulated Sharpe ratio
  sortino_simulated    — simulated Sortino ratio
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

N_SIMULATIONS  = 10_000
DEFAULT_HORIZON = 20
RISK_FREE_DAILY = 0.05 / 252   # annualised 5% → daily


@dataclass(frozen=True)
class MonteCarloResult:
    simulations:          int
    horizon:              int

    prob_profit:          float   # % paths finishing > entry
    prob_stop_hit:        float   # % paths touching SL
    prob_target_hit:      float   # % paths reaching target
    expected_return_pct:  float   # mean final return (%)
    expected_drawdown_pct: float  # mean max drawdown (%)

    ci_95_low:            float   # 2.5th percentile return (%)
    ci_95_high:           float   # 97.5th percentile return (%)

    var_95:               float   # -VaR at 95% (positive number, % loss)
    cvar_95:              float   # -CVaR at 95% (Expected Shortfall, % loss)

    sharpe_simulated:     float
    sortino_simulated:    float


def run_monte_carlo(
    close_series: pd.Series,
    entry:        float,
    stop_loss:    float,
    target:       float,
    horizon:      int   = DEFAULT_HORIZON,
    simulations:  int   = N_SIMULATIONS,
) -> MonteCarloResult:
    """
    Run GBM Monte Carlo simulation and return risk/probability statistics.

    Parameters
    ----------
    close_series : historical closing prices (pd.Series)
    entry        : trade entry price
    stop_loss    : stop loss level
    target       : profit target level
    horizon      : number of trading days to simulate
    simulations  : number of GBM paths
    """

    # ── Calibrate from historical returns ────────────────────────────────────
    log_returns = np.log(close_series / close_series.shift(1)).dropna()
    mu    = float(log_returns.mean())
    sigma = float(log_returns.std())

    if sigma <= 0:
        sigma = 0.01   # fallback

    # GBM drift-adjusted mean
    drift = mu - 0.5 * sigma ** 2

    # ── Simulate paths (simulations × horizon) ───────────────────────────────
    rng    = np.random.default_rng(42)
    shocks = rng.normal(drift, sigma, size=(simulations, horizon))
    log_paths = np.cumsum(shocks, axis=1)   # shape (simulations, horizon)

    # Price paths relative to entry
    price_paths = entry * np.exp(log_paths)  # shape (simulations, horizon)
    final_prices = price_paths[:, -1]

    # ── Returns ───────────────────────────────────────────────────────────────
    final_returns_pct = (final_prices - entry) / entry * 100

    # ── Probabilities ─────────────────────────────────────────────────────────
    prob_profit = float((final_prices > entry).mean() * 100)

    # Stop-loss: did ANY bar during the path touch SL?
    if stop_loss < entry:  # LONG
        stop_touched = (price_paths.min(axis=1) <= stop_loss)
    else:                  # SHORT
        stop_touched = (price_paths.max(axis=1) >= stop_loss)
    prob_stop_hit = float(stop_touched.mean() * 100)

    # Target hit: did ANY bar reach target?
    if target > entry:    # LONG
        target_touched = (price_paths.max(axis=1) >= target)
    else:                  # SHORT
        target_touched = (price_paths.min(axis=1) <= target)
    prob_target_hit = float(target_touched.mean() * 100)

    # ── Expected return + drawdown ────────────────────────────────────────────
    expected_return = float(final_returns_pct.mean())

    # Max drawdown per path: (peak - trough) / peak
    running_max  = np.maximum.accumulate(price_paths, axis=1)
    drawdown_per_path = ((price_paths - running_max) / running_max).min(axis=1)
    expected_dd  = float(drawdown_per_path.mean() * 100)

    # ── Confidence interval ───────────────────────────────────────────────────
    ci_low  = float(np.percentile(final_returns_pct, 2.5))
    ci_high = float(np.percentile(final_returns_pct, 97.5))

    # ── VaR & CVaR (95%) ─────────────────────────────────────────────────────
    var_95   = float(-np.percentile(final_returns_pct, 5))    # positive = loss
    tail     = final_returns_pct[final_returns_pct <= np.percentile(final_returns_pct, 5)]
    cvar_95  = float(-tail.mean()) if len(tail) > 0 else var_95

    # ── Simulated Sharpe & Sortino ────────────────────────────────────────────
    daily_path_returns = np.diff(np.log(price_paths), axis=1)   # (sim, horizon-1)
    mean_daily = daily_path_returns.mean(axis=1)
    std_daily  = daily_path_returns.std(axis=1)

    excess_daily    = mean_daily - RISK_FREE_DAILY
    sharpe_per_path = np.where(std_daily > 0, excess_daily / std_daily * np.sqrt(252), 0)
    sharpe_sim      = float(sharpe_per_path.mean())

    downside = np.where(daily_path_returns < 0, daily_path_returns, 0)
    downside_std = downside.std(axis=1)
    sortino_per_path = np.where(
        downside_std > 0,
        excess_daily / downside_std * np.sqrt(252),
        0
    )
    sortino_sim = float(sortino_per_path.mean())

    logger.info(
        "MC[%d paths, %dd]  P(profit)=%.1f%%  P(SL)=%.1f%%  P(TP)=%.1f%%  "
        "E[ret]=%.2f%%  VaR95=%.2f%%",
        simulations, horizon,
        prob_profit, prob_stop_hit, prob_target_hit,
        expected_return, var_95,
    )

    return MonteCarloResult(
        simulations           = simulations,
        horizon               = horizon,
        prob_profit           = round(prob_profit, 1),
        prob_stop_hit         = round(prob_stop_hit, 1),
        prob_target_hit       = round(prob_target_hit, 1),
        expected_return_pct   = round(expected_return, 2),
        expected_drawdown_pct = round(expected_dd, 2),
        ci_95_low             = round(ci_low, 2),
        ci_95_high            = round(ci_high, 2),
        var_95                = round(var_95, 2),
        cvar_95               = round(cvar_95, 2),
        sharpe_simulated      = round(sharpe_sim, 3),
        sortino_simulated     = round(sortino_sim, 3),
    )
