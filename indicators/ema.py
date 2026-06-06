"""
EMA Indicator
=============
EMA12 / EMA26 primary trend filter.
EMA12 > EMA26 → BULLISH  (LONG only)
EMA12 < EMA26 → BEARISH  (SHORT only)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EMAResult:
    ema12:              float
    ema26:              float
    bias:               str    # "BULLISH" | "BEARISH"
    spread_pct:         float  # (EMA12-EMA26)/EMA26 × 100
    alignment_strength: float  # 0–100


def compute_ema(df: pd.DataFrame) -> pd.DataFrame:
    """Return df (copy) with EMA12, EMA26, EMA_Spread_Pct, EMA_Bias columns."""
    if "Close" not in df.columns:
        raise ValueError("DataFrame must have a 'Close' column")
    df = df.copy()
    df["EMA12"]          = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA26"]          = df["Close"].ewm(span=26, adjust=False).mean()
    df["EMA_Spread"]     = df["EMA12"] - df["EMA26"]
    df["EMA_Spread_Pct"] = (df["EMA_Spread"] / df["EMA26"]) * 100
    df["EMA_Bias"]       = (df["EMA12"] > df["EMA26"]).map({True: "BULLISH", False: "BEARISH"})
    return df


def get_ema_result(df: pd.DataFrame) -> EMAResult:
    """Extract latest EMA snapshot. df must already contain EMA12/EMA26 columns."""
    last = df.iloc[-1]
    ema12 = float(last["EMA12"])
    ema26 = float(last["EMA26"])
    spread_pct = float(last.get("EMA_Spread_Pct", (ema12 - ema26) / ema26 * 100))
    bias = "BULLISH" if ema12 > ema26 else "BEARISH"
    strength = min(100.0, max(10.0, abs(spread_pct) * 30))
    return EMAResult(
        ema12=round(ema12, 4),
        ema26=round(ema26, 4),
        bias=bias,
        spread_pct=round(spread_pct, 4),
        alignment_strength=round(strength, 1),
    )
