"""
TradeAnalyze — Main Entry Point
================================
Flow per symbol:
  1. Fetch market data + indicators
  2. Fetch option chain  (yfinance/Deribit)
  3. Compute Greeks      (Black-Scholes / Deribit native)
  4. Generate signal     (Greek-aware)
  5. Write Option_Chain  → Google Sheets
  6. Write TradeSignals  → Google Sheets
  7. Write Options       → Google Sheets
  8. Broadcast           → LINE Messaging API (one message per symbol)

ตั้งค่า SYMBOL_CONFIG columns:
  symbol | group | asset_type
  AAPL   | LINE  | stock
  BTC    | LINE  | crypto
"""

import time
import traceback

from config.logging_config import logger
from config.config_validator import validate
from core.orchestrator import TradeOrchestrator
from alerts.line_alert import send_line_message
from reports.formatter import format_symbol_message
from reports.option_chain_writer import clear_symbol_rows, write_option_chain
from reports.sheet_writer import log_trade_signals, log_options_signals
from utils.symbol_loader import load_symbols_with_type


# ──────────────────────────────────────────────────────────────────────────────
# ENGINE
# ──────────────────────────────────────────────────────────────────────────────
def run_trading_engine() -> None:

    validate()

    orchestrator = TradeOrchestrator()
    success = fail = 0

    symbol_list = load_symbols_with_type("LINE")

    if not symbol_list:
        logger.warning("No symbols found in SYMBOL_CONFIG (group=LINE)")
        print("❌ No symbols found in Google Sheet (SYMBOL_CONFIG)")
        return

    print(f"\n🚀 ===== TRADING ENGINE START =====")
    print(f"📊 Symbols loaded: {len(symbol_list)}")

    for item in symbol_list:
        symbol     = item["symbol"]
        asset_type = item["asset_type"]

        print(f"\n{'─'*40}")
        print(f"📊 Processing: {symbol}  ({asset_type})")

        try:
            data = orchestrator.run(symbol, asset_type=asset_type)

            if not data:
                logger.warning(f"[{symbol}] orchestrator returned None")
                fail += 1
                continue

            signals        = data["signals"]
            options        = data["options"]
            monte          = data["monte"]
            enriched_chain = data["option_chain"]
            runtime        = data["runtime"]

            signal = signals[0]
            option = options[0]
            mc     = monte[0]

            # ── 1. Option Chain → Google Sheets ───────────────────────────────
            chain_rows = 0
            if enriched_chain:
                try:
                    clear_symbol_rows(symbol)
                    chain_rows = write_option_chain(symbol, enriched_chain)
                    print(f"  📋 Option chain : {chain_rows} rows → Option_Chain")
                except Exception as exc:
                    logger.error(f"[{symbol}] option chain write: {exc}")
                    print(f"  ⚠️  Option chain write failed: {exc}")
            else:
                print(f"  ⚠️  Option chain : no data (skipped)")

            # ── 2. Signal → Google Sheets ─────────────────────────────────────
            log_trade_signals(symbol, signals, monte)
            log_options_signals(symbol, options, monte)
            print(f"  ✅ Sheets       : TradeSignals + Options written")

            # ── 3. LINE broadcast  (per symbol) ──────────────────────────────
            msg = format_symbol_message(signal, option, mc, enriched_chain)

            if len(msg) > 4500:
                msg = msg[:4490] + "\n…(truncated)"

            sent = send_line_message(msg)
            status = "✅ sent" if sent else "⚠️ skipped (no LINE token)"
            print(f"  📱 LINE         : {status}")

            success += 1
            print(f"  ⏱  Runtime      : {runtime}s")

            # Rate-limit buffer
            time.sleep(1.5)

        except Exception:
            fail += 1
            logger.error(f"[{symbol}] UNHANDLED:\n{traceback.format_exc()}")
            print(f"  ❌ ERROR:\n{traceback.format_exc()}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'━'*40}")
    print(f"🏁 ENGINE DONE  ✅ {success}  ❌ {fail}")
    logger.info(f"Engine done — success={success} fail={fail}")


# ──────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    try:
        run_trading_engine()
    except Exception:
        logger.critical(f"GLOBAL ERROR:\n{traceback.format_exc()}")
        print(f"GLOBAL ERROR:\n{traceback.format_exc()}")
