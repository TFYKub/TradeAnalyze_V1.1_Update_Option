"""
LINE Message Formatter
=======================
สร้าง text report ที่ส่งเข้า LINE สำหรับแต่ละ Symbol

โครงสร้างข้อความ:
━━━━━━━━━━━━━━━━━━━━━━
🐱 TRADE ANALYZE | {SYMBOL}
━━━━━━━━━━━━━━━━━━━━━━
📊 REGIME: STRONG_BULL
💰 Price:  195.50

📈 SIGNAL ─────────────
Position  : LONG
Entry     : 195.50
Stop Loss : 192.30  (-1.6%)
TP1       : 198.70  (+1.6%)
TP2       : 201.90  (+3.3%)
Holding   : 30 days

🧠 OPTION SIGNAL ──────
Strategy  : BULL_CALL_SPREAD   [HIGH conviction]
IV Rank   : 38.2%  → Low IV (Long Vol cheap)
P/C Skew  : +0.08  → Bullish Bias
Avg IV    : 0.28
Dominant DTE : 30 days
P/C OI Ratio : 0.72

📐 GREEKS SNAPSHOT (ATM 30D) ──
Delta  :  0.52  (Moderate Directional)
Gamma  :  0.028
Theta  : -0.09  (Moderate Decay)
Vega   :  0.23  (Moderate Vega)

🎲 MONTE CARLO (20D) ───
🟢 Bull   : 52.3%
🔴 Bear   : 22.1%
⬜ Sideway: 25.6%

🧪 OPTIONS SETUP ───────
Strategy : BULL_CALL_SPREAD
Buy Call : 195  |  Sell Call: 205
DTE: 30  |  POP: 62%
━━━━━━━━━━━━━━━━━━━━━━
"""

from __future__ import annotations

import math
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _f(x, decimals: int = 2) -> str:
    """Format number → string, return 'N/A' for None/NaN."""
    if x is None:
        return "N/A"
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return "N/A"
        return f"{v:.{decimals}f}"
    except (TypeError, ValueError):
        return str(x)


def _pct(x) -> str:
    """Format as percentage string."""
    if x is None:
        return "N/A"
    try:
        return f"{float(x):.1f}%"
    except (TypeError, ValueError):
        return str(x)


def _s(x) -> str:
    return "N/A" if (x is None or x == "") else str(x)


def _pct_diff(entry, target) -> str:
    """Return sign + percent diff between two prices."""
    try:
        e, t = float(entry), float(target)
        if e == 0:
            return ""
        diff = (t - e) / e * 100
        sign = "+" if diff >= 0 else ""
        return f"({sign}{diff:.1f}%)"
    except Exception:
        return ""


def _regime_emoji(regime: str) -> str:
    return {
        "STRONG_BULL": "🚀",
        "BULL":        "📈",
        "BEAR":        "📉",
        "CORRECTION":  "⚠️",
        "RANGE":       "↔️",
    }.get(regime, "❓")


def _position_emoji(position: str) -> str:
    return {"LONG": "🟢", "SHORT": "🔴", "WAIT": "⏸️"}.get(position, "❓")


def _conviction_emoji(conviction: str) -> str:
    return {"HIGH": "🔥", "MEDIUM": "🟡", "LOW": "⬜"}.get(conviction, "")


def _mc_bar(pct: float, total_width: int = 10) -> str:
    """Simple ASCII progress bar."""
    filled = round(pct / 100 * total_width)
    return "█" * filled + "░" * (total_width - filled)


def _iv_context(iv_rank: float | None) -> str:
    if iv_rank is None:
        return ""
    if iv_rank < 30:
        return "→ Low IV (Long Vol cheap)"
    if iv_rank > 65:
        return "→ High IV (Short Vol lucrative)"
    return "→ Normal IV"


def _skew_context(skew: float | None) -> str:
    if skew is None:
        return ""
    if skew > 0.05:
        return "→ Bullish Bias"
    if skew < -0.05:
        return "→ Bearish Bias"
    return "→ Neutral"


def _atm_greeks(enriched_chain: list[dict], dte_bucket: int | None = 30) -> dict | None:
    """
    Pick the single closest-to-ATM call row for the dominant DTE bucket.
    Used for the Greeks Snapshot section.
    """
    if not enriched_chain:
        return None

    target_dte = dte_bucket or 30
    # Filter to the target DTE bucket, prefer calls
    candidates = [
        r for r in enriched_chain
        if r.get("dte_bucket") == target_dte
        and r.get("option_type") == "call"
        and r.get("delta") is not None
    ]

    if not candidates:
        # Fall back to any DTE
        candidates = [
            r for r in enriched_chain
            if r.get("option_type") == "call" and r.get("delta") is not None
        ]

    if not candidates:
        return None

    # ATM = delta closest to 0.50
    atm = min(candidates, key=lambda r: abs((r.get("delta") or 0) - 0.50))
    return atm


