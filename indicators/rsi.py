"""
RSI Indicator
=============
RSI-14 calculation + divergence pre-computation.
Divergence detection is done in signals/divergence_detector.py.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RSIResult:
    value:    float   # latest RSI
    zone:     str     # OVERBOUGHT | OVERSOLD | NEUTRAL
    momentum: str     # BULLISH | BEARISH | NEUTRAL


def compute_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Return df (copy) with RSI{period} column."""
    df = df.copy()
    delta = df["Close"].diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    df[f"RSI{period}"] = 100 - (100 / (1 + rs))
    return df


def get_rsi_result(df: pd.DataFrame, period: int = 14) -> RSIResult:
    """Extract latest RSI snapshot."""
    col = f"RSI{period}"
    if col not in df.columns:
        df = compute_rsi(df, period)
    val = float(df[col].iloc[-1])
    zone = "OVERBOUGHT" if val > 70 else "OVERSOLD" if val < 30 else "NEUTRAL"
    # Momentum: RSI vs its 5-period EMA
    rsi_ema = df[col].ewm(span=5, adjust=False).mean().iloc[-1]
    momentum = "BULLISH" if val > float(rsi_ema) else "BEARISH"
    return RSIResult(value=round(val, 2), zone=zone, momentum=momentum)
