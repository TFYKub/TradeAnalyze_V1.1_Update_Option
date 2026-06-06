"""
Options Orchestrator
=====================
รับ FuturesResult จาก FuturesOrchestrator เป็น source of truth
แล้วต่อยอดด้วย Option Chain + Greeks + Option Strategy

ทำไม FuturesResult ถึงเป็น source of truth?
- FuturesOrchestrator ใช้ 7-gate decision + HMM regime + market structure
- Options pipeline เพิ่มข้อมูล: Greek conviction, IV environment, ตาราง option chain
- direction / entry / sl / tp มาจาก Futures เสมอ → ไม่มี conflict

Pipeline:
  1. รับ df + futures_result จากภายนอก (main.py โหลดแล้ว)
  2. Fetch option chain (yfinance / Deribit)
  3. Enrich with Greeks (Black-Scholes)
  4. Build option strategy จาก futures decision + IV environment
  5. ประกอบ unified result dict
"""

from __future__ import annotations

import logging
import time

from core.futures_orchestrator import FuturesResult
from data.option_chain import fetch_option_chain
from engines.greek_signal_engine import aggregate_greeks
from engines.greeks_pipeline import enrich_with_greeks
from engines.option_engine import generate_option_trade_v2
from engines.montecarlo_engine import monte_carlo

logger = logging.getLogger(__name__)


class OptionsOrchestrator:

    def run(
        self,
        futures: FuturesResult,
        asset_type: str = "stock",
    ) -> dict:
        """
        Build options data on top of an already-computed FuturesResult.

        Parameters
        ----------
        futures    : result from FuturesOrchestrator.run()
        asset_type : "stock" | "crypto"

        Returns
        -------
        dict with keys: signal, option, monte, option_chain
        """

        t0     = time.time()
        symbol = futures.symbol
        price  = futures.price

        # ── Option Chain + Greeks ──────────────────────────────────────────────
        raw_chain:      list[dict] = []
        enriched_chain: list[dict] = []

        try:
            logger.info(f"[{symbol}] Fetching option chain ({asset_type})...")
            raw_chain      = fetch_option_chain(symbol, price, asset_type=asset_type)
            enriched_chain = enrich_with_greeks(raw_chain, spot=price)
            logger.info(f"[{symbol}] Option chain: {len(enriched_chain)} rows enriched")
        except Exception as exc:
            logger.warning(f"[{symbol}] Option chain failed — {exc}")

        agg = aggregate_greeks(enriched_chain)

        # ── Signal: use Futures decision as source of truth ───────────────────
        # direction / entry / sl / tp1 / tp2 always come from FuturesResult
        signal = {
            "symbol":              symbol,
            "asset_type":          asset_type,
            "regime":              futures.regime,
            "price":               price,
            # ─ directional fields from Futures (single source of truth) ───────
            "position":            futures.final_decision,   # LONG | SHORT | NO_TRADE
            "entry":               futures.entry,
            "sl":                  futures.stop_loss,
            "tp1":                 futures.tp1,
            "tp2":                 futures.tp2,
            "target":              futures.tp2,
            "risk":                abs(futures.entry - futures.stop_loss),
            "holding_days":        _holding_days(agg.get("dominant_dte"), futures.final_decision),
            "active":              futures.approved,
            "ai_score":            futures.ai_score,
            "rr":                  futures.rr,
            # ─ Greek overlay ──────────────────────────────────────────────────
            "greek_conviction":    agg.get("iv_environment"),
            "conviction_reasons":  [],
            "greek_strategy_hint": _greek_strat_hint(futures.regime, agg),
            "iv_rank_proxy":       agg.get("iv_rank_proxy"),
            "iv_environment":      agg.get("iv_environment"),
            "put_call_delta_skew": agg.get("put_call_delta_skew"),
            "dominant_dte":        agg.get("dominant_dte"),
            "near_term_risk":      agg.get("near_term_risk", False),
            "avg_iv":              agg.get("avg_iv"),
            "pc_oi_ratio":         agg.get("pc_oi_ratio"),
            "avg_gamma":           agg.get("avg_gamma"),
            "fast_decay_pct":      agg.get("fast_decay_pct"),
        }

        # ── Option Strategy ────────────────────────────────────────────────────
        # ใช้ futures.final_decision (ผ่าน 7-gate แล้ว) + IV env จาก Greeks
        option = generate_option_trade_v2(
            price      = price,
            direction  = futures.final_decision,
            regime     = futures.regime,
            iv_env     = agg.get("iv_environment", "NORMAL_IV"),
            dominant_dte = agg.get("dominant_dte", 30),
            atr        = futures.entry - futures.stop_loss if futures.stop_loss < futures.entry else 0,
        )
        option["symbol"] = symbol

        # ── Monte Carlo (simple directional, reuse existing engine) ──────────
        from data.market_data import get_market_data
        df = get_market_data(symbol)
        mc_raw = monte_carlo(df["Close"]) if df is not None and not df.empty else {}

        monte = {
            "symbol":  symbol,
            "bull":    mc_raw.get("bull", 0),
            "bear":    mc_raw.get("bear", 0),
            "sideway": mc_raw.get("sideway", 0),
        }

        runtime = round(time.time() - t0, 2)
        logger.info(
            f"[{symbol}] Options done in {runtime}s  "
            f"decision={futures.final_decision}  "
            f"iv_env={agg.get('iv_environment')}  "
            f"strategy={option.get('strategy')}"
        )

        return {
            "symbol":       symbol,
            "price":        price,
            "signal":       signal,
            "option":       option,
            "monte":        monte,
            "option_chain": enriched_chain,
            "runtime":      runtime,
        }


def _holding_days(dominant_dte: int | None, direction: str) -> int:
    if direction in ("NO_TRADE", "WAIT"):
        return 0
    dte = dominant_dte or 30
    return max(5, round(dte * 0.60))


def _greek_strat_hint(regime: str, agg: dict) -> str:
    """เลือก option strategy hint จาก regime + IV env"""
    if not agg:
        return "WAIT"
    iv_env = agg.get("iv_environment", "NORMAL_IV")
    if regime in ("STRONG_BULL", "BULL"):
        return "BULL_CALL_SPREAD" if iv_env == "HIGH_IV" else "LONG_CALL"
    if regime in ("STRONG_BEAR", "BEAR"):
        return "BEAR_CALL_SPREAD" if iv_env == "HIGH_IV" else "PUT_DEBIT_SPREAD"
    if iv_env == "HIGH_IV":
        return "IRON_CONDOR"
    return "WAIT"
