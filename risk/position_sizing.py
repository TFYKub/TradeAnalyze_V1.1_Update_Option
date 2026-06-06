"""
Position Sizing Engine
=======================
Kelly Criterion + Half-Kelly + Regime-adjusted risk

Kelly = (W × R - L) / R
  W = win probability
  L = 1 - W (loss probability)
  R = reward/risk ratio

Conservative: Half-Kelly (Kelly × 0.5)
Maximum risk cap: 2% of account

Regime risk multiplier:
  STRONG_BULL / STRONG_BEAR = 100%
  BULL / BEAR               =  75%
  RANGE                     =  50%
"""
from __future__ import annotations
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BASE_RISK_PCT  = 0.01    # 1% base risk per trade
MAX_RISK_PCT   = 0.02    # 2% hard cap
MIN_KELLY      = 0.01    # minimum Kelly to allow trade

REGIME_RISK_MAP = {
    "STRONG_BULL": 1.00,
    "BULL":        0.75,
    "RANGE":       0.50,
    "BEAR":        0.75,
    "STRONG_BEAR": 1.00,
}


@dataclass(frozen=True)
class PositionResult:
    win_rate:       float
    avg_rr:         float
    kelly_fraction: float
    half_kelly:     float
    regime_mult:    float
    risk_pct:       float   # final risk % of account
    kelly_valid:    bool
    ev:             float   # Expected Value in R
    reason:         str


def compute_position(
    win_rate: float,   # 0–1
    avg_rr:   float,   # historical avg reward/risk
    regime:   str,
) -> PositionResult:
    """
    Calculate Kelly fraction and adjusted position size.

    Parameters
    ----------
    win_rate : historical win rate (0–1), e.g. 0.55
    avg_rr   : average reward/risk ratio, e.g. 2.5
    regime   : Markov regime string
    """
    w = max(0.01, min(0.99, win_rate))
    l = 1 - w
    r = max(0.1, avg_rr)

    kelly     = (w * r - l) / r
    half_kelly = kelly * 0.5
    ev         = (w * r) - (l * 1)   # Expected Value in R units

    regime_mult = REGIME_RISK_MAP.get(regime, 0.75)
    raw_risk    = BASE_RISK_PCT * regime_mult * max(0, half_kelly) * 2
    risk_pct    = min(MAX_RISK_PCT, max(0.001, raw_risk))

    kelly_valid = kelly > MIN_KELLY and ev > 0

    reason = (
        f"Kelly={kelly:.3f} HalfKelly={half_kelly:.3f} EV={ev:.2f}R risk={risk_pct*100:.2f}%"
        if kelly_valid
        else f"Kelly={kelly:.3f} ≤ 0 or EV={ev:.2f} ≤ 0 → NO TRADE"
    )

    return PositionResult(
        win_rate=round(w, 3),
        avg_rr=round(r, 2),
        kelly_fraction=round(kelly, 4),
        half_kelly=round(half_kelly, 4),
        regime_mult=regime_mult,
        risk_pct=round(risk_pct, 4),
        kelly_valid=kelly_valid,
        ev=round(ev, 3),
        reason=reason,
    )
