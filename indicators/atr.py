"""
ATR Indicator
=============
ATR-14 (Wilder's smoothing) for stop-loss and volatility sizing.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ATRResult:
    atr14:      float
    atr_pct:    float   # ATR / price × 100
    volatility: str     # LOW | MEDIUM | HIGH


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Return df (copy) with ATR{period} column using Wilder EMA."""
    df = df.copy()
    hl  = df["High"] - df["Low"]
    hc  = (df["High"] - df["Close"].shift()).abs()
    lc  = (df["Low"]  - df["Close"].shift()).abs()
    tr  = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df[f"ATR{period}"] = tr.ewm(alpha=1 / period, adjust=False).mean()
    return df


def get_atr_result(df: pd.DataFrame, period: int = 14) -> ATRResult:
    """Extract latest ATR snapshot."""
    col = f"ATR{period}"
    if col not in df.columns:
        df = compute_atr(df, period)
    atr  = float(df[col].iloc[-1])
    price = float(df["Close"].iloc[-1])
    pct  = atr / price * 100 if price > 0 else 0.0
    vol  = "HIGH" if pct > 3.0 else "LOW" if pct < 1.0 else "MEDIUM"
    return ATRResult(atr14=round(atr, 4), atr_pct=round(pct, 2), volatility=vol)
