"""
LINE Message Formatter
=======================
Single source of truth สำหรับข้อความ LINE

โครงสร้างใหม่ (unified — ใช้ FuturesResult เป็นฐาน):

━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🐱 TRADE ANALYZE  |  AAPL  |  2026-06-03 07:00
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 REGIME : 📈 BULL  (conf 73%)
💰 Price  : 195.50

📈 FUTURES SIGNAL ──────────
  🟢 LONG   [AI: 82 | RR: 2.8]
  Entry    : 195.50
  Stop Loss: 192.30  (-1.6%)
  TP1      : 200.40  (+2.5%)
  TP2      : 207.80  (+6.3%)
  Holding  : 18 days
  Gates    : 7/7 ✅

🧠 OPTION SIGNAL ──────────
  IV Env   : NORMAL_IV
  Strategy : BULL_CALL_SPREAD
  Rationale: Direction=LONG + Normal IV → Bull Call Spread
  IV Rank  : 42.1%
  P/C Skew : +0.08  → Bullish Bias
  Dom DTE  : 30 days

📐 GREEKS (ATM 30D) ────────
  Strike   : 196
  Delta    : 0.5180  (Moderate Directional)
  Gamma    : 0.02800
  Theta    : -0.0900  (Moderate Decay)
  Vega     : 0.2300  (Moderate Vega)

🧪 OPTION SETUP ────────────
  Strategy : BULL_CALL_SPREAD
  Buy Call : 196  |  Sell Call: 206
  DTE      : 30 days  |  POP: 58%
  Max Profit: 10 pts
  Max Loss  : Net debit paid
  Breakeven : 196

🎲 MONTE CARLO (20D) ───────
  🟢 Bull   : ██████░░░░  56.2%
  🔴 Bear   : ███░░░░░░░  29.1%
  ⬜ Sideway: ██░░░░░░░░  14.7%
━━━━━━━━━━━━━━━━━━━━━━━━━━━━

RULE:
- Futures signal (direction/entry/sl/tp) มาจาก FuturesResult เสมอ
- Option strategy ขึ้นกับ direction + IV environment
- ถ้า NO_TRADE → แสดง IRON_CONDOR ถ้า IV สูง, NO_TRADE ถ้าไม่
"""

from __future__ import annotations

import math
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _f(x, dec: int = 2) -> str:
    if x is None: return "N/A"
    try:
        v = float(x)
        return "N/A" if (math.isnan(v) or math.isinf(v)) else f"{v:.{dec}f}"
    except (TypeError, ValueError):
        return str(x)

def _pct(x) -> str:
    if x is None: return "N/A"
    try: return f"{float(x):.1f}%"
    except: return str(x)

def _s(x) -> str:
    return "N/A" if (x is None or x == "") else str(x)

def _diff(entry, target) -> str:
    try:
        d = (float(target) - float(entry)) / float(entry) * 100
        return f"({'+' if d >= 0 else ''}{d:.1f}%)"
    except: return ""

def _bar(pct: float, w: int = 10) -> str:
    n = max(0, min(w, round(pct / 100 * w)))
    return "█" * n + "░" * (w - n)

_RE = {"STRONG_BULL":"🚀","BULL":"📈","RANGE":"↔️","BEAR":"📉",
       "STRONG_BEAR":"🔻","CORRECTION":"⚠️"}
_PE = {"LONG":"🟢","SHORT":"🔴","NO_TRADE":"⏸️","WAIT":"⏸️"}
_CE = {"HIGH":"🔥","MEDIUM":"🟡","LOW":"⬜"}

SEP  = "━" * 28
SEP2 = "─" * 26


# ──────────────────────────────────────────────────────────────────────────────
# ATM GREEKS  (pick ATM call nearest delta=0.50 in dominant DTE bucket)
# ──────────────────────────────────────────────────────────────────────────────
def _atm_greeks(chain: list[dict], dominant_dte: int | None) -> dict | None:
    if not chain: return None
    target = dominant_dte or 30
    cands = [r for r in chain
             if r.get("dte_bucket") == target
             and r.get("option_type") == "call"
             and r.get("delta") is not None]
    if not cands:
        cands = [r for r in chain if r.get("option_type") == "call" and r.get("delta") is not None]
    if not cands: return None
    return min(cands, key=lambda r: abs((r.get("delta") or 0) - 0.50))


# ──────────────────────────────────────────────────────────────────────────────
# BLOCK BUILDERS
# ──────────────────────────────────────────────────────────────────────────────
def _header(symbol: str, regime: str, regime_conf: float, price: float) -> list[str]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return [
        SEP,
        f"🐱 TRADE ANALYZE  |  {symbol}  |  {now}",
        SEP,
        f"📊 REGIME : {_RE.get(regime,'❓')} {regime}  (conf {regime_conf:.0f}%)",
        f"💰 Price  : {_f(price)}",
        "",
    ]


