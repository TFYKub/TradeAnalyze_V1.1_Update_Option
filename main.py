"""
TradeAnalyze — Main Entry Point
================================
Per symbol pipeline:

  A) FUTURES  — FuturesOrchestrator (14-step: HMM + structure + 7-gate)
     → Full institutional report → LINE

  B) OPTIONS  — options/options_orchestrator.py (new institutional engine)
     → Volatility Engine → Expected Move → Strategy Selector (7 rules)
     → POP Monte Carlo → EV/Kelly → Top 3 strategies
     → format_options_message → LINE
     → Options_Analysis sheet

  C) OPTION CHAIN — fetch + Greeks → Option_Chain sheet
"""

import time
import traceback

from config.config_validator import validate
from config.logging_config import logger
from alerts.line_alert import send_line_message
from core.futures_orchestrator import FuturesOrchestrator
from data.market_data import get_market_data
from data.option_chain import fetch_option_chain
from engines.greeks_pipeline import enrich_with_greeks
from options.options_orchestrator import run_options_analysis
from reports.options_formatter import format_options_message
from reports.options_sheet_writer import write_options_analysis
from reports.option_chain_writer import clear_symbol_rows, write_option_chain
from reports.sheet_writer import log_trade_signals
from utils.symbol_loader import load_symbols_with_type


def run_trading_engine() -> None:

    validate()

    futures_orch = FuturesOrchestrator(win_rate=0.52, avg_rr=2.5)
    success = fail = 0

    symbol_list = load_symbols_with_type("LINE")
    if not symbol_list:
        print("❌ No symbols found in SYMBOL_CONFIG (group=LINE)")
        return

    print(f"\n🚀 ===== TRADING ENGINE START =====")
    print(f"📊 Symbols: {len(symbol_list)}")

    for item in symbol_list:
        symbol     = item["symbol"]
        asset_type = item["asset_type"]

        print(f"\n{'━'*44}")
        print(f"📊 {symbol}  ({asset_type})")

        try:
            # ── 1. Market data (shared) ───────────────────────────────────────
            df = get_market_data(symbol)
            if df is None or df.empty:
                print(f"  ❌ No market data"); fail += 1; continue

            # ── 2. FUTURES PIPELINE ───────────────────────────────────────────
            print(f"  ⚙️  Futures analysis...")
            futures = futures_orch.run(symbol, df)

            dec_e = {"LONG":"🟢","SHORT":"🔴","NO_TRADE":"⏸️"}.get(futures.final_decision,"❓")
            print(f"  {dec_e} Futures: {futures.final_decision} | "
                  f"Regime={futures.regime}({futures.regime_conf:.0f}%) | "
                  f"AI={futures.ai_score:.0f} | RR={futures.rr:.2f}")

            # Send futures institutional report → LINE
            msg = futures.report_text
            if len(msg) > 4500: msg = msg[:4480] + "\n…"
            send_line_message(msg)
            print(f"  📱 Futures report → LINE ✅")

            # Write TradeSignals sheet
            signal_dict = {
                "symbol": symbol, "regime": futures.regime, "price": futures.price,
                "position": futures.final_decision, "entry": futures.entry,
                "sl": futures.stop_loss, "tp1": futures.tp1, "tp2": futures.tp2,
                "risk": abs(futures.entry - futures.stop_loss),
                "holding_days": 0, "active": futures.approved,
                "ai_score": futures.ai_score, "rr": futures.rr,
                "greek_conviction": "", "conviction_reasons": [],
                "greek_strategy_hint": "", "iv_rank_proxy": None,
                "iv_environment": None, "put_call_delta_skew": None,
                "dominant_dte": None, "near_term_risk": False,
                "avg_iv": None, "pc_oi_ratio": None, "avg_gamma": None,
                "fast_decay_pct": None, "asset_type": asset_type,
            }
            log_trade_signals(symbol, [signal_dict], [{"bull":0,"bear":0,"sideway":0}])

            # ── 3. OPTION CHAIN + GREEKS ──────────────────────────────────────
            print(f"  ⚙️  Fetching option chain...")
            enriched_chain: list[dict] = []
            try:
                raw_chain      = fetch_option_chain(symbol, futures.price, asset_type=asset_type)
                enriched_chain = enrich_with_greeks(raw_chain, spot=futures.price)
                if enriched_chain:
                    clear_symbol_rows(symbol)
                    n = write_option_chain(symbol, enriched_chain)
                    print(f"  📋 Option_Chain: {n} rows ✅")
                else:
                    print(f"  ⚠️  Option chain: no data")
            except Exception as exc:
                logger.warning("[%s] Option chain failed: %s", symbol, exc)
                print(f"  ⚠️  Option chain: {exc}")

            # ── 4. OPTIONS ANALYSIS (new engine) ─────────────────────────────
            print(f"  ⚙️  Options analysis (institutional)...")

            # Get regime probabilities from futures orchestrator
            # Re-run regime engine for probs (already computed inside futures, expose here)
            from regime.markov import MarkovRegimeEngine
            from indicators.ema import compute_ema
            from indicators.rsi import compute_rsi
            from indicators.atr import compute_atr
            import warnings
            warnings.filterwarnings("ignore")

            df_ind = compute_ema(compute_rsi(compute_atr(df.copy())))
            try:
                re = MarkovRegimeEngine()
                reg_result = re.detect(df_ind)
                regime_probs = reg_result.regime_probs_all
            except Exception:
                regime_probs = {futures.regime: 0.65}

            opts_rec = run_options_analysis(
                symbol         = symbol,
                price          = futures.price,
                df             = df_ind,
                regime         = futures.regime,
                regime_conf    = futures.regime_conf,
                regime_probs   = regime_probs,
                ai_score       = futures.ai_score,
                enriched_chain = enriched_chain,
            )

            # Write Options_Analysis sheet
            write_options_analysis(opts_rec)
            print(f"  ✅ Options_Analysis sheet: {opts_rec.primary.display} "
                  f"(score={opts_rec.primary.composite_score:.0f})")

            # Send options LINE message
            opts_msg = format_options_message(opts_rec)
            if len(opts_msg) > 4500: opts_msg = opts_msg[:4480] + "\n…"
            send_line_message(opts_msg)
            print(f"  📱 Options analysis → LINE ✅")
            print(f"     {opts_rec.primary.display}  "
                  f"EV={opts_rec.primary.ev:.1f}  "
                  f"POP={opts_rec.primary.pop:.0f}%  "
                  f"{'✅' if opts_rec.trade_approved else '⏸️'}")

            success += 1
            print(f"  ⏱  {futures.runtime + opts_rec.runtime:.1f}s total")
            time.sleep(1.5)

        except Exception:
            fail += 1
            logger.error("[%s] UNHANDLED:\n%s", symbol, traceback.format_exc())
            print(f"  ❌ ERROR:\n{traceback.format_exc()}")

    print(f"\n{'━'*44}")
    print(f"🏁 DONE  ✅ {success}  ❌ {fail}")
    logger.info("Engine done — success=%d fail=%d", success, fail)


if __name__ == "__main__":
    try:
        run_trading_engine()
    except Exception:
        logger.critical("GLOBAL ERROR:\n%s", traceback.format_exc())
        print(f"GLOBAL ERROR:\n{traceback.format_exc()}")
