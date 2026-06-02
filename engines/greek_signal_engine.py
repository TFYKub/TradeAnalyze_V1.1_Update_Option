"""
Greek-Aware Signal Generator
==============================
ผสาน market regime (markov_engine) + Option Chain Greeks
เพื่อสร้าง trade signal ที่มีความแม่นยำสูงขึ้น

เกณฑ์การให้ Signal
-------------------
STRONG_BULL + HIGH conviction  → LONG  (SL แคบ 0.8x ATR, TP 2.5x ATR)
STRONG_BULL + MEDIUM conviction → LONG  (SL 1.0x ATR, TP 2.0x ATR)
BULL        + HIGH conviction  → LONG
BULL        + LOW conviction   → WAIT  (regime ไม่ confirm จาก chain)
BEAR        + any              → SHORT (mirror ของ BULL)
CORRECTION + HIGH IV rank      → WAIT + hint IRON_CONDOR
RANGE       + HIGH IV rank     → WAIT + hint IRON_CONDOR / STRADDLE

Greek เกณฑ์แต่ละข้อ
--------------------
Delta skew   > +0.05  → call-side heavier → bullish confirmation
P/C OI ratio < 0.80   → more call OI than put → bullish
IV Rank      < 35     → low IV → long vol ถูก → favour debit spreads
IV Rank      > 65     → high IV → short vol ดี → favour credit spreads
Avg Gamma    > 0.04   → high gamma environment → pin risk, careful near expiry
Fast Decay % > 40%   → theta-rich environment → favour short vol

DTE Analysis
------------
ดู OI ที่กระจุกตัวใน DTE bucket ไหนมากที่สุด → dominant_dte
ถ้า dominant_dte = 7 หรือ 14 → market expects near-term move (event risk)
ถ้า dominant_dte = 60 หรือ 90 → market hedging longer term
"""

import logging
import statistics

logger = logging.getLogger(__name__)

# ── Thresholds (ปรับได้) ──────────────────────────────────────────────────────
DELTA_SKEW_BULL   =  0.05   # skew > +0.05 → bullish
DELTA_SKEW_BEAR   = -0.05   # skew < -0.05 → bearish
PC_OI_BULL        =  0.80   # P/C OI < 0.80 → more calls → bullish
PC_OI_BEAR        =  1.25   # P/C OI > 1.25 → more puts  → bearish
IV_RANK_LOW       =  35.0   # < 35 → low IV → long vol cheap
IV_RANK_HIGH      =  65.0   # > 65 → high IV → short vol lucrative
GAMMA_HIGH        =  0.04   # gamma > 0.04 → accelerating environment
FAST_DECAY_RATIO  =  0.40   # >40% of chain rows are FAST_DECAY theta
NEAR_TERM_DTE     = (7, 14) # dominant DTE → near-term event risk


# ──────────────────────────────────────────────────────────────────────────────
# AGGREGATION
# ──────────────────────────────────────────────────────────────────────────────
def _safe_mean(values: list) -> float:
    clean = [float(v) for v in values if v is not None]
    return statistics.mean(clean) if clean else 0.0


