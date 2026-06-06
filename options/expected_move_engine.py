"""
Expected Move Engine
=====================
ExpectedMove = Price × IV × sqrt(DTE / 365)

1 SD = ExpectedMove → ~68% probability price stays inside ±1SD
"""
from __future__ import annotations
import math
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class ExpectedMoveResult:
    price:             float
    iv:                float
    dte:               int
    expected_move:     float
    expected_move_pct: float
    upper_1sd:         float
    lower_1sd:         float
    upper_1_5sd:       float
    lower_1_5sd:       float
    upper_2sd:         float
    lower_2sd:         float


def compute_expected_move(price: float, iv: float, dte: int) -> ExpectedMoveResult:
    if price <= 0 or iv <= 0 or dte <= 0:
        raise ValueError(f"Invalid inputs: price={price} iv={iv} dte={dte}")
    t   = dte / 365.0
    em  = price * iv * math.sqrt(t)
    pct = em / price * 100
    return ExpectedMoveResult(
        price=round(price, 4), iv=round(iv, 4), dte=dte,
        expected_move=round(em, 4), expected_move_pct=round(pct, 2),
        upper_1sd=round(price + em, 4),    lower_1sd=round(price - em, 4),
        upper_1_5sd=round(price + em*1.5, 4), lower_1_5sd=round(price - em*1.5, 4),
        upper_2sd=round(price + em*2.0, 4),   lower_2sd=round(price - em*2.0, 4),
    )


def select_dte(regime: str, iv_rank: float) -> int:
    """Optimal DTE by regime + IV environment."""
    if iv_rank >= 65:
        return 21 if regime in ("BULL","BEAR","STRONG_BULL","STRONG_BEAR") else 30
    if iv_rank <= 30:
        return 45 if regime in ("BULL","BEAR") else 60
    return 30 if regime in ("BULL","BEAR","STRONG_BULL","STRONG_BEAR") else 45


def choose_dte_for_strategy(strategy_name: str, dominant_dte: int | None) -> int:
    """
    DTE preference by strategy type.
    Credit strategies prefer shorter DTE (faster theta decay).
    Debit / long-vol strategies prefer longer DTE.
    """
    base = dominant_dte or 30
    short_dte = {"IRON_CONDOR","IRON_BUTTERFLY","SHORT_STRANGLE",
                 "CASH_SECURED_PUT","PUT_CREDIT_SPREAD","BEAR_CALL_SPREAD","COVERED_CALL"}
    long_dte  = {"LONG_STRADDLE","LONG_STRANGLE","LONG_CALL","LONG_PUT",
                 "RISK_REVERSAL","BULL_CALL_SPREAD","PUT_DEBIT_SPREAD"}
    s = strategy_name.upper()
    if s in short_dte:
        return min(base, 30)
    if s in long_dte:
        return max(base, 30)
    return base