def _futures_block(signal: dict) -> list[str]:
    """
    FUTURES SIGNAL block — ข้อมูลมาจาก FuturesResult โดยตรง
    """
    pos    = signal.get("position", "NO_TRADE")
    entry  = signal.get("entry")
    sl     = signal.get("sl")
    tp1    = signal.get("tp1")
    tp2    = signal.get("tp2")
    hold   = signal.get("holding_days", 0)
    ai     = signal.get("ai_score", 0)
    rr     = signal.get("rr", 0)
    active = signal.get("active", False)

    gate_str = "7/7 ✅" if active else "❌ blocked"
    emoji    = _PE.get(pos, "❓")

    lines = [
        f"📈 FUTURES SIGNAL {SEP2[:9]}",
        f"  {emoji} {pos}   [AI: {_f(ai, 0)} | RR: {_f(rr, 2)}]",
    ]

    if pos in ("LONG", "SHORT"):
        lines += [
            f"  Entry    : {_f(entry)}",
            f"  Stop Loss: {_f(sl)}  {_diff(entry, sl)}",
            f"  TP1      : {_f(tp1)}  {_diff(entry, tp1)}",
            f"  TP2      : {_f(tp2)}  {_diff(entry, tp2)}",
            f"  Holding  : {hold} days",
            f"  Gates    : {gate_str}",
        ]
    else:
        lines.append(f"  ⏸️  No directional signal — gates not all passed")

    lines.append("")
    return lines


def _option_signal_block(signal: dict) -> list[str]:
    """
    OPTION SIGNAL block — Greek analysis
    แสดงว่า IV environment เป็นอย่างไรและ strategy hint คืออะไร
    """
    iv_env  = signal.get("iv_environment") or "N/A"
    strat   = signal.get("greek_strategy_hint") or "N/A"
    iv_rank = signal.get("iv_rank_proxy")
    skew    = signal.get("put_call_delta_skew")
    avg_iv  = signal.get("avg_iv")
    dom_dte = signal.get("dominant_dte")
    pc_oi   = signal.get("pc_oi_ratio")
    nt_risk = signal.get("near_term_risk", False)

    def _skew_ctx(s):
        if s is None: return ""
        return "→ Bullish Bias" if s > 0.05 else "→ Bearish Bias" if s < -0.05 else "→ Neutral"

    def _iv_ctx(r):
        if r is None: return ""
        return "→ Low IV (long vol cheap)" if r < 35 else \
               "→ High IV (short vol lucrative)" if r > 65 else "→ Normal"

    lines = [
        f"🧠 OPTION SIGNAL {SEP2[:10]}",
        f"  IV Env   : {_s(iv_env)}  {_iv_ctx(iv_rank)}",
        f"  Strategy : {_s(strat)}",
        f"  IV Rank  : {_pct(iv_rank)}",
        f"  P/C Skew : {_f(skew, 3)}  {_skew_ctx(skew)}",
        f"  Avg IV   : {_f(avg_iv, 3)}",
        f"  Dom DTE  : {_s(dom_dte)} days",
    ]
    if pc_oi is not None:
        lines.append(f"  P/C OI   : {_f(pc_oi, 3)}")
    if nt_risk:
        lines.append(f"  ⚠️  Near-term event risk (short DTE dominant)")
    lines.append("")
    return lines


def _greeks_block(chain: list[dict], dominant_dte: int | None) -> list[str]:
    """ATM Greeks Snapshot"""
    atm = _atm_greeks(chain, dominant_dte)
    if not atm:
        return []
    return [
        f"📐 GREEKS (ATM {dominant_dte or 30}D) {SEP2[:6]}",
        f"  Strike : {_f(atm.get('strike'), 0)}",
        f"  Delta  : {_f(atm.get('delta'), 4)}  ({_s(atm.get('direction_bias'))})",
        f"  Gamma  : {_f(atm.get('gamma'), 5)}",
        f"  Theta  : {_f(atm.get('theta'), 4)}  ({_s(atm.get('theta_category'))})",
        f"  Vega   : {_f(atm.get('vega'), 4)}  ({_s(atm.get('vega_category'))})",
        f"  ITM    : {_s(atm.get('in_the_money'))}  Moneyness: {_s(atm.get('moneyness'))}",
        "",
    ]


