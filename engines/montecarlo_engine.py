import numpy as np
import pandas as pd


def monte_carlo(
    close_series: pd.Series,
    simulations: int = 1000,
    horizon: int = 20,
    bull_threshold: float = 0.05,
    bear_threshold: float = -0.05,
) -> dict:
    """
    Estimate the probability of bull / bear / sideway outcomes over *horizon*
    trading days using Geometric Brownian Motion (log-return simulation).

    Parameters
    ----------
    close_series   : pd.Series of closing prices
    simulations    : number of Monte Carlo paths
    horizon        : forward-looking days
    bull_threshold : total log-return above this → BULL  (default +5 %)
    bear_threshold : total log-return below this → BEAR  (default -5 %)

    Returns
    -------
    dict with keys: symbol, bull, bear, sideway (all rounded to 1 dp)
    """

    log_returns = np.log(close_series / close_series.shift(1)).dropna()

    mu = log_returns.mean()
    sigma = log_returns.std()

    # Drift-adjusted mean for GBM
    drift = mu - 0.5 * sigma ** 2

    # Simulate (simulations × horizon) random shocks in one vectorised call
    shocks = np.random.normal(drift, sigma, size=(simulations, horizon))
    total_log_returns = shocks.sum(axis=1)          # shape (simulations,)

    bull = int((total_log_returns > bull_threshold).sum())
    bear = int((total_log_returns < bear_threshold).sum())
    sideway = simulations - bull - bear

    bull_pct = round(bull / simulations * 100, 1)
    bear_pct = round(bear / simulations * 100, 1)
    sideway_pct = round(max(0, sideway / simulations * 100), 1)

    return {
        "symbol": getattr(close_series, "name", "UNKNOWN"),
        "bull": bull_pct,
        "bear": bear_pct,
        "sideway": sideway_pct,
    }