def aggregate_greeks(rows: list[dict]) -> dict:
    """
    สรุป Greek ทั้ง chain ให้เป็น dict เดียว สำหรับใช้เป็นเกณฑ์ signal

    Returns empty dict ถ้าไม่มีข้อมูล
    """

    if not rows:
        return {}

    calls = [r for r in rows if r.get("option_type") == "call"]
    puts  = [r for r in rows if r.get("option_type") == "put"]
    total = len(rows)

    # ── IV ────────────────────────────────────────────────────────────────────
    all_iv  = [r["iv"] for r in rows if r.get("iv", 0) > 0]
    avg_iv  = _safe_mean(all_iv)
    max_iv  = max(all_iv, default=0)
    min_iv  = min(all_iv, default=0)

    # IV Rank proxy = position ของ avg_iv ในช่วง [min_iv, max_iv]
    iv_rank = (
        round((avg_iv - min_iv) / (max_iv - min_iv) * 100, 1)
        if max_iv > min_iv else 50.0
    )

    # ── Delta skew ────────────────────────────────────────────────────────────
    avg_call_delta = _safe_mean([r.get("delta") for r in calls])
    avg_put_delta  = _safe_mean([abs(r.get("delta") or 0) for r in puts])
    delta_skew     = round(avg_call_delta - avg_put_delta, 4)

    # ── Gamma ─────────────────────────────────────────────────────────────────
    avg_gamma       = _safe_mean([r.get("gamma") for r in rows])
    high_gamma_n    = sum(1 for r in rows if r.get("high_gamma"))
    high_gamma_pct  = round(high_gamma_n / total * 100, 1) if total else 0

    # ── Theta ─────────────────────────────────────────────────────────────────
    avg_theta        = _safe_mean([r.get("theta") for r in rows])
    fast_decay_n     = sum(1 for r in rows if r.get("theta_category") == "FAST_DECAY")
    fast_decay_pct   = round(fast_decay_n / total * 100, 1) if total else 0

    # ── Vega ──────────────────────────────────────────────────────────────────
    avg_vega        = _safe_mean([r.get("vega") for r in rows])
    high_vega_n     = sum(1 for r in rows if r.get("vega_category") == "HIGH_VEGA")

    # ── OI analysis ───────────────────────────────────────────────────────────
    total_call_oi = sum(r.get("open_interest", 0) or 0 for r in calls)
    total_put_oi  = sum(r.get("open_interest", 0) or 0 for r in puts)
    pc_oi_ratio   = round(
        total_put_oi / total_call_oi if total_call_oi > 0 else 1.0, 3
    )

    # DTE bucket ที่มี OI รวมสูงสุด
    oi_by_bucket: dict[int, int] = {}
    for r in rows:
        b  = r.get("dte_bucket", 30)
        oi = r.get("open_interest", 0) or 0
        oi_by_bucket[b] = oi_by_bucket.get(b, 0) + oi

    dominant_dte = max(oi_by_bucket, key=oi_by_bucket.get) if oi_by_bucket else 30

    # Near-term event risk flag
    near_term_risk = dominant_dte in NEAR_TERM_DTE

    return {
        # IV
        "avg_iv":          round(avg_iv, 4),
        "iv_rank_proxy":   iv_rank,
        "iv_environment":  (
            "LOW_IV"  if iv_rank < IV_RANK_LOW else
            "HIGH_IV" if iv_rank > IV_RANK_HIGH else
            "NORMAL_IV"
        ),
        # Delta
        "put_call_delta_skew": delta_skew,
        "avg_call_delta":      round(avg_call_delta, 4),
        "avg_put_delta":       round(avg_put_delta, 4),
        # Gamma
        "avg_gamma":        round(avg_gamma, 6),
        "high_gamma_count": high_gamma_n,
        "high_gamma_pct":   high_gamma_pct,
        # Theta
        "avg_theta":        round(avg_theta, 5),
        "fast_decay_pct":   fast_decay_pct,
        # Vega
        "avg_vega":         round(avg_vega, 5),
        "high_vega_count":  high_vega_n,
        # OI
        "pc_oi_ratio":      pc_oi_ratio,
        "total_call_oi":    total_call_oi,
        "total_put_oi":     total_put_oi,
        "dominant_dte":     dominant_dte,
        "near_term_risk":   near_term_risk,
    }


