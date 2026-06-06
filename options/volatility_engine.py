"""
Volatility Engine
==================
Computes all volatility metrics required by the options strategy selector:

  HV20  — Historical Volatility 20-day (annualised)
  HV60  — Historical Volatility 60-day
  ATR14 — Average True Range 14-day
  IV    — Implied Volatility (from option chain or ATM estimate)
  IV Rank     — (IV - IV_min_52w) / (IV_max_52w - IV_min_52w) × 100
  IV Percentile — % of days in past 252d where IV was below current

All outputs are normalised to 0–100 for IV Rank / Percentile.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRADING_DAYS = 252
IV_LOOKBACK  = 252   # 1 year for IV Rank / Percentile


@dataclass(frozen=True)
class VolatilityResult:
    iv:               float         # current IV (from chain or estimate)
    iv_rank:          float         # 0–100
    iv_percentile:    float         # 0–100
    hv20:             float         # annualised %
    hv60:             float         # annualised %
    atr14:            float         # dollar value
    atr_pct:          float         # ATR / price %
    iv_vs_hv:         float         # IV / HV20 ratio
    vol_regime:       str           # HIGH | NORMAL | LOW
    iv_environment:   str           # HIGH_IV | NORMAL_IV | LOW_IV
    source:           str           # "chain" | "atm_estimate" | "hv_proxy"


def _hv(close: pd.Series, window: int) -> float:
    """Annualised historical volatility over *window* days."""
    log_ret = np.log(close / close.shift(1)).dropna()
    if len(log_ret) < window:
        return float(log_ret.std() * math.sqrt(TRADING_DAYS))
    return float(log_ret.iloc[-window:].std() * math.sqrt(TRADING_DAYS))


def _atr14(df: pd.DataFrame) -> tuple[float, float]:
    """Return (ATR14, ATR_pct)."""
    hl  = df["High"] - df["Low"]
    hc  = (df["High"] - df["Close"].shift()).abs()
    lc  = (df["Low"]  - df["Close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    atr = float(tr.ewm(alpha=1 / 14, adjust=False).mean().iloc[-1])
    price = float(df["Close"].iloc[-1])
    return atr, (atr / price * 100 if price > 0 else 0.0)


def _iv_rank_percentile(
    current_iv: float,
    close: pd.Series,
    hv20: float,
) -> tuple[float, float]:
    """
    Estimate IV Rank and IV Percentile from a synthetic IV series.

    If real historical IV is unavailable (no chain history), proxy using
    a rolling HV20 series — acceptable for ranking purposes.
    """
    log_ret = np.log(close / close.shift(1)).dropna()

    if len(log_ret) < IV_LOOKBACK:
        window = len(log_ret)
    else:
        window = IV_LOOKBACK

    # Synthetic IV proxy: rolling 20-day HV annualised
    roll_hv = (
        log_ret
        .rolling(20)
        .std()
        .dropna()
        .iloc[-window:]
        * math.sqrt(TRADING_DAYS)
    )

    if len(roll_hv) < 2:
        return 50.0, 50.0

    iv_min = float(roll_hv.min())
    iv_max = float(roll_hv.max())

    iv_rank = (
        round((current_iv - iv_min) / (iv_max - iv_min) * 100, 1)
        if iv_max > iv_min else 50.0
    )
    iv_rank = max(0.0, min(100.0, iv_rank))

    iv_pct = round(float((roll_hv < current_iv).mean() * 100), 1)

    return iv_rank, iv_pct


def _classify_iv_env(iv_rank: float) -> str:
    if iv_rank >= 65:
        return "HIGH_IV"
    if iv_rank <= 30:
        return "LOW_IV"
    return "NORMAL_IV"


def _classify_vol_regime(atr_pct: float) -> str:
    if atr_pct >= 3.0:
        return "HIGH"
    if atr_pct <= 1.0:
        return "LOW"
    return "NORMAL"


def compute_volatility(
    df: pd.DataFrame,
    chain_iv: float | None = None,
) -> VolatilityResult:
    """
    Compute all volatility metrics.

    Parameters
    ----------
    df       : daily OHLCV DataFrame
    chain_iv : ATM IV from the option chain (0–1 scale, e.g. 0.28 = 28%)
               Pass None to fall back to HV20 as proxy.

    Returns
    -------
    VolatilityResult
    """
    if len(df) < 21:
        raise ValueError("Need ≥ 21 bars to compute volatility")

    close = df["Close"]

    hv20 = round(_hv(close, 20), 4)
    hv60 = round(_hv(close, 60), 4)
    atr, atr_pct = _atr14(df)

    # Determine IV source
    if chain_iv is not None and chain_iv > 0.005:
        iv     = round(chain_iv, 4)
        source = "chain"
    else:
        # Proxy: use HV20 × 1.15 (options typically price in a 15% premium)
        iv     = round(hv20 * 1.15, 4)
        source = "hv_proxy" if chain_iv is None else "atm_estimate"

    iv_rank, iv_pct = _iv_rank_percentile(iv, close, hv20)
    iv_vs_hv = round(iv / hv20, 3) if hv20 > 0 else 1.0

    return VolatilityResult(
        iv             = iv,
        iv_rank        = iv_rank,
        iv_percentile  = iv_pct,
        hv20           = round(hv20, 4),
        hv60           = round(hv60, 4),
        atr14          = round(atr, 4),
        atr_pct        = round(atr_pct, 3),
        iv_vs_hv       = iv_vs_hv,
        vol_regime     = _classify_vol_regime(atr_pct),
        iv_environment = _classify_iv_env(iv_rank),
        source         = source,
    )
