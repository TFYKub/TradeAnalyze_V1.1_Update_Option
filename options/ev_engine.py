"""EV + Kelly Engine"""
from __future__ import annotations
import math, logging
from dataclasses import replace
from options.strategy_models import StrategySetup

logger = logging.getLogger(__name__)
MAX_KELLY = 0.25


def compute_ev_and_kelly(setup: StrategySetup, pop: float, expected_move: float) -> StrategySetup:
    w = max(0.01, min(0.99, pop / 100))
    l = 1 - w

    avg_win  = (max(abs(setup.max_loss) * 1.5, expected_move * 0.5)
                if math.isinf(setup.max_profit) else max(setup.max_profit, 0.01))
    avg_loss = (setup.max_profit * 5 if (math.isinf(setup.max_loss) and setup.max_profit > 0)
                else expected_move if math.isinf(setup.max_loss)
                else setup.max_loss)
    avg_loss = max(float(avg_loss), 0.01)

    ev    = (w * avg_win) - (l * avg_loss)
    r     = avg_win / avg_loss           # always > 0 now
    kelly = max(0.0, min(MAX_KELLY, (w * r - l) / r))

    return replace(setup,
        pop=round(pop, 1), ev=round(ev, 2),
        kelly=round(kelly, 4), half_kelly=round(kelly*0.5, 4), quarter_kelly=round(kelly*0.25, 4),
    )


def compute_ev_batch(setups: list[StrategySetup], pops: dict[str, float], expected_move: float) -> list[StrategySetup]:
    return [compute_ev_and_kelly(s, pops.get(s.name, 50.0), expected_move) for s in setups]
