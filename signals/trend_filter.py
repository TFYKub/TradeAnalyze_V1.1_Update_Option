"""
Trend Filter + Reversal Logic
==============================
Priority:
1. Markov Regime gate
2. EMA12/EMA26 bias
3. Market structure (HH-HL vs LL-LH)
4. RSI Divergence reversal
5. Return final_bias

Changes from v1:
- MIXED structure is relaxed: EMA bias alone is sufficient for LONG/SHORT
  when regime agrees — avoids over-filtering on choppy periods
- REVERSAL requires BOTH divergence + BOS (structure.bos_bullish/bearish)
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

from indicators.ema import EMAResult
from market_structure.structure_break import StructureResult
from signals.divergence_detector import DivergenceResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TrendFilterResult:
    final_bias:    str    # "LONG_ONLY" | "SHORT_ONLY" | "REVERSAL_WATCH" | "NO_TRADE"
    reason:        str
    reversal_mode: bool
    reversal_dir:  str    # "BULLISH" | "BEARISH" | "NONE"
    trend_score:   float  # 0–100


def apply_trend_filter(
    ema:        EMAResult,
    structure:  StructureResult,
    divergence: DivergenceResult,
    regime:     str,
) -> TrendFilterResult:

    regime_allows_long  = regime in ("STRONG_BULL", "BULL", "RANGE")
    regime_allows_short = regime in ("STRONG_BEAR", "BEAR", "RANGE")

    ema_long  = ema.bias == "BULLISH"
    ema_short = ema.bias == "BEARISH"

    struct_bull = structure.trend in ("BULLISH", "MIXED")
    struct_bear = structure.trend in ("BEARISH", "MIXED")

    # ── Reversal: RSI div + Break-of-Structure BOTH required ──────────────────
    reversal_mode = False
    reversal_dir  = "NONE"

    if (not ema_long and divergence.kind == "BULLISH"
            and divergence.detected and structure.bos_bullish):
        reversal_mode, reversal_dir = True, "BULLISH"

    if (not ema_short and divergence.kind == "BEARISH"
            and divergence.detected and structure.bos_bearish):
        reversal_mode, reversal_dir = True, "BEARISH"

    if reversal_mode and reversal_dir == "BULLISH" and regime_allows_long:
        return TrendFilterResult(
            final_bias="LONG_ONLY",
            reason=f"Bullish reversal: RSI div + BOS (regime={regime})",
            reversal_mode=True, reversal_dir="BULLISH", trend_score=70.0,
        )

    if reversal_mode and reversal_dir == "BEARISH" and regime_allows_short:
        return TrendFilterResult(
            final_bias="SHORT_ONLY",
            reason=f"Bearish reversal: RSI div + BOS (regime={regime})",
            reversal_mode=True, reversal_dir="BEARISH", trend_score=70.0,
        )

    # ── Normal trend-following ────────────────────────────────────────────────
    # STRONG regime: EMA alone is sufficient
    if regime in ("STRONG_BULL",) and ema_long and regime_allows_long:
        return TrendFilterResult(
            final_bias="LONG_ONLY",
            reason=f"STRONG_BULL + EMA BULLISH (structure={structure.trend})",
            reversal_mode=False, reversal_dir="NONE",
            trend_score=min(100, ema.alignment_strength * 1.2),
        )

    if regime in ("STRONG_BEAR",) and ema_short and regime_allows_short:
        return TrendFilterResult(
            final_bias="SHORT_ONLY",
            reason=f"STRONG_BEAR + EMA BEARISH (structure={structure.trend})",
            reversal_mode=False, reversal_dir="NONE",
            trend_score=min(100, ema.alignment_strength * 1.2),
        )

    # BULL/BEAR: require EMA + structure (MIXED allowed)
    if ema_long and struct_bull and regime_allows_long:
        return TrendFilterResult(
            final_bias="LONG_ONLY",
            reason=f"EMA BULLISH + {structure.trend} structure (regime={regime})",
            reversal_mode=False, reversal_dir="NONE",
            trend_score=ema.alignment_strength,
        )

    if ema_short and struct_bear and regime_allows_short:
        return TrendFilterResult(
            final_bias="SHORT_ONLY",
            reason=f"EMA BEARISH + {structure.trend} structure (regime={regime})",
            reversal_mode=False, reversal_dir="NONE",
            trend_score=ema.alignment_strength,
        )

    # Divergence watch
    if divergence.detected:
        return TrendFilterResult(
            final_bias="REVERSAL_WATCH",
            reason=f"{divergence.kind} divergence — awaiting BOS confirmation",
            reversal_mode=False, reversal_dir=divergence.kind, trend_score=40.0,
        )

    return TrendFilterResult(
        final_bias="NO_TRADE",
        reason=f"No alignment: regime={regime} EMA={ema.bias} structure={structure.trend}",
        reversal_mode=False, reversal_dir="NONE", trend_score=20.0,
    )
