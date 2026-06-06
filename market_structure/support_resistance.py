"""
Support & Resistance Engine
============================
ตรวจจับและจัด rank ระดับ S/R จากหลายแหล่ง:

  • Daily Swing Highs / Lows
  • Supply Zones (bearish rejection clusters)
  • Demand Zones (bullish reversal clusters)
  • Previous Weekly High / Low
  • 52-Week High / Low

แต่ละระดับมี:
  • price         : ราคา
  • kind          : RESISTANCE | SUPPORT
  • source        : swing / zone / weekly / yearly
  • touch_count   : จำนวนครั้งที่ price กลับตัวที่ระดับนี้
  • strength_score: 0–100
  • distance_pct  : ระยะห่างจาก current price (%)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

ZONE_TOLERANCE = 0.005   # 0.5% tolerance to cluster nearby levels
MIN_TOUCH      = 1       # minimum touches to keep a level


@dataclass
class SRLevel:
    price:         float
    kind:          str    # "SUPPORT" | "RESISTANCE"
    source:        str    # "swing" | "zone" | "weekly" | "yearly"
    touch_count:   int
    strength_score: float  # 0–100
    distance_pct:  float   # positive = above current price


def _touches(df: pd.DataFrame, level: float, tol: float = ZONE_TOLERANCE) -> int:
    """Count candles that touched the level (High/Low within tolerance band)."""
    band_hi = level * (1 + tol)
    band_lo = level * (1 - tol)
    touches = ((df["High"] >= band_lo) & (df["Low"] <= band_hi)).sum()
    return int(touches)


def _cluster_levels(levels: list[float], tol: float = ZONE_TOLERANCE) -> list[float]:
    """Merge nearby price levels into a single representative level."""
    if not levels:
        return []
    levels = sorted(levels)
    clusters: list[list[float]] = [[levels[0]]]
    for price in levels[1:]:
        if price <= clusters[-1][-1] * (1 + tol):
            clusters[-1].append(price)
        else:
            clusters.append([price])
    return [float(np.mean(c)) for c in clusters]


def detect_sr_levels(
    df: pd.DataFrame,
    swing_highs: list,
    swing_lows:  list,
    current_price: float,
    n_levels: int = 5,
) -> dict:
    """
    Build ranked S/R level list.

    Parameters
    ----------
    df             : full OHLCV DataFrame (daily)
    swing_highs    : list of SwingPoint (HIGH)
    swing_lows     : list of SwingPoint (LOW)
    current_price  : latest close
    n_levels       : how many top levels to return per side

    Returns
    -------
    {
      "supports":    [SRLevel, ...],
      "resistances": [SRLevel, ...],
      "weekly_high": float | None,
      "weekly_low":  float | None,
      "yearly_high": float | None,
      "yearly_low":  float | None,
    }
    """
    # ── Collect raw resistance prices ─────────────────────────────────────────
    raw_res = [s.price for s in swing_highs]
    # ── Collect raw support prices ────────────────────────────────────────────
    raw_sup = [s.price for s in swing_lows]

    # ── Weekly High/Low (last 5 trading days prior to last bar) ───────────────
    weekly_high = weekly_low = None
    if len(df) >= 10:
        week_slice  = df.iloc[-10:-5]
        weekly_high = float(week_slice["High"].max())
        weekly_low  = float(week_slice["Low"].min())
        raw_res.append(weekly_high)
        raw_sup.append(weekly_low)

    # ── 52-Week High/Low ──────────────────────────────────────────────────────
    yearly_high = yearly_low = None
    if len(df) >= 252:
        yr_slice    = df.iloc[-252:]
        yearly_high = float(yr_slice["High"].max())
        yearly_low  = float(yr_slice["Low"].min())
        raw_res.append(yearly_high)
        raw_sup.append(yearly_low)

    # ── Cluster + filter ──────────────────────────────────────────────────────
    res_prices = _cluster_levels([p for p in raw_res if p > current_price])
    sup_prices = _cluster_levels([p for p in raw_sup if p < current_price])

    # ── Build SRLevel objects ─────────────────────────────────────────────────
    def build_level(price: float, kind: str, source: str) -> SRLevel:
        tc = _touches(df, price)
        dist = (price - current_price) / current_price * 100
        strength = min(100.0, 30 + tc * 15 + (10 if source in ("weekly", "yearly") else 0))
        return SRLevel(
            price=round(price, 4),
            kind=kind,
            source=source,
            touch_count=tc,
            strength_score=round(strength, 1),
            distance_pct=round(dist, 2),
        )

    def infer_source(price: float) -> str:
        if yearly_high and abs(price - yearly_high) / yearly_high < 0.005:
            return "yearly"
        if yearly_low and abs(price - yearly_low) / yearly_low < 0.005:
            return "yearly"
        if weekly_high and abs(price - weekly_high) / weekly_high < 0.005:
            return "weekly"
        if weekly_low and abs(price - weekly_low) / weekly_low < 0.005:
            return "weekly"
        return "swing"

    resistances = sorted(
        [build_level(p, "RESISTANCE", infer_source(p)) for p in res_prices],
        key=lambda l: l.strength_score,
        reverse=True,
    )[:n_levels]

    supports = sorted(
        [build_level(p, "SUPPORT", infer_source(p)) for p in sup_prices],
        key=lambda l: l.strength_score,
        reverse=True,
    )[:n_levels]

    # Sort by proximity for final display
    resistances.sort(key=lambda l: l.price)
    supports.sort(key=lambda l: l.price, reverse=True)

    return {
        "supports":    supports,
        "resistances": resistances,
        "weekly_high": weekly_high,
        "weekly_low":  weekly_low,
        "yearly_high": yearly_high,
        "yearly_low":  yearly_low,
    }
