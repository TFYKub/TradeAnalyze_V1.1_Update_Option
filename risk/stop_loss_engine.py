"""
Stop Loss Engine
=================
LONG  SL: SwingLow  - (ATR × ATR_MULTIPLIER)
SHORT SL: SwingHigh + (ATR × ATR_MULTIPLIER)

Take Profit:
  TP1 = nearest resistance (LONG) / support (SHORT)
  TP2 = next major resistance/support
  Minimum RR = 2.0 → reject trade if below
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

ATR_MULTIPLIER = 1.0
MIN_RR         = 2.0


@dataclass(frozen=True)
class RiskResult:
    direction:    str
    entry:        float
    stop_loss:    float
    tp1:          float | None
    tp2:          float | None
    risk:         float    # $ distance from entry to SL
    rr1:          float    # R:R to TP1
    rr2:          float    # R:R to TP2
    valid_rr:     bool     # True if max(rr1, rr2) >= MIN_RR
    reason:       str


def compute_sl_tp(
    direction:   str,
    entry:       float,
    atr:         float,
    swing_low:   float | None,
    swing_high:  float | None,
    supports:    list,       # SRLevel list (sorted descending)
    resistances: list,       # SRLevel list (sorted ascending)
) -> RiskResult:
    """
    Calculate SL and TP based on swing points + ATR buffer.
    """
    def _rr(target: float) -> float:
        if risk <= 0:
            return 0.0
        return abs(target - entry) / risk

    # ── Stop Loss ─────────────────────────────────────────────────────────────
    if direction == "LONG":
        sl_base = swing_low if swing_low else entry * 0.97
        stop_loss = sl_base - atr * ATR_MULTIPLIER

        # TP = resistance levels above entry
        above = [r for r in resistances if r.price > entry]
        tp1 = above[0].price if len(above) >= 1 else entry * 1.04
        tp2 = above[1].price if len(above) >= 2 else entry * 1.08

    elif direction == "SHORT":
        sl_base = swing_high if swing_high else entry * 1.03
        stop_loss = sl_base + atr * ATR_MULTIPLIER

        # TP = support levels below entry
        below = [s for s in supports if s.price < entry]
        tp1 = below[0].price if len(below) >= 1 else entry * 0.96
        tp2 = below[1].price if len(below) >= 2 else entry * 0.92

    else:
        return RiskResult(
            direction="WAIT", entry=entry, stop_loss=entry,
            tp1=None, tp2=None, risk=0, rr1=0, rr2=0,
            valid_rr=False, reason="No direction",
        )

    risk = abs(entry - stop_loss)
    rr1  = _rr(tp1)
    rr2  = _rr(tp2)
    best_rr = max(rr1, rr2)
    valid   = best_rr >= MIN_RR

    reason = (
        f"RR {best_rr:.1f} ≥ {MIN_RR} ✓" if valid
        else f"RR {best_rr:.1f} < {MIN_RR} — REJECTED"
    )

    return RiskResult(
        direction=direction,
        entry=round(entry, 4),
        stop_loss=round(stop_loss, 4),
        tp1=round(tp1, 4),
        tp2=round(tp2, 4),
        risk=round(risk, 4),
        rr1=round(rr1, 2),
        rr2=round(rr2, 2),
        valid_rr=valid,
        reason=reason,
    )
