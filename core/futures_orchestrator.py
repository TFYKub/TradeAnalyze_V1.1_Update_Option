"""
Futures Trade Orchestrator
============================
Coordinates the full 11-step futures analysis pipeline per symbol:

  1.  Market data + EMA / RSI / ATR indicators
  2.  Markov HMM regime detection
  3.  Swing detection
  4.  Market structure classification
  5.  Support / Resistance levels
  6.  RSI divergence detection
  7.  Trend filter (EMA + structure + divergence)
  8.  Entry condition check
  9.  Stop loss / Take profit calculation
  10. AI scoring
  11. Monte Carlo + Portfolio risk
  12. Kelly / EV position sizing
  13. Final 7-gate decision
  14. Build full report text

Returns FuturesResult (all sub-results + report text)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import pandas as pd

from ai.scoring_engine import compute_ai_score
from indicators.atr import compute_atr, get_atr_result
from indicators.ema import compute_ema, get_ema_result
from indicators.rsi import compute_rsi, get_rsi_result
from market_structure.structure_break import detect_structure
from market_structure.support_resistance import detect_sr_levels
from market_structure.swing_detector import get_recent_swings
from regime.markov import MarkovRegimeEngine
from report.daily_report import build_daily_report
from risk.position_sizing import compute_position
from risk.stop_loss_engine import compute_sl_tp
from signals.divergence_detector import detect_divergence
from signals.entry_engine import check_entry
from signals.final_decision import evaluate_trade
from signals.trend_filter import apply_trend_filter
from simulation.monte_carlo import run_monte_carlo
from simulation.portfolio_risk import compute_portfolio_risk

logger = logging.getLogger(__name__)

# Default win-rate used for Kelly/EV if no backtest data available
DEFAULT_WIN_RATE = 0.52
DEFAULT_AVG_RR   = 2.5


@dataclass
class FuturesResult:
    symbol:          str
    price:           float
    runtime:         float
    report_text:     str
    final_decision:  str        # "LONG" | "SHORT" | "NO_TRADE"
    ai_score:        float
    regime:          str
    regime_conf:     float
    entry:           float
    stop_loss:       float
    tp1:             float | None
    tp2:             float | None
    rr:              float
    risk_pct:        float
    mc_profit_prob:  float
    kelly:           float
    ev:              float
    sharpe:          float
    approved:        bool


class FuturesOrchestrator:

    def __init__(self, win_rate: float = DEFAULT_WIN_RATE, avg_rr: float = DEFAULT_AVG_RR):
        self._regime_engine = MarkovRegimeEngine()
        self._win_rate      = win_rate
        self._avg_rr        = avg_rr

    def run(self, symbol: str, df: pd.DataFrame) -> FuturesResult:
        """
        Run full futures analysis on a pre-loaded OHLCV DataFrame.

        Parameters
        ----------
        symbol : ticker string (for display)
        df     : daily OHLCV with columns: Open, High, Low, Close, Volume
        """

        t0 = time.time()
        price = float(df["Close"].iloc[-1])

        logger.info("[%s] Futures analysis start | price=%.4f | bars=%d", symbol, price, len(df))

        # ── 1. Indicators ─────────────────────────────────────────────────────
        df = compute_ema(df)
        df = compute_rsi(df, period=14)
        df = compute_atr(df, period=14)

        ema_result = get_ema_result(df)
        rsi_result = get_rsi_result(df, period=14)
        atr_result = get_atr_result(df, period=14)

        # ── 2. Markov Regime ──────────────────────────────────────────────────
        try:
            regime_result = self._regime_engine.detect(df)
        except Exception as exc:
            logger.warning("[%s] Regime detection failed: %s", symbol, exc)
            # Create a safe fallback using EMA bias
            from regime.markov import RegimeResult, _PERMISSION_MAP
            fallback_regime = "BULL" if ema_result.bias == "BULLISH" else "BEAR"
            perm, mult = _PERMISSION_MAP[fallback_regime]
            regime_result = RegimeResult(
                current_regime=fallback_regime, regime_probability=0.55,
                confidence=55.0, regime_probs_all={fallback_regime: 0.55},
                transition_matrix={}, expected_next_regime=fallback_regime,
                feature_snapshot={}, trade_permission=perm, position_size_mult=mult,
            )

        # ── 3. Swing Detection ────────────────────────────────────────────────
        swing_data   = get_recent_swings(df)
        swing_highs  = swing_data["all_highs"]
        swing_lows   = swing_data["all_lows"]
        last_sh      = swing_data["last_swing_high"]
        last_sl      = swing_data["last_swing_low"]

        # ── 4. Market Structure ───────────────────────────────────────────────
        structure = detect_structure(swing_highs, swing_lows, price)

        # ── 5. Support / Resistance ───────────────────────────────────────────
        sr = detect_sr_levels(df, swing_highs, swing_lows, price)

        # ── 6. RSI Divergence ─────────────────────────────────────────────────
        divergence = detect_divergence(df, rsi_col="RSI14")

        # ── 7. Trend Filter ───────────────────────────────────────────────────
        trend_filter = apply_trend_filter(
            ema       = ema_result,
            structure = structure,
            divergence= divergence,
            regime    = regime_result.current_regime,
        )

        # ── 8. Entry Conditions ───────────────────────────────────────────────
        entry_result = check_entry(
            df            = df,
            final_bias    = trend_filter.final_bias,
            supports      = sr["supports"],
            resistances   = sr["resistances"],
            current_price = price,
        )

        direction = entry_result.direction   # "LONG" | "SHORT" | "WAIT"

        # ── 9. SL / TP ────────────────────────────────────────────────────────
        risk = compute_sl_tp(
            direction   = direction,
            entry       = price,
            atr         = atr_result.atr14,
            swing_low   = last_sl.price if last_sl else None,
            swing_high  = last_sh.price if last_sh else None,
            supports    = sr["supports"],
            resistances = sr["resistances"],
        )

        best_rr = max(risk.rr1, risk.rr2)

        # ── 10. AI Scoring ────────────────────────────────────────────────────
        ai_score = compute_ai_score(
            regime             = regime_result.current_regime,
            regime_confidence  = regime_result.confidence,
            structure_trend    = structure.trend,
            structure_clarity  = structure.structure_score,
            ema_alignment      = ema_result.alignment_strength,
            ema_bias           = ema_result.bias,
            rsi_value          = rsi_result.value,
            rsi_momentum       = rsi_result.momentum,
            rr                 = best_rr,
            direction          = direction,
        )

        # ── 11. Monte Carlo ───────────────────────────────────────────────────
        mc = run_monte_carlo(
            close_series = df["Close"],
            entry        = price,
            stop_loss    = risk.stop_loss,
            target       = risk.tp2 or price * 1.04,
            horizon      = 20,
            simulations  = 10_000,
        )

        # ── Portfolio Risk ────────────────────────────────────────────────────
        port = compute_portfolio_risk(df["Close"])

        # ── 12. Position Sizing (Kelly / EV) ──────────────────────────────────
        position = compute_position(
            win_rate = self._win_rate,
            avg_rr   = max(self._avg_rr, best_rr),
            regime   = regime_result.current_regime,
        )

        # ── 13. Final Decision ────────────────────────────────────────────────
        final = evaluate_trade(
            direction          = direction,
            regime_confidence  = regime_result.confidence,
            ai_score           = ai_score.final_score,
            expected_value     = position.ev,
            kelly_fraction     = position.kelly_fraction,
            mc_profit_prob     = mc.prob_profit,
            best_rr            = best_rr,
            structure_trend    = structure.trend,
            ema_bias           = ema_result.bias,
        )

        # ── 14. Report ────────────────────────────────────────────────────────
        report_text = build_daily_report(
            symbol       = symbol,
            price        = price,
            regime       = regime_result,
            ema          = ema_result,
            rsi          = rsi_result,
            structure    = structure,
            divergence   = divergence,
            trend_filter = trend_filter,
            sr           = sr,
            risk         = risk,
            ai_score     = ai_score,
            mc           = mc,
            port         = port,
            position     = position,
            entry_result = entry_result,
            final        = final,
        )

        runtime = round(time.time() - t0, 2)
        logger.info(
            "[%s] Done in %.1fs | regime=%s conf=%.0f%% | "
            "decision=%s ai=%.0f rr=%.1f mc=%.1f%%",
            symbol, runtime,
            regime_result.current_regime, regime_result.confidence,
            final.decision, ai_score.final_score, best_rr, mc.prob_profit,
        )

        return FuturesResult(
            symbol         = symbol,
            price          = price,
            runtime        = runtime,
            report_text    = report_text,
            final_decision = final.decision,
            ai_score       = ai_score.final_score,
            regime         = regime_result.current_regime,
            regime_conf    = regime_result.confidence,
            entry          = risk.entry,
            stop_loss      = risk.stop_loss,
            tp1            = risk.tp1,
            tp2            = risk.tp2,
            rr             = best_rr,
            risk_pct       = position.risk_pct,
            mc_profit_prob = mc.prob_profit,
            kelly          = position.kelly_fraction,
            ev             = position.ev,
            sharpe         = port.sharpe,
            approved       = final.approved,
        )
