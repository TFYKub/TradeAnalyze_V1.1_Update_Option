"""
Market Structure Break Detector
=================================
Detects:
  • Higher High (HH) + Higher Low (HL) → BULLISH structure
  • Lower Low  (LL) + Lower High (LH) → BEARISH structure
  • Structure Break (BOS — Break of Structure)

Used for:
  • Reversal confirmation after RSI divergence
  • Trend continuation confirmation
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from market_structure.swing_detector import SwingPoint

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StructureResult:
    trend:          str          # "BULLISH" | "BEARISH" | "MIXED" | "UNKNOWN"
    pattern:        str          # "HH-HL" | "LL-LH" | "MIXED" | "UNKNOWN"
    bos_bullish:    bool         # Break of swing high → bullish BOS
    bos_bearish:    bool         # Break of swing low  → bearish BOS
    last_hh:        float | None
    last_hl:        float | None
    last_ll:        float | None
    last_lh:        float | None
    structure_score: float       # 0–100 clarity score


def detect_structure(
    highs: list[SwingPoint],
    lows:  list[SwingPoint],
    current_price: float,
) -> StructureResult:
    """
    Analyse the last 3 swing highs and lows to determine market structure.

    Parameters
    ----------
    highs         : swing high list (ascending index order)
    lows          : swing low list  (ascending index order)
    current_price : latest close price
    """
    # Need at least 2 of each
    if len(highs) < 2 or len(lows) < 2:
        return StructureResult(
            trend="UNKNOWN", pattern="UNKNOWN",
            bos_bullish=False, bos_bearish=False,
            last_hh=None, last_hl=None, last_ll=None, last_lh=None,
            structure_score=0.0,
        )

    h_prices = [s.price for s in highs[-3:]]
    l_prices  = [s.price for s in lows[-3:]]

    # HH: each high > previous high
    hh_count = sum(1 for i in range(1, len(h_prices)) if h_prices[i] > h_prices[i - 1])
    hl_count = sum(1 for i in range(1, len(l_prices))  if l_prices[i] > l_prices[i - 1])
    ll_count = sum(1 for i in range(1, len(l_prices))  if l_prices[i] < l_prices[i - 1])
    lh_count = sum(1 for i in range(1, len(h_prices))  if h_prices[i] < h_prices[i - 1])

    max_count = max(len(h_prices), len(l_prices)) - 1 or 1

    bullish_score = (hh_count + hl_count) / (2 * max_count) * 100
    bearish_score = (ll_count + lh_count) / (2 * max_count) * 100

    if bullish_score >= 66:
        trend   = "BULLISH"
        pattern = "HH-HL"
        score   = bullish_score
    elif bearish_score >= 66:
        trend   = "BEARISH"
        pattern = "LL-LH"
        score   = bearish_score
    else:
        trend   = "MIXED"
        pattern = "MIXED"
        score   = 40.0

    # Break of Structure
    bos_bullish = current_price > highs[-1].price if highs else False
    bos_bearish = current_price < lows[-1].price  if lows  else False

    return StructureResult(
        trend=trend,
        pattern=pattern,
        bos_bullish=bos_bullish,
        bos_bearish=bos_bearish,
        last_hh=max(h_prices) if hh_count else None,
        last_hl=max(l_prices) if hl_count else None,
        last_ll=min(l_prices) if ll_count else None,
        last_lh=min(h_prices) if lh_count else None,
        structure_score=round(score, 1),
    )
