"""
Daily Institutional Trade Report
==================================
Formats all engine outputs into a structured LINE / console report.

Format:
  ━ MARKOV REGIME DASHBOARD
  ━ MARKET STRUCTURE ANALYSIS
  ━ KEY SUPPORT / RESISTANCE LEVELS
  ━ TRADE PLAN
  ━ RISK & SIMULATION DASHBOARD
  ━ INSTITUTIONAL TRADE DASHBOARD (final summary)
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _f(x: Any, dec: int = 2) -> str:
    if x is None:
        return "N/A"
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return "N/A"
        return f"{v:.{dec}f}"
    except (TypeError, ValueError):
        return str(x)

def _pct(x: Any) -> str:
    return "N/A" if x is None else f"{float(x):.1f}%"

def _s(x: Any) -> str:
    return "N/A" if (x is None or x == "") else str(x)

def _pct_diff(entry: float, target: float) -> str:
    try:
        d = (target - entry) / entry * 100
        return f"({'+' if d >= 0 else ''}{d:.1f}%)"
    except Exception:
        return ""

def _bar(pct: float, width: int = 10) -> str:
    n = max(0, min(width, round(pct / 100 * width)))
    return "█" * n + "░" * (width - n)

_REGIME_EMOJI = {
    "STRONG_BULL": "🚀", "BULL": "📈",
    "RANGE": "↔️",
    "BEAR": "📉", "STRONG_BEAR": "🔻",
}
_DIR_EMOJI = {"LONG": "🟢", "SHORT": "🔴", "NO_TRADE": "⏸️", "WAIT": "⏸️"}

SEP  = "━" * 28
SEP2 = "─" * 26


# ──────────────────────────────────────────────────────────────────────────────
# SECTION BUILDERS
# ──────────────────────────────────────────────────────────────────────────────
def _section_regime(regime) -> list[str]:
    """regime: RegimeResult"""
    reg   = regime.current_regime
    emoji = _REGIME_EMOJI.get(reg, "❓")
    prob_all = regime.regime_probs_all
    tm    = regime.transition_matrix

    lines = [
        SEP,
        f"📊 MARKOV REGIME DASHBOARD",
        SEP,
        f"Current Regime   : {emoji} {reg}",
        f"Probability      : {_pct(regime.regime_probability * 100)}",
        f"Confidence       : {_pct(regime.confidence)}",
        f"Expected Next    : {_REGIME_EMOJI.get(regime.expected_next_regime,'❓')} {regime.expected_next_regime}",
        f"Trade Permission : {regime.trade_permission}",
        f"Position Mult    : {regime.position_size_mult:.0%}",
        "",
        "Regime Probs ─────────────────",
    ]
    for label, p in sorted(prob_all.items(), key=lambda x: -x[1]):
        bar = _bar(p * 100, 8)
        lines.append(f"  {label:<12} {bar}  {_pct(p * 100)}")

    # Transition matrix: current → all
    lines += ["", f"Transitions from {reg} ──────────"]
    if reg in tm:
        for to_reg, p in sorted(tm[reg].items(), key=lambda x: -x[1])[:4]:
            lines.append(f"  → {to_reg:<12}  {_pct(p * 100)}")

    lines += [
        "",
        f"Features ─────────────────────",
        f"  Daily Return  : {_f(regime.feature_snapshot.get('daily_return'), 3)}%",
        f"  Rolling Vol   : {_f(regime.feature_snapshot.get('rolling_vol_20'), 1)}% ann.",
        f"  EMA Momentum  : {_f(regime.feature_snapshot.get('momentum_score'), 2)}%",
        f"  RSI Normalised: {_f(regime.feature_snapshot.get('rsi_normalised'), 3)}",
    ]
    return lines


def _section_structure(ema, rsi, structure, divergence, trend_filter) -> list[str]:
    return [
        SEP,
        "📐 MARKET STRUCTURE ANALYSIS",
        SEP,
        f"Current Trend   : {_s(ema.bias)}",
        f"EMA12           : {_f(ema.ema12)}",
        f"EMA26           : {_f(ema.ema26)}",
        f"EMA Spread      : {_f(ema.spread_pct, 3)}%",
        f"EMA Strength    : {_f(ema.alignment_strength)}",
        "",
        f"Market Structure: {_s(structure.pattern)}",
        f"Structure Trend : {_s(structure.trend)}",
        f"Clarity Score   : {_f(structure.structure_score)}",
        f"BOS Bullish     : {structure.bos_bullish}",
        f"BOS Bearish     : {structure.bos_bearish}",
        "",
        f"RSI             : {_f(rsi.value)}",
        f"RSI Zone        : {_s(rsi.zone)}",
        f"RSI Momentum    : {_s(rsi.momentum)}",
        "",
        f"RSI Divergence  : {_s(divergence.kind)}",
        f"Div Detected    : {divergence.detected}",
        f"Div Confidence  : {_f(divergence.confidence)}",
        "",
        f"Final Bias      : {_s(trend_filter.final_bias)}",
        f"Bias Reason     : {_s(trend_filter.reason)}",
        f"Reversal Mode   : {trend_filter.reversal_mode}",
    ]


def _section_sr(sr: dict) -> list[str]:
    lines = [SEP, "🏔️  KEY RESISTANCE LEVELS", SEP]
    for i, lvl in enumerate(sr.get("resistances", [])[:3], 1):
        lines.append(
            f"  R{i}: {_f(lvl.price)}  "
            f"dist={_f(lvl.distance_pct, 2)}%  "
            f"touches={lvl.touch_count}  "
            f"score={_f(lvl.strength_score)}"
        )
    lines += [SEP2, "🛖  KEY SUPPORT LEVELS", SEP2]
    for i, lvl in enumerate(sr.get("supports", [])[:3], 1):
        lines.append(
            f"  S{i}: {_f(lvl.price)}  "
            f"dist={_f(lvl.distance_pct, 2)}%  "
            f"touches={lvl.touch_count}  "
            f"score={_f(lvl.strength_score)}"
        )
    if sr.get("weekly_high"):
        lines += [
            "",
            f"  Weekly High : {_f(sr['weekly_high'])}",
            f"  Weekly Low  : {_f(sr['weekly_low'])}",
            f"  52W High    : {_f(sr.get('yearly_high'))}",
            f"  52W Low     : {_f(sr.get('yearly_low'))}",
        ]
    return lines


def _section_trade_plan(risk, ai_score, entry_result) -> list[str]:
    d       = risk.direction
    emoji   = _DIR_EMOJI.get(d, "❓")
    rr_best = max(risk.rr1, risk.rr2)
    return [
        SEP,
        "📋 TRADE PLAN",
        SEP,
        f"Direction       : {emoji} {d}",
        f"Entry           : {_f(risk.entry)}",
        f"Stop Loss       : {_f(risk.stop_loss)}  {_pct_diff(risk.entry, risk.stop_loss)}",
        f"Target 1 (TP1)  : {_f(risk.tp1)}  {_pct_diff(risk.entry, risk.tp1)}",
        f"Target 2 (TP2)  : {_f(risk.tp2)}  {_pct_diff(risk.entry, risk.tp2)}",
        f"Risk Per Trade  : {_f(risk.risk)}",
        f"RR1             : {_f(risk.rr1, 2)}",
        f"RR2             : {_f(risk.rr2, 2)}",
        f"RR Valid (≥2.0) : {risk.valid_rr}",
        "",
        f"AI Score        : {_f(ai_score.final_score)} / 100",
        f"  Regime   (30%): {_f(ai_score.regime_score)}",
        f"  Structure(25%): {_f(ai_score.structure_score)}",
        f"  Trend    (20%): {_f(ai_score.trend_score)}",
        f"  Momentum (15%): {_f(ai_score.momentum_score)}",
        f"  RR       (10%): {_f(ai_score.rr_score)}",
        f"Trade Allowed   : {ai_score.trade_allowed}",
        f"Entry Trigger   : {entry_result.reason}",
    ]


def _section_simulation(mc, port) -> list[str]:
    return [
        SEP,
        "🎲 RISK & SIMULATION DASHBOARD",
        SEP,
        f"Monte Carlo ({mc.simulations:,} paths, {mc.horizon}d)",
        f"  P(Profit)     : {_bar(mc.prob_profit)}  {_pct(mc.prob_profit)}",
        f"  P(Stop Hit)   : {_bar(mc.prob_stop_hit)}  {_pct(mc.prob_stop_hit)}",
        f"  P(Target Hit) : {_bar(mc.prob_target_hit)}  {_pct(mc.prob_target_hit)}",
        f"  Exp Return    : {_f(mc.expected_return_pct)}%",
        f"  Exp Drawdown  : {_f(mc.expected_drawdown_pct)}%",
        f"  95% CI        : [{_f(mc.ci_95_low)}%,  {_f(mc.ci_95_high)}%]",
        f"  VaR(95%)      : {_f(mc.var_95)}%",
        f"  CVaR(95%)     : {_f(mc.cvar_95)}%",
        f"  Sharpe(sim)   : {_f(mc.sharpe_simulated, 3)}",
        f"  Sortino(sim)  : {_f(mc.sortino_simulated, 3)}",
        "",
        "Portfolio Risk (Historical)",
        f"  VaR 95%       : {_f(port.var_95)}%",
        f"  VaR 99%       : {_f(port.var_99)}%",
        f"  CVaR 95%      : {_f(port.cvar_95)}%",
        f"  Max Drawdown  : {_f(port.max_drawdown)}%",
        f"  Vol (Ann.)    : {_f(port.volatility_annual)}%",
        f"  Vol (EWMA)    : {_f(port.vol_ewma_forecast)}%",
        f"  Sharpe        : {_f(port.sharpe, 3)}",
        f"  Sortino       : {_f(port.sortino, 3)}",
        f"  Calmar        : {_f(port.calmar, 3)}",
    ]


def _section_kelly_ev(position) -> list[str]:
    return [
        SEP,
        "💹 POSITION SIZING",
        SEP,
        f"Win Rate        : {_pct(position.win_rate * 100)}",
        f"Avg RR          : {_f(position.avg_rr, 2)}",
        f"Expected Value  : {_f(position.ev, 3)}R",
        f"Kelly Fraction  : {_f(position.kelly_fraction, 4)}",
        f"Half-Kelly      : {_f(position.half_kelly, 4)}",
        f"Regime Mult     : {position.regime_mult:.0%}",
        f"Final Risk %    : {_pct(position.risk_pct * 100)}",
        f"Kelly Valid     : {position.kelly_valid}",
    ]


def _section_final(symbol, price, final, ai_score, regime, mc, port, position, risk) -> list[str]:
    emoji = _DIR_EMOJI.get(final.decision, "❓")
    conf_bar = _bar(final.confidence_pct)
    return [
        SEP,
        f"🏛️  INSTITUTIONAL TRADE DASHBOARD — {symbol}",
        SEP,
        f"{'─'*26}",
        f"Current Price     : {_f(price)}",
        f"{'─'*26}",
        f"Regime            : {_REGIME_EMOJI.get(regime.current_regime,'❓')} {regime.current_regime}",
        f"Regime Prob       : {_pct(regime.regime_probability * 100)}",
        f"Regime Confidence : {_pct(regime.confidence)}",
        f"{'─'*26}",
        f"AI Score          : {_f(ai_score.final_score)} / 100",
        f"Expected Value    : {_f(position.ev, 3)}R",
        f"Kelly Fraction    : {_f(position.kelly_fraction, 4)}",
        f"Half-Kelly        : {_f(position.half_kelly, 4)}",
        f"{'─'*26}",
        f"MC P(Profit)      : {_pct(mc.prob_profit)}",
        f"MC P(Target)      : {_pct(mc.prob_target_hit)}",
        f"Exp Drawdown      : {_f(mc.expected_drawdown_pct)}%",
        f"VaR 95%           : {_f(port.var_95)}%",
        f"CVaR 95%          : {_f(port.cvar_95)}%",
        f"Sharpe            : {_f(port.sharpe, 3)}",
        f"Sortino           : {_f(port.sortino, 3)}",
        f"Calmar            : {_f(port.calmar, 3)}",
        f"{'─'*26}",
        f"Trade Direction   : {emoji} {risk.direction}",
        f"Entry             : {_f(risk.entry)}",
        f"Stop Loss         : {_f(risk.stop_loss)}  {_pct_diff(risk.entry, risk.stop_loss)}",
        f"Target 1          : {_f(risk.tp1)}  {_pct_diff(risk.entry, risk.tp1)}",
        f"Target 2          : {_f(risk.tp2)}  {_pct_diff(risk.entry, risk.tp2)}",
        f"Risk Reward       : {_f(max(risk.rr1, risk.rr2), 2)}",
        f"Position Size     : {_pct(position.risk_pct * 100)} of account",
        f"{'─'*26}",
        f"Gate Confidence   : {conf_bar}  {_f(final.confidence_pct)}%",
        f"Gates Passed      : {len(final.gates_passed)}/{len(final.gates_passed)+len(final.gates_failed)}",
        "",
    ]
    # decision block
    decision_block = [
        f"{'━'*28}",
        f"  FINAL DECISION: {emoji} {final.decision}",
        f"{'━'*28}",
        f"  {final.reason[:80]}",
    ]
    if final.gates_failed:
        decision_block.append(f"  Blocked by: {final.gates_failed[0]}")
    return lines + decision_block


# ──────────────────────────────────────────────────────────────────────────────
# MAIN: BUILD FULL REPORT
# ──────────────────────────────────────────────────────────────────────────────
def build_daily_report(
    symbol:       str,
    price:        float,
    regime,       # RegimeResult
    ema,          # EMAResult
    rsi,          # RSIResult
    structure,    # StructureResult
    divergence,   # DivergenceResult
    trend_filter, # TrendFilterResult
    sr:           dict,
    risk,         # RiskResult
    ai_score,     # AIScoreResult
    mc,           # MonteCarloResult
    port,         # PortfolioRiskResult
    position,     # PositionResult
    entry_result, # EntryResult
    final,        # FinalDecision
) -> str:
    """
    Assemble all sections into a single report string.

    Returns
    -------
    Full report as a multi-line string ready for LINE / console output.
    """

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    header = [
        SEP,
        f"🐱 TRADE ANALYZE  |  {symbol}  |  {now}",
        SEP,
    ]

    sections = (
        header
        + _section_regime(regime)
        + _section_structure(ema, rsi, structure, divergence, trend_filter)
        + _section_sr(sr)
        + _section_trade_plan(risk, ai_score, entry_result)
        + _section_kelly_ev(position)
        + _section_simulation(mc, port)
        + _section_final(symbol, price, final, ai_score, regime, mc, port, position, risk)
    )

    return "\n".join(sections)