# ──────────────────────────────────────────────────────────────────────────────
# CONVICTION SCORING
# ──────────────────────────────────────────────────────────────────────────────
def _score_conviction(agg: dict, regime: str) -> tuple[str, list[str]]:
    """
    คำนวณ conviction score จากหลายเกณฑ์พร้อมกัน

    Returns (conviction_level, reasons_list)
    conviction: HIGH (≥3 pts) | MEDIUM (1-2 pts) | LOW (0 pts)
    """

    if not agg:
        return "LOW", ["No option chain data"]

    score   = 0
    reasons = []

    skew    = agg.get("put_call_delta_skew", 0)
    pc      = agg.get("pc_oi_ratio", 1.0)
    iv_r    = agg.get("iv_rank_proxy", 50)
    gamma   = agg.get("avg_gamma", 0)
    fd_pct  = agg.get("fast_decay_pct", 0)
    nt_risk = agg.get("near_term_risk", False)

    if regime in ("STRONG_BULL", "BULL"):
        if skew > DELTA_SKEW_BULL:
            score += 1
            reasons.append(f"Delta skew bullish ({skew:+.3f})")
        if pc < PC_OI_BULL:
            score += 1
            reasons.append(f"Call OI dominant (P/C={pc:.2f})")
        if iv_r < IV_RANK_LOW:
            score += 1
            reasons.append(f"Low IV rank ({iv_r:.0f}) → long vol cheap")
        if gamma < GAMMA_HIGH:
            score += 1
            reasons.append("Stable gamma → low pin risk")
        if nt_risk:
            score -= 1   # near-term event → risky to go directional
            reasons.append("⚠️ Near-term event risk (short DTE dominant)")

    elif regime == "BEAR":
        if skew < DELTA_SKEW_BEAR:
            score += 1
            reasons.append(f"Delta skew bearish ({skew:+.3f})")
        if pc > PC_OI_BEAR:
            score += 1
            reasons.append(f"Put OI dominant (P/C={pc:.2f})")
        if iv_r < IV_RANK_LOW:
            score += 1
            reasons.append(f"Low IV rank ({iv_r:.0f}) → long vol cheap")
        if gamma < GAMMA_HIGH:
            score += 1
            reasons.append("Stable gamma → low pin risk")
        if nt_risk:
            score -= 1
            reasons.append("⚠️ Near-term event risk")

    elif regime in ("CORRECTION", "RANGE", "SIDEWAY"):
        if PC_OI_BULL <= pc <= PC_OI_BEAR:
            score += 1
            reasons.append(f"Balanced P/C OI ({pc:.2f})")
        if iv_r > IV_RANK_HIGH:
            score += 1
            reasons.append(f"High IV rank ({iv_r:.0f}) → short vol lucrative")
        if fd_pct > FAST_DECAY_RATIO * 100:
            score += 1
            reasons.append(f"Theta-rich ({fd_pct:.0f}% fast decay)")
        if gamma < GAMMA_HIGH:
            score += 1
            reasons.append("Low gamma → stable range")

    score = max(0, score)  # prevent negative
    level = "HIGH" if score >= 3 else "MEDIUM" if score >= 1 else "LOW"
    return level, reasons


# ──────────────────────────────────────────────────────────────────────────────
# STRATEGY HINT
# ──────────────────────────────────────────────────────────────────────────────
def _pick_strategy(regime: str, agg: dict, conviction: str) -> str:
    """
    เลือก option strategy ที่เหมาะสมที่สุด จาก regime + Greek environment
    """

    if not agg:
        return "WAIT"

    iv_r   = agg.get("iv_rank_proxy", 50)
    skew   = agg.get("put_call_delta_skew", 0)
    iv_env = agg.get("iv_environment", "NORMAL_IV")

    if regime == "STRONG_BULL":
        if iv_env == "HIGH_IV":
            return "BULL_CALL_SPREAD"   # high IV → use spread to reduce debit
        if iv_env == "LOW_IV":
            return "LONG_CALL"          # low IV → buy outright call cheaper
        return "BULL_CALL_SPREAD"

    if regime == "BULL":
        if iv_env == "HIGH_IV":
            return "BULL_PUT_SPREAD"    # sell put spread → collect premium
        return "BULL_CALL_SPREAD"

    if regime == "BEAR":
        if iv_env == "HIGH_IV":
            return "BEAR_CALL_SPREAD"
        return "PUT_DEBIT_SPREAD"

    if regime in ("CORRECTION", "RANGE", "SIDEWAY"):
        if iv_r > IV_RANK_HIGH:
            return "IRON_CONDOR"        # premium selling in high IV
        if iv_r > 50 and abs(skew) < 0.03:
            return "SHORT_STRADDLE"     # neutral + decent IV
        if iv_r < IV_RANK_LOW:
            return "LONG_STRADDLE"      # low IV → buy vol before move
        return "IRON_CONDOR"

    return "WAIT"


# ──────────────────────────────────────────────────────────────────────────────
# HOLDING DAYS จาก DTE
# ──────────────────────────────────────────────────────────────────────────────
def _holding_days(dominant_dte: int | None, position: str) -> int:
    """กำหนด holding period ตาม dominant DTE bucket"""
    if position == "WAIT":
        return 0
    dte = dominant_dte or 30
    # Hold ประมาณ 50-70% ของ DTE เพื่อหลีกเลี่ยง theta decay ท้าย
    return max(5, round(dte * 0.60))


