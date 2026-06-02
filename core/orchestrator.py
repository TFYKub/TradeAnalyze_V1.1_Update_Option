"""
Trade Orchestrator
==================
Coordinates the full analysis pipeline per symbol:

  1. Market data + indicators  (data/market_data.py)
  2. Option chain fetch         (data/option_chain.py)
  3. Greeks enrichment          (engines/greeks_pipeline.py)
  4. Greek-aware signal         (engines/greek_signal_engine.py)
  5. Option strategy suggestion (engines/option_engine.py)
  6. Monte Carlo simulation     (engines/montecarlo_engine.py)

Returns a unified result dict consumed by main.py.
"""

import logging
import time

from data.market_data import get_market_data
from data.option_chain import fetch_option_chain
from engines.greek_signal_engine import aggregate_greeks, generate_greek_signal
from engines.greeks_pipeline import enrich_with_greeks
from engines.markov_engine import classify_regime
from engines.montecarlo_engine import monte_carlo
from engines.option_engine import generate_option_trade

logger = logging.getLogger(__name__)


class TradeOrchestrator:

    def run(self, symbol: str, asset_type: str = "stock") -> dict | None:

        t0 = time.time()

        # ── 1. Market data ────────────────────────────────────────────────────
        logger.info(f"[{symbol}] Fetching market data...")
        df = get_market_data(symbol)
        if df is None or df.empty:
            logger.warning(f"[{symbol}] No market data — skipping")
            return None

        last   = df.iloc[-1]
        price  = float(last["Close"])
        atr    = float(last["ATR14"])
        hv20   = float(last.get("HV20", 0))
        regime = classify_regime(last)
        logger.info(f"[{symbol}] price={price:.4f}  atr={atr:.4f}  regime={regime}")

        # ── 2. Option chain + Greeks ──────────────────────────────────────────
        raw_chain:      list[dict] = []
        enriched_chain: list[dict] = []

        try:
            logger.info(f"[{symbol}] Fetching option chain ({asset_type})...")
            raw_chain      = fetch_option_chain(symbol, price, asset_type=asset_type)
            enriched_chain = enrich_with_greeks(raw_chain, spot=price)
            logger.info(f"[{symbol}] Option chain: {len(enriched_chain)} rows enriched")
        except Exception as exc:
            logger.warning(f"[{symbol}] Option chain failed — {exc}")

        # ── 3. Greek-aware signal ─────────────────────────────────────────────
        raw_signal = generate_greek_signal(price, atr, regime, enriched_chain)

        signal = {
            "symbol":              symbol,
            "asset_type":          asset_type,
            "regime":              regime,
            "price":               price,
            "atr":                 atr,
            "hv20":                hv20,
            "position":            raw_signal["position"],
            "entry":               raw_signal["entry"],
            "sl":                  raw_signal["sl"],
            "tp1":                 raw_signal["tp1"],
            "tp2":                 raw_signal["tp2"],
            "target":              raw_signal["target"],
            "risk":                raw_signal["risk"],
            "holding_days":        raw_signal["holding_days"],
            "active":              raw_signal["active"],
            # Greek overlay
            "greek_conviction":    raw_signal.get("greek_conviction"),
            "conviction_reasons":  raw_signal.get("conviction_reasons", []),
            "greek_strategy_hint": raw_signal.get("greek_strategy_hint"),
            "iv_rank_proxy":       raw_signal.get("iv_rank_proxy"),
            "iv_environment":      raw_signal.get("iv_environment"),
            "put_call_delta_skew": raw_signal.get("put_call_delta_skew"),
            "dominant_dte":        raw_signal.get("dominant_dte"),
            "near_term_risk":      raw_signal.get("near_term_risk", False),
            "avg_iv":              raw_signal.get("avg_iv"),
            "pc_oi_ratio":         raw_signal.get("pc_oi_ratio"),
            "avg_gamma":           raw_signal.get("avg_gamma"),
            "fast_decay_pct":      raw_signal.get("fast_decay_pct"),
        }

        # ── 4. Option strategy (regime-based suggestion) ──────────────────────
        raw_option = generate_option_trade(price, regime, atr)

        option = {
            "symbol":    symbol,
            "strategy":  raw_option.get("strategy", ""),
            "direction": raw_option.get("direction", ""),
            "entry":     raw_option.get("entry", 0),
            "target":    raw_option.get("target", 0),
            "buy_call":  raw_option.get("buy_call"),
            "sell_call": raw_option.get("sell_call"),
            "buy_put":   raw_option.get("buy_put"),
            "sell_put":  raw_option.get("sell_put"),
            "dte":       raw_option.get("dte", 0),
            "pop":       raw_option.get("pop", 0),
        }

        # ── 5. Monte Carlo ────────────────────────────────────────────────────
        mc = monte_carlo(df["Close"])

        monte = {
            "symbol":  symbol,
            "bull":    mc.get("bull", 0),
            "bear":    mc.get("bear", 0),
            "sideway": mc.get("sideway", 0),
        }

        runtime = round(time.time() - t0, 2)
        logger.info(f"[{symbol}] Done in {runtime}s  position={signal['position']}  conviction={signal['greek_conviction']}")

        return {
            "symbol":       symbol,
            "price":        price,
            "atr":          atr,
            "regime":       regime,
            "signals":      [signal],
            "options":      [option],
            "monte":        [monte],
            "option_chain": enriched_chain,
            "runtime":      runtime,
        }
