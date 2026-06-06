"""
Entry Engine
=============
ตรวจหา entry condition สำหรับ LONG และ SHORT

LONG SETUP:
  ✓ EMA12 > EMA26
  ✓ Bullish market structure (HH-HL)
  ✓ Pullback toward support zone
  ✓ Bullish confirmation candle (close > open, close > prev close)

SHORT SETUP:
  ✓ EMA12 < EMA26
  ✓ Bearish market structure (LL-LH)
  ✓ Pullback toward resistance zone
  ✓ Bearish confirmation candle (close < open, close < prev close)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass
import pandas as pd

logger = logging.getLogger(__name__)

PULLBACK_ZONE_PCT = 0.03   # within 3% of nearest S/R = "at zone"


@dataclass(frozen=True)
class EntryResult:
    valid:               bool
    direction:           str    # "LONG" | "SHORT" | "WAIT"
    entry_price:         float
    pullback_confirmed:  bool
    confirmation_candle: bool
    reason:              str


def _is_bullish_candle(df: pd.DataFrame) -> bool:
    """Last candle: close > open AND close > previous close."""
    if len(df) < 2:
        return False
    last = df.iloc[-1]
    prev = df.iloc[-2]
    return float(last["Close"]) > float(last["Open"]) and float(last["Close"]) > float(prev["Close"])


def _is_bearish_candle(df: pd.DataFrame) -> bool:
    """Last candle: close < open AND close < previous close."""
    if len(df) < 2:
        return False
    last = df.iloc[-1]
    prev = df.iloc[-2]
    return float(last["Close"]) < float(last["Open"]) and float(last["Close"]) < float(prev["Close"])


def _near_level(price: float, level: float, pct: float = PULLBACK_ZONE_PCT) -> bool:
    return abs(price - level) / level <= pct


def check_entry(
    df:           pd.DataFrame,
    final_bias:   str,              # from TrendFilterResult
    supports:     list,             # SRLevel list
    resistances:  list,
    current_price: float,
) -> EntryResult:
    """
    Check whether current bar satisfies entry conditions.

    Returns EntryResult with direction and validity.
    """
    _wait = lambda reason: EntryResult(
        valid=False, direction="WAIT", entry_price=current_price,
        pullback_confirmed=False, confirmation_candle=False, reason=reason,
    )

    if final_bias not in ("LONG_ONLY", "SHORT_ONLY"):
        return _wait(f"Bias is {final_bias} — no entry")

    # ── LONG ─────────────────────────────────────────────────────────────────
    if final_bias == "LONG_ONLY":
        # Pullback: price near support
        near_support = any(_near_level(current_price, s.price) for s in supports)
        bull_candle  = _is_bullish_candle(df)

        if near_support and bull_candle:
            return EntryResult(
                valid=True, direction="LONG", entry_price=current_price,
                pullback_confirmed=True, confirmation_candle=True,
                reason="LONG: price at support + bullish confirmation candle",
            )
        if near_support:
            return EntryResult(
                valid=False, direction="WAIT", entry_price=current_price,
                pullback_confirmed=True, confirmation_candle=False,
                reason="LONG: at support but awaiting bullish candle",
            )
        return _wait("LONG: price not yet at support zone")

    # ── SHORT ────────────────────────────────────────────────────────────────
    if final_bias == "SHORT_ONLY":
        near_resistance = any(_near_level(current_price, r.price) for r in resistances)
        bear_candle     = _is_bearish_candle(df)

        if near_resistance and bear_candle:
            return EntryResult(
                valid=True, direction="SHORT", entry_price=current_price,
                pullback_confirmed=True, confirmation_candle=True,
                reason="SHORT: price at resistance + bearish confirmation candle",
            )
        if near_resistance:
            return EntryResult(
                valid=False, direction="WAIT", entry_price=current_price,
                pullback_confirmed=True, confirmation_candle=False,
                reason="SHORT: at resistance but awaiting bearish candle",
            )
        return _wait("SHORT: price not yet at resistance zone")

    return _wait("Unknown bias")
