"""
AI Trade Scoring Engine
========================
คำนวณ AI Score 0–100 จาก 5 components:

  Regime Score      (30%) — ขึ้นกับ regime + confidence
  Market Structure  (25%) — HH-HL vs LL-LH clarity
  Trend Score       (20%) — EMA alignment strength
  Momentum Score    (15%) — RSI confirming trend
  Risk Reward Score (10%) — RR ratio quality

Formula:
  FINAL = (Regime*0.30) + (Structure*0.25) + (Trend*0.20) + (Momentum*0.15) + (RR*0.10)

Trade allowed only if FINAL_AI_SCORE >= 70
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MIN_AI_SCORE = 70.0   # threshold to allow trade


@dataclass(frozen=True)
class AIScoreResult:
    final_score:       float   # 0–100 composite
    regime_score:      float
    structure_score:   float
    trend_score:       float
    momentum_score:    float
    rr_score:          float
    trade_allowed:     bool
    breakdown:         dict[str, float]
    reason:            str


# ──────────────────────────────────────────────────────────────────────────────
# COMPONENT SCORERS
# ──────────────────────────────────────────────────────────────────────────────

def _regime_score(regime: str, confidence: float) -> float:
    """
    Base score per regime × confidence scaling.

    STRONG_BULL / STRONG_BEAR = 100
    BULL / BEAR               =  80
    RANGE                     =  50
    """
    base = {
        "STRONG_BULL": 100.0,
        "BULL":         80.0,
        "RANGE":        50.0,
        "BEAR":         80.0,
        "STRONG_BEAR": 100.0,
    }.get(regime, 40.0)

    # Scale by confidence: if confidence = 100 → full score; 60 → 60% of base
    conf_factor = max(0.0, confidence / 100.0)
    return round(base * conf_factor, 1)


def _structure_score(structure_trend: str, structure_score: float) -> float:
    """
    Clear HH-HL or LL-LH = 100, Mixed = 50, Unknown = 20.
    Scale by the structure clarity score from StructureResult.
    """
    if structure_trend in ("BULLISH", "BEARISH"):
        base = 100.0
    elif structure_trend == "MIXED":
        base = 50.0
    else:
        base = 20.0

    # structure_score is already 0–100 from structure_break.py
    return round((base + structure_score) / 2, 1)


def _trend_score(alignment_strength: float, bias: str, structure_trend: str, regime: str) -> float:
    """
    EMA alignment strength (0–100) × direction agreement bonus.
    """
    score = alignment_strength   # already 0–100 from EMAResult

    # Bonus: EMA bias agrees with regime direction
    ema_bull = bias == "BULLISH"
    ema_bear = bias == "BEARISH"
    regime_bull = regime in ("STRONG_BULL", "BULL")
    regime_bear = regime in ("STRONG_BEAR", "BEAR")

    if (ema_bull and regime_bull) or (ema_bear and regime_bear):
        score = min(100.0, score * 1.15)

    # Penalise if structure contradicts EMA
    if structure_trend == "MIXED":
        score *= 0.85

    return round(score, 1)


def _momentum_score(rsi_value: float, rsi_momentum: str, direction: str) -> float:
    """
    RSI confirming trend direction = 100, neutral = 50, contra = 20.

    LONG  + RSI BULLISH + RSI < 70 (not overbought) = best
    SHORT + RSI BEARISH + RSI > 30 (not oversold)   = best
    """
    if direction == "LONG":
        if rsi_momentum == "BULLISH" and 40 <= rsi_value <= 70:
            return 100.0
        if rsi_momentum == "BULLISH":
            return 75.0
        if 45 <= rsi_value <= 55:
            return 50.0
        return 20.0

    if direction == "SHORT":
        if rsi_momentum == "BEARISH" and 30 <= rsi_value <= 60:
            return 100.0
        if rsi_momentum == "BEARISH":
            return 75.0
        if 45 <= rsi_value <= 55:
            return 50.0
        return 20.0

    # WAIT — neutral
    return 50.0


def _rr_score(rr: float) -> float:
    """
    RR >= 4 = 100, >= 3 = 80, >= 2 = 60, < 2 = 0 (reject)
    """
    if rr >= 4.0:
        return 100.0
    if rr >= 3.0:
        return 80.0
    if rr >= 2.0:
        return 60.0
    return 0.0   # below MIN_RR → will trigger rejection elsewhere too


# ──────────────────────────────────────────────────────────────────────────────
# MAIN SCORER
# ──────────────────────────────────────────────────────────────────────────────
def compute_ai_score(
    regime:             str,
    regime_confidence:  float,          # 0–100
    structure_trend:    str,            # "BULLISH" | "BEARISH" | "MIXED" | "UNKNOWN"
    structure_clarity:  float,          # 0–100  from StructureResult.structure_score
    ema_alignment:      float,          # 0–100  from EMAResult.alignment_strength
    ema_bias:           str,            # "BULLISH" | "BEARISH"
    rsi_value:          float,          # 0–100
    rsi_momentum:       str,            # "BULLISH" | "BEARISH"
    rr:                 float,          # best R:R ratio
    direction:          str,            # "LONG" | "SHORT" | "WAIT"
) -> AIScoreResult:
    """
    Compute the 5-component AI trade score.

    Parameters
    ----------
    All inputs are plain scalars extracted from their respective result objects.
    """

    rs  = _regime_score(regime, regime_confidence)
    ss  = _structure_score(structure_trend, structure_clarity)
    ts  = _trend_score(ema_alignment, ema_bias, structure_trend, regime)
    ms  = _momentum_score(rsi_value, rsi_momentum, direction)
    rrs = _rr_score(rr)

    final = (
        rs  * 0.30
        + ss  * 0.25
        + ts  * 0.20
        + ms  * 0.15
        + rrs * 0.10
    )
    final = round(final, 1)

    trade_allowed = final >= MIN_AI_SCORE and direction != "WAIT"

    breakdown = {
        "regime_score":    rs,
        "structure_score": ss,
        "trend_score":     ts,
        "momentum_score":  ms,
        "rr_score":        rrs,
        "weights":         "30% / 25% / 20% / 15% / 10%",
    }

    reason = (
        f"AI Score {final:.0f} ≥ {MIN_AI_SCORE} → TRADE ALLOWED"
        if trade_allowed
        else f"AI Score {final:.0f} < {MIN_AI_SCORE} → NO TRADE"
    )

    return AIScoreResult(
        final_score     = final,
        regime_score    = rs,
        structure_score = ss,
        trend_score     = ts,
        momentum_score  = ms,
        rr_score        = rrs,
        trade_allowed   = trade_allowed,
        breakdown       = breakdown,
        reason          = reason,
    )
