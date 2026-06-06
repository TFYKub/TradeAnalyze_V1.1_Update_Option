"""
Options LINE Message Formatter
================================
Formats OptionsRecommendation (using strategy_models.StrategySetup) → LINE text
"""
from __future__ import annotations
import math
from datetime import datetime

_RE = {"STRONG_BULL":"🚀","BULL":"📈","RANGE":"↔️","BEAR":"📉","STRONG_BEAR":"🔻","CORRECTION":"⚠️"}
SEP  = "━" * 28
SEP2 = "─" * 26

def _f(x, dec: int = 2) -> str:
    if x is None: return "N/A"
    try:
        v = float(x)
        return "N/A" if (math.isnan(v) or math.isinf(v)) else f"{v:.{dec}f}"
    except: return str(x)

def _pct(x) -> str:
    return "N/A" if x is None else f"{float(x):.1f}%"

def _s(x) -> str:
    return "N/A" if (x is None or x == "") else str(x)

def _diff(price, target) -> str:
    try:
        d = (float(target) - float(price)) / float(price) * 100
        return f"({'+' if d>=0 else ''}{d:.1f}%)"
    except: return ""

def _bar(pct: float, w: int = 10) -> str:
    n = max(0, min(w, round(pct / 100 * w)))
    return "█" * n + "░" * (w - n)

def _iv_label(r: float) -> str:
    return "High IV (sell vol)" if r >= 65 else "Low IV (buy vol)" if r <= 30 else "Normal IV"


def _strategy_block(s, rank: int, full: bool = True) -> list[str]:
    medals = ["🏆","🥈","🥉"]
    medal  = medals[rank] if rank < 3 else f"#{rank+1}"
    lines  = [f"  {medal}  {s.name}   [Score: {s.score:.0f}]"]
    if full:
        lines += [
            f"      POP    : {_bar(s.pop)}  {_pct(s.pop)}",
            f"      EV     : {'+' if s.ev >= 0 else ''}{_f(s.ev)} pts",
            f"      RR     : {_f(s.rr, 2)}",
            f"      Kelly  : {_f(s.kelly, 3)}  Half: {_f(s.half_kelly, 3)}",
            f"      Legs   : {s.strike_summary}",
            f"      MaxP   : {_f(s.max_profit) if not math.isinf(s.max_profit) else '∞'}  "
            f"MaxL: {_f(s.max_loss) if not math.isinf(s.max_loss) else '∞'}",
            f"      BE     : {_s(s.breakevens)}",
            f"      DTE    : {s.dte}d",
            f"      Rationale: {s.rationale[:65]}",
        ]
    return lines


def format_options_message(rec) -> str:
    from options.options_orchestrator import OptionsRecommendation
    now    = datetime.now().strftime("%Y-%m-%d %H:%M")
    vol    = rec.vol;  em = rec.em;  ranking = rec.ranking;  pri = rec.primary

    lines = [
        SEP, f"🐱 OPTIONS ANALYSIS  |  {rec.symbol}  |  {now}", SEP,
        f"📊 REGIME     : {_RE.get(rec.regime,'❓')} {rec.regime}  (conf {rec.regime_conf:.0f}%)",
        f"   Bull {_pct(rec.bull_prob*100)}  Bear {_pct(rec.bear_prob*100)}  Range {_pct(rec.range_prob*100)}",
        f"💰 Price      : {_f(rec.price)}",
        f"📐 IV Rank    : {_pct(vol.iv_rank)}  → {_iv_label(vol.iv_rank)}",
        f"📈 Exp Move   : ±{_f(em.expected_move)}  ({_f(em.expected_move_pct)}%)  [{em.dte}D]",
        "",
        f"🏆 TOP STRATEGY {SEP2[:11]}",
        f"     Rule: {ranking.rule_triggered}",
    ]
    lines += _strategy_block(pri, 0, full=True)
    lines.append("")

    # Alt strategies (compact)
    top3 = ranking.top_strategies
    if len(top3) > 1:
        for i, s in enumerate(top3[1:], 1):
            lines += _strategy_block(s, i, full=False)
        lines.append("")

    lines += [
        f"📊 VOLATILITY {SEP2[:13]}",
        f"  IV        : {_pct(vol.iv * 100)}  (source: {vol.source})",
        f"  HV20      : {_pct(vol.hv20 * 100)}",
        f"  IV/HV     : {_f(vol.iv_vs_hv, 2)}",
        f"  ATR14     : {_f(vol.atr14)}  ({_f(vol.atr_pct)}%)",
        f"  Vol Regime: {vol.vol_regime}", "",
        f"🎯 STRIKE BANDS ({em.dte}D) {SEP2[:6]}",
        f"  Price    : {_f(rec.price)}",
        f"  +1 SD    : {_f(em.upper_1sd)}  {_diff(rec.price, em.upper_1sd)}",
        f"  -1 SD    : {_f(em.lower_1sd)}  {_diff(rec.price, em.lower_1sd)}",
        f"  +1.5 SD  : {_f(em.upper_1_5sd)}  {_diff(rec.price, em.upper_1_5sd)}",
        f"  -1.5 SD  : {_f(em.lower_1_5sd)}  {_diff(rec.price, em.lower_1_5sd)}",
        "",
        rec.approval_reason,
        SEP,
    ]
    return "\n".join(lines)
