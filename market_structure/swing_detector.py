"""
Swing High / Swing Low Detector
================================
ใช้ rolling window เพื่อหา swing high และ swing low บน Daily timeframe.

Swing High: high[i] > max(high[i-n:i]) AND high[i] > max(high[i+1:i+n+1])
Swing Low : low[i]  < min(low[i-n:i])  AND low[i]  < min(low[i+1:i+n+1])
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_WINDOW = 5   # bars on each side


@dataclass(frozen=True)
class SwingPoint:
    index:  int
    date:   str
    price:  float
    kind:   str   # "HIGH" | "LOW"


def detect_swings(df: pd.DataFrame, window: int = DEFAULT_WINDOW) -> tuple[list[SwingPoint], list[SwingPoint]]:
    """
    Detect swing highs and swing lows in df.

    Returns
    -------
    (swing_highs, swing_lows) — each sorted ascending by index
    """
    highs: list[SwingPoint] = []
    lows:  list[SwingPoint] = []

    n = len(df)
    high_arr = df["High"].to_numpy()
    low_arr  = df["Low"].to_numpy()
    dates    = df.index.astype(str).tolist()

    for i in range(window, n - window):
        left_high  = high_arr[i - window: i]
        right_high = high_arr[i + 1: i + window + 1]
        left_low   = low_arr[i - window: i]
        right_low  = low_arr[i + 1: i + window + 1]

        if high_arr[i] > left_high.max() and high_arr[i] > right_high.max():
            highs.append(SwingPoint(index=i, date=dates[i], price=float(high_arr[i]), kind="HIGH"))

        if low_arr[i] < left_low.min() and low_arr[i] < right_low.min():
            lows.append(SwingPoint(index=i, date=dates[i], price=float(low_arr[i]), kind="LOW"))

    return highs, lows


def get_recent_swings(
    df: pd.DataFrame,
    window: int = DEFAULT_WINDOW,
    n_recent: int = 5,
) -> dict:
    """
    Return the most recent swing highs and lows as a dict.

    Keys: recent_highs, recent_lows,
          last_swing_high (SwingPoint | None),
          last_swing_low  (SwingPoint | None)
    """
    highs, lows = detect_swings(df, window)
    return {
        "recent_highs":    highs[-n_recent:],
        "recent_lows":     lows[-n_recent:],
        "last_swing_high": highs[-1] if highs else None,
        "last_swing_low":  lows[-1]  if lows  else None,
        "all_highs":       highs,
        "all_lows":        lows,
    }
