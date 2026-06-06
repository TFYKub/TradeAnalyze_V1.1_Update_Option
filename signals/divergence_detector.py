"""
RSI Divergence Detector
========================
ตรวจ bullish/bearish divergence บน Daily timeframe

Bullish Divergence:
  price makes Lower Low  → RSI makes Higher Low
  → potential reversal UP

Bearish Divergence:
  price makes Higher High → RSI makes Lower High
  → potential reversal DOWN

IMPORTANT: Divergence alone ≠ signal.
ต้องรอ Market Structure Shift ยืนยันก่อน (ดูใน signals/trend_filter.py)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

LOOKBACK = 20    # bars to scan for divergence
MIN_BARS  = 5    # minimum separation between pivot points


@dataclass(frozen=True)
class DivergenceResult:
    kind:        str     # "BULLISH" | "BEARISH" | "NONE"
    detected:    bool
    price_low1:  float | None   # for bullish: first low
    price_low2:  float | None   # for bullish: second low (lower)
    rsi_low1:    float | None
    rsi_low2:    float | None   # higher → divergence
    confidence:  float   # 0–100


def _find_local_lows(series: pd.Series, window: int = 3) -> list[int]:
    """Return indices of local minima in series."""
    idxs = []
    arr  = series.to_numpy()
    for i in range(window, len(arr) - window):
        if arr[i] == arr[i - window:i + window + 1].min():
            idxs.append(i)
    return idxs


def _find_local_highs(series: pd.Series, window: int = 3) -> list[int]:
    """Return indices of local maxima in series."""
    idxs = []
    arr  = series.to_numpy()
    for i in range(window, len(arr) - window):
        if arr[i] == arr[i - window:i + window + 1].max():
            idxs.append(i)
    return idxs


def detect_divergence(df: pd.DataFrame, rsi_col: str = "RSI14") -> DivergenceResult:
    """
    Scan the last LOOKBACK bars for RSI divergence.

    Parameters
    ----------
    df      : DataFrame with Close and rsi_col
    rsi_col : column name for RSI values

    Returns
    -------
    DivergenceResult
    """
    _none = DivergenceResult(
        kind="NONE", detected=False,
        price_low1=None, price_low2=None,
        rsi_low1=None, rsi_low2=None,
        confidence=0.0,
    )

    if rsi_col not in df.columns or len(df) < LOOKBACK + 10:
        return _none

    window = df.iloc[-(LOOKBACK + 10):].copy().reset_index(drop=True)
    close  = window["Close"]
    rsi    = window[rsi_col]

    # ── Bullish Divergence ────────────────────────────────────────────────────
    price_lows = _find_local_lows(close)
    rsi_lows   = _find_local_lows(rsi)

    if len(price_lows) >= 2 and len(rsi_lows) >= 2:
        # Take last two local lows for each
        pl1, pl2 = price_lows[-2], price_lows[-1]
        rl1, rl2 = rsi_lows[-2],   rsi_lows[-1]

        if (
            pl2 > pl1 + MIN_BARS                     # enough separation
            and close.iloc[pl2] < close.iloc[pl1]    # price: Lower Low
            and rsi.iloc[rl2]   > rsi.iloc[rl1]      # RSI: Higher Low
        ):
            price_drop = (close.iloc[pl1] - close.iloc[pl2]) / close.iloc[pl1]
            rsi_rise   = (rsi.iloc[rl2] - rsi.iloc[rl1]) / max(rsi.iloc[rl1], 1)
            conf = min(100.0, (price_drop * 300 + rsi_rise * 200))
            return DivergenceResult(
                kind="BULLISH", detected=True,
                price_low1=float(close.iloc[pl1]),
                price_low2=float(close.iloc[pl2]),
                rsi_low1=float(rsi.iloc[rl1]),
                rsi_low2=float(rsi.iloc[rl2]),
                confidence=round(conf, 1),
            )

    # ── Bearish Divergence ────────────────────────────────────────────────────
    price_highs = _find_local_highs(close)
    rsi_highs   = _find_local_highs(rsi)

    if len(price_highs) >= 2 and len(rsi_highs) >= 2:
        ph1, ph2 = price_highs[-2], price_highs[-1]
        rh1, rh2 = rsi_highs[-2],   rsi_highs[-1]

        if (
            ph2 > ph1 + MIN_BARS
            and close.iloc[ph2] > close.iloc[ph1]    # price: Higher High
            and rsi.iloc[rh2]   < rsi.iloc[rh1]      # RSI: Lower High
        ):
            price_rise = (close.iloc[ph2] - close.iloc[ph1]) / close.iloc[ph1]
            rsi_drop   = (rsi.iloc[rh1] - rsi.iloc[rh2]) / max(rsi.iloc[rh1], 1)
            conf = min(100.0, (price_rise * 300 + rsi_drop * 200))
            return DivergenceResult(
                kind="BEARISH", detected=True,
                price_low1=float(close.iloc[ph1]),
                price_low2=float(close.iloc[ph2]),
                rsi_low1=float(rsi.iloc[rh1]),
                rsi_low2=float(rsi.iloc[rh2]),
                confidence=round(conf, 1),
            )

    return _none