def _option_setup_block(option: dict) -> list[str]:
    """
    OPTIONS SETUP block — concrete trade parameters
    อธิบาย: นี่คือ option trade ที่ recommend ให้ทำ ไม่ใช่ futures trade
    """
    strat   = option.get("strategy", "N/A")
    rat     = option.get("rationale", "")
    bc      = option.get("buy_call")
    sc      = option.get("sell_call")
    bp      = option.get("buy_put")
    sp      = option.get("sell_put")
    dte     = option.get("dte", 0)
    pop     = option.get("pop", 0)
    mp      = option.get("max_profit", "N/A")
    ml      = option.get("max_loss", "N/A")
    be      = option.get("breakeven", "N/A")

    if strat == "NO_TRADE":
        return [
            f"🧪 OPTION SETUP {SEP2[:11]}",
            f"  ⏸️  NO_TRADE — {rat}",
            "",
        ]

    lines = [
        f"🧪 OPTION SETUP {SEP2[:11]}",
        f"  Strategy  : {strat}",
        f"  Rationale : {rat[:60]}",
    ]

    # Legs
    if bc is not None:
        lines.append(f"  Buy Call  : {_f(bc, 0)}")
    if sc is not None:
        lines.append(f"  Sell Call : {_f(sc, 0)}")
    if bp is not None:
        lines.append(f"  Buy Put   : {_f(bp, 0)}")
    if sp is not None:
        lines.append(f"  Sell Put  : {_f(sp, 0)}")

    lines += [
        f"  DTE       : {dte} days   POP: {pop}%",
        f"  Max Profit: {_s(mp)}",
        f"  Max Loss  : {_s(ml)}",
        f"  Breakeven : {_s(be)}",
        "",
    ]
    return lines


def _monte_block(monte: dict) -> list[str]:
    bull    = float(monte.get("bull", 0))
    bear    = float(monte.get("bear", 0))
    sideway = float(monte.get("sideway", 0))
    return [
        f"🎲 MONTE CARLO (20D) {SEP2[:6]}",
        f"  🟢 Bull   : {_bar(bull)}  {_pct(bull)}",
        f"  🔴 Bear   : {_bar(bear)}  {_pct(bear)}",
        f"  ⬜ Sideway: {_bar(sideway)}  {_pct(sideway)}",
        SEP,
    ]


# ──────────────────────────────────────────────────────────────────────────────
# MAIN: BUILD PER-SYMBOL MESSAGE
# ──────────────────────────────────────────────────────────────────────────────
def format_symbol_message(
    signal:         dict,
    option:         dict,
    monte:          dict,
    enriched_chain: list[dict],
) -> str:
    """
    Build the complete LINE message for one symbol.

    signal  : unified signal dict from OptionsOrchestrator
              (direction/entry/sl/tp from FuturesResult)
    option  : option trade setup dict from generate_option_trade_v2
    monte   : Monte Carlo dict
    enriched_chain: enriched option rows for Greeks snapshot
    """

    symbol      = signal.get("symbol", "?")
    regime      = signal.get("regime", "?")
    regime_conf = signal.get("regime_conf", 0)
    price       = signal.get("price", signal.get("entry", 0))
    dominant_dte = signal.get("dominant_dte")

    # regime_conf might not be in signal if called from legacy path
    if regime_conf == 0 and signal.get("ai_score"):
        regime_conf = float(signal.get("ai_score", 0))   # fallback

    lines = (
        _header(symbol, regime, regime_conf, price)
        + _futures_block(signal)
        + _option_signal_block(signal)
        + _greeks_block(enriched_chain, dominant_dte)
        + _option_setup_block(option)
        + _monte_block(monte)
    )

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# LEGACY: format_report (used by sheet_writer path, kept for compat)
# ──────────────────────────────────────────────────────────────────────────────
def format_report(
    signals:        list[dict],
    option_results: list[dict],
    monte_results:  list[dict],
    runtime:        float,
    success_count:  int,
    fail_count:     int,
    enriched_chains: dict | None = None,
) -> dict:
    enriched_chains = enriched_chains or {}
    blocks = []
    for sig in signals:
        sym    = sig.get("symbol", "")
        opt    = next((o for o in option_results if o.get("symbol") == sym), option_results[0] if option_results else {})
        mc     = next((m for m in monte_results if m.get("symbol") == sym), monte_results[0] if monte_results else {})
        chain  = enriched_chains.get(sym, [])
        blocks.append(format_symbol_message(sig, opt, mc, chain))

    return {
        "text":    "\n".join(blocks),
        "blocks":  blocks,
        "signals": signals,
        "options": option_results,
        "monte":   monte_results,
        "runtime": runtime,
        "success": success_count,
        "fail":    fail_count,
    }