# ──────────────────────────────────────────────────────────────────────────────
# SL/TP MULTIPLIER จาก IV
# ──────────────────────────────────────────────────────────────────────────────
def _sl_tp_mults(conviction: str, iv_rank: float) -> tuple[float, float]:
    """
    ปรับ SL/TP multiplier ตาม conviction + IV environment

    HIGH conviction + LOW IV  → tight SL (0.8x), wide TP (2.5x)
    HIGH conviction + HIGH IV → normal SL (1.0x), TP (2.0x)
    MEDIUM                    → SL 1.0x, TP 2.0x
    LOW                       → SL 1.2x (wider), TP 1.5x (conservative)
    """
    if conviction == "HIGH":
        if iv_rank < IV_RANK_LOW:
            return 0.8, 2.5
        return 1.0, 2.0
    if conviction == "MEDIUM":
        return 1.0, 2.0
    # LOW conviction
    return 1.2, 1.5


# ──────────────────────────────────────────────────────────────────────────────
# MAIN: GENERATE SIGNAL
# ──────────────────────────────────────────────────────────────────────────────
def generate_greek_signal(
    price: float,
    atr: float,
    regime: str,
    enriched_rows: list[dict],
) -> dict:
    """
    สร้าง trade signal โดยใช้ Greek เป็นเกณฑ์กรองและปรับ SL/TP

    Falls back gracefully ถ้าไม่มี option chain data
    """

    agg         = aggregate_greeks(enriched_rows)
    conviction, reasons = _score_conviction(agg, regime)
    strat_hint  = _pick_strategy(regime, agg, conviction)
    iv_rank     = agg.get("iv_rank_proxy", 50)
    dominant_dte = agg.get("dominant_dte")
    sl_mult, tp_mult = _sl_tp_mults(conviction, iv_rank)

    # ── Directional: LONG ─────────────────────────────────────────────────────
    if regime in ("STRONG_BULL", "BULL"):
        # LOW conviction + ไม่ใช่ STRONG_BULL → ไม่ส่ง signal
        if conviction == "LOW" and regime != "STRONG_BULL":
            position = "WAIT"
        else:
            position = "LONG"

    # ── Directional: SHORT ────────────────────────────────────────────────────
    elif regime == "BEAR":
        if conviction == "LOW":
            position = "WAIT"
        else:
            position = "SHORT"

    # ── Neutral / No trade ────────────────────────────────────────────────────
    else:
        position = "WAIT"

    # ── Build signal dict ─────────────────────────────────────────────────────
    holding = _holding_days(dominant_dte, position)

    if position == "LONG":
        signal = dict(
            position   = "LONG",
            entry      = price,
            sl         = round(price - atr * sl_mult, 4),
            tp1        = round(price + atr, 4),
            tp2        = round(price + atr * tp_mult, 4),
            target     = round(price + atr * tp_mult, 4),
            risk       = round(atr * sl_mult, 4),
            holding_days = holding,
            active     = True,
        )

    elif position == "SHORT":
        signal = dict(
            position   = "SHORT",
            entry      = price,
            sl         = round(price + atr * sl_mult, 4),
            tp1        = round(price - atr, 4),
            tp2        = round(price - atr * tp_mult, 4),
            target     = round(price - atr * tp_mult, 4),
            risk       = round(atr * sl_mult, 4),
            holding_days = holding,
            active     = True,
        )

    else:
        signal = dict(
            position   = "WAIT",
            entry      = price,
            sl         = price,
            tp1        = price,
            tp2        = price,
            target     = price,
            risk       = 0,
            holding_days = 0,
            active     = False,
        )

    # ── Greek overlay fields ──────────────────────────────────────────────────
    signal.update({
        "greek_conviction":    conviction,
        "conviction_reasons":  reasons,
        "greek_strategy_hint": strat_hint,
        "iv_rank_proxy":       agg.get("iv_rank_proxy"),
        "iv_environment":      agg.get("iv_environment"),
        "put_call_delta_skew": agg.get("put_call_delta_skew"),
        "dominant_dte":        agg.get("dominant_dte"),
        "near_term_risk":      agg.get("near_term_risk", False),
        "avg_iv":              agg.get("avg_iv"),
        "pc_oi_ratio":         agg.get("pc_oi_ratio"),
        "avg_gamma":           agg.get("avg_gamma"),
        "fast_decay_pct":      agg.get("fast_decay_pct"),
    })

    return signal
