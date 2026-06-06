"""
Portfolio Risk Engine
======================
Computes portfolio-level risk metrics from historical returns:

  VaR (95% & 99%)   — Value at Risk
  CVaR (ES)         — Conditional VaR / Expected Shortfall
  Max Drawdown      — historical + forecast
  Volatility        — historical + EWMA forecast
  Sharpe Ratio
  Sortino Ratio
  Calmar Ratio
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

RISK_FREE_ANNUAL = 0.05
TRADING_DAYS     = 252


@dataclass(frozen=True)
class PortfolioRiskResult:
    var_95:             float   # VaR at 95% (% of capital, positive = loss)
    var_99:             float
    cvar_95:            float   # CVaR / Expected Shortfall at 95%
    cvar_99:            float
    max_drawdown:       float   # historical max drawdown (%)
    volatility_annual:  float   # annualised historical vol (%)
    vol_ewma_forecast:  float   # EWMA vol forecast next day (%)
    sharpe:             float
    sortino:            float
    calmar:             float


def compute_portfolio_risk(close_series: pd.Series) -> PortfolioRiskResult:
    """
    Compute all portfolio risk metrics from a price series.

    Parameters
    ----------
    close_series : pd.Series of closing prices (daily)
    """

    returns = close_series.pct_change().dropna().to_numpy()

    if len(returns) < 30:
        raise ValueError("Need ≥ 30 return observations")

    # ── VaR ──────────────────────────────────────────────────────────────────
    var_95 = float(-np.percentile(returns, 5)  * 100)
    var_99 = float(-np.percentile(returns, 1)  * 100)

    # ── CVaR (Expected Shortfall) ────────────────────────────────────────────
    tail_95 = returns[returns <= np.percentile(returns, 5)]
    tail_99 = returns[returns <= np.percentile(returns, 1)]
    cvar_95 = float(-tail_95.mean() * 100) if len(tail_95) > 0 else var_95
    cvar_99 = float(-tail_99.mean() * 100) if len(tail_99) > 0 else var_99

    # ── Max Drawdown ──────────────────────────────────────────────────────────
    prices     = close_series.to_numpy()
    peak       = np.maximum.accumulate(prices)
    drawdown   = (prices - peak) / peak
    max_dd_pct = float(drawdown.min() * 100)

    # ── Volatility ────────────────────────────────────────────────────────────
    vol_annual  = float(np.std(returns) * np.sqrt(TRADING_DAYS) * 100)

    # EWMA volatility forecast (λ = 0.94, RiskMetrics standard)
    lam = 0.94
    ewma_var = float(returns[-1] ** 2)
    for r in returns[-30:]:
        ewma_var = lam * ewma_var + (1 - lam) * r ** 2
    vol_ewma = float(np.sqrt(ewma_var) * np.sqrt(TRADING_DAYS) * 100)

    # ── Sharpe ────────────────────────────────────────────────────────────────
    mean_annual = float(np.mean(returns) * TRADING_DAYS)
    std_annual  = float(np.std(returns)  * np.sqrt(TRADING_DAYS))
    sharpe = (mean_annual - RISK_FREE_ANNUAL) / std_annual if std_annual > 0 else 0.0

    # ── Sortino ───────────────────────────────────────────────────────────────
    downside = returns[returns < 0]
    downside_std = float(np.std(downside) * np.sqrt(TRADING_DAYS)) if len(downside) > 0 else std_annual
    sortino = (mean_annual - RISK_FREE_ANNUAL) / downside_std if downside_std > 0 else 0.0

    # ── Calmar ────────────────────────────────────────────────────────────────
    calmar = mean_annual / abs(max_dd_pct / 100) if max_dd_pct != 0 else 0.0

    return PortfolioRiskResult(
        var_95            = round(var_95, 3),
        var_99            = round(var_99, 3),
        cvar_95           = round(cvar_95, 3),
        cvar_99           = round(cvar_99, 3),
        max_drawdown      = round(max_dd_pct, 2),
        volatility_annual = round(vol_annual, 2),
        vol_ewma_forecast = round(vol_ewma, 2),
        sharpe            = round(sharpe, 3),
        sortino           = round(sortino, 3),
        calmar            = round(calmar, 3),
    )