# ──────────────────────────────────────────────────────────────────────────────
# PER-SYMBOL BLOCK
# ──────────────────────────────────────────────────────────────────────────────
def _symbol_block(
    signal: dict,
    option: dict,
    monte: dict,
    enriched_chain: list[dict],
) -> str:
    symbol   = signal.get("symbol", "?")
    regime   = signal.get("regime", "?")
    position = signal.get("position", "WAIT")
    entry    = signal.get("entry")
    sl       = signal.get("sl")
    tp1      = signal.get("tp1")
    tp2      = signal.get("tp2")
    holding  = signal.get("holding_days", 0)

    greek_conviction   = signal.get("greek_conviction")
    greek_strat_hint   = signal.get("greek_strategy_hint")
    iv_rank            = signal.get("iv_rank_proxy")
    skew               = signal.get("put_call_delta_skew")
    avg_iv             = signal.get("avg_iv")
    dominant_dte       = signal.get("dominant_dte")
    pc_oi              = signal.get("pc_oi_ratio")

    bull_pct    = monte.get("bull", 0)
    bear_pct    = monte.get("bear", 0)
    sideway_pct = monte.get("sideway", 0)

    opt_strategy = option.get("strategy", "N/A")
    buy_call     = option.get("buy_call")
    sell_call    = option.get("sell_call")
    buy_put      = option.get("buy_put")
    sell_put     = option.get("sell_put")
    opt_dte      = option.get("dte")
    opt_pop      = option.get("pop")

    # ATM Greeks snapshot
    atm = _atm_greeks(enriched_chain, dominant_dte)

    SEP  = "━" * 24
    SEP2 = "─" * 22

    lines = [
        SEP,
        f"🐱 TRADE ANALYZE  |  {symbol}",
        SEP,
        f"📊 REGIME : {_regime_emoji(regime)} {regime}",
        f"💰 Price  : {_f(entry)}",
        "",
    ]

    # ── SIGNAL ────────────────────────────────────────────────────────────────
    if position != "WAIT":
        lines += [
            f"📈 SIGNAL {SEP2[:14]}",
            f"  {_position_emoji(position)} Position  : {position}",
            f"  Entry     : {_f(entry)}",
            f"  Stop Loss : {_f(sl)}  {_pct_diff(entry, sl)}",
            f"  TP1       : {_f(tp1)}  {_pct_diff(entry, tp1)}",
            f"  TP2       : {_f(tp2)}  {_pct_diff(entry, tp2)}",
            f"  Holding   : {holding} days",
            "",
        ]
    else:
        lines += [
            f"📈 SIGNAL {SEP2[:14]}",
            f"  ⏸️  WAIT — No directional signal",
            "",
        ]

    # ── OPTION SIGNAL (Greek-based) ───────────────────────────────────────────
    if greek_conviction and greek_conviction != "LOW":
        conv_flag = f"  [{_conviction_emoji(greek_conviction)} {greek_conviction} conviction]"
        lines += [
            f"🧠 OPTION SIGNAL {SEP2[:9]}",
            f"  Strategy  : {_s(greek_strat_hint)}{conv_flag}",
            f"  IV Rank   : {_pct(iv_rank)}  {_iv_context(iv_rank)}",
            f"  P/C Skew  : {_f(skew, 3)}  {_skew_context(skew)}",
            f"  Avg IV    : {_f(avg_iv, 3)}",
            f"  Dom DTE   : {_s(dominant_dte)} days",
            f"  P/C OI    : {_f(pc_oi, 3)}",
            "",
        ]
    elif greek_conviction == "LOW":
        lines += [
            f"🧠 OPTION SIGNAL {SEP2[:9]}",
            f"  ⬜ LOW conviction — Greeks inconclusive",
            f"  IV Rank  : {_pct(iv_rank)}  {_iv_context(iv_rank)}",
            "",
        ]

    # ── ATM GREEKS SNAPSHOT ───────────────────────────────────────────────────
    if atm:
        d = atm.get("delta")
        g = atm.get("gamma")
        t = atm.get("theta")
        v = atm.get("vega")
        moneyness   = atm.get("moneyness", "")
        dir_bias    = atm.get("direction_bias", "")
        theta_cat   = atm.get("theta_category", "")
        vega_cat    = atm.get("vega_category", "")
        atm_strike  = atm.get("strike")
        atm_dte_b   = atm.get("dte_bucket")

        lines += [
            f"📐 GREEKS SNAPSHOT {SEP2[:7]}",
            f"  ATM Call  : Strike {_f(atm_strike, 0)}  DTE {_s(atm_dte_b)}d",
            f"  Delta  : {_f(d, 4)}  ({_s(dir_bias)})",
            f"  Gamma  : {_f(g, 5)}",
            f"  Theta  : {_f(t, 4)}  ({_s(theta_cat)})",
            f"  Vega   : {_f(v, 4)}  ({_s(vega_cat)})",
            f"  Moneyness : {_s(moneyness)}",
            "",
        ]

    # ── MONTE CARLO ───────────────────────────────────────────────────────────
    lines += [
        f"🎲 MONTE CARLO (20D) {SEP2[:5]}",
        f"  🟢 Bull    : {_mc_bar(bull_pct)}  {_pct(bull_pct)}",
        f"  🔴 Bear    : {_mc_bar(bear_pct)}  {_pct(bear_pct)}",
        f"  ⬜ Sideway : {_mc_bar(sideway_pct)}  {_pct(sideway_pct)}",
        "",
    ]

    # ── OPTIONS SETUP ─────────────────────────────────────────────────────────
    opt_lines = [
        f"🧪 OPTIONS SETUP {SEP2[:10]}",
        f"  Strategy : {_s(opt_strategy)}",
    ]
    if buy_call is not None:
        opt_lines.append(f"  Buy Call : {_f(buy_call, 0)}")
    if sell_call is not None:
        opt_lines.append(f"  Sell Call: {_f(sell_call, 0)}")
    if buy_put is not None:
        opt_lines.append(f"  Buy Put  : {_f(buy_put, 0)}")
    if sell_put is not None:
        opt_lines.append(f"  Sell Put : {_f(sell_put, 0)}")
    opt_lines.append(f"  DTE: {_s(opt_dte)}d  |  POP: {_pct(opt_pop)}")

    lines += opt_lines
    lines.append(SEP)

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# SUMMARY HEADER (sent once at top)
# ──────────────────────────────────────────────────────────────────────────────
def _summary_header(signals: list, success: int, fail: int) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    regime_summary = ", ".join(
        f"{s.get('symbol')} {_regime_emoji(s.get('regime', ''))}"
        for s in signals
    )
    return (
        f"🐱 TRADE ANALYZE  {now}\n"
        f"Symbols: {len(signals)}  ✅{success}  ❌{fail}\n"
        f"{regime_summary}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
def format_report(
    signals: list[dict],
    option_results: list[dict],
    monte_results: list[dict],
    runtime: float,
    success_count: int,
    fail_count: int,
    enriched_chains: dict[str, list] | None = None,
) -> dict:
    """
    Build the full LINE message and return the data bundle.

    Parameters
    ----------
    signals         : list of signal dicts (one per symbol)
    option_results  : list of option strategy dicts
    monte_results   : list of Monte Carlo dicts
    runtime         : elapsed seconds
    success_count   : symbols processed OK
    fail_count      : symbols that errored
    enriched_chains : {symbol: [enriched_option_rows]}  for Greeks snapshot
    """

    enriched_chains = enriched_chains or {}

    # Build per-symbol blocks
    symbol_blocks: list[str] = []

    for signal in signals:
        sym = signal.get("symbol", "")

        # Match option + monte by symbol
        option = next(
            (o for o in option_results if o.get("symbol") == sym),
            option_results[0] if option_results else {},
        )
        monte = next(
            (m for m in monte_results if m.get("symbol") == sym),
            monte_results[0] if monte_results else {},
        )
        chain = enriched_chains.get(sym, [])

        symbol_blocks.append(_symbol_block(signal, option, monte, chain))

    full_text = "\n".join(symbol_blocks)

    # LINE has 4500-char limit per message — each block is sent individually
    return {
        "text":          full_text,          # full concatenated (for single-symbol)
        "blocks":        symbol_blocks,      # per-symbol blocks for multi-symbol send
        "signals":       signals,
        "options":       option_results,
        "monte":         monte_results,
        "runtime":       runtime,
        "success":       success_count,
        "fail":          fail_count,
    }


# ──────────────────────────────────────────────────────────────────────────────
# CONVENIENCE: format single symbol (called from orchestrator directly)
# ──────────────────────────────────────────────────────────────────────────────
def format_symbol_message(
    signal: dict,
    option: dict,
    monte: dict,
    enriched_chain: list[dict],
) -> str:
    """Return a ready-to-send LINE text block for one symbol."""
    return _symbol_block(signal, option, monte, enriched_chain)
