from data.market_data import get_market_data
from reports.sheet_writer import write_market_data
from utils.symbol_loader import load_symbols


def run_pipeline() -> None:

    print("\n🚀 ===== PIPELINE START =====")

    # ------------------------------------------------------------------
    # STEP 1: Load symbols
    # ------------------------------------------------------------------
    print("\n📥 STEP 1: Loading symbols...")

    try:
        symbols = load_symbols("DATA")
        print(f"✅ Symbols loaded: {len(symbols)}")
        print("🔎 SAMPLE:", symbols[:5])
    except Exception as exc:
        print("❌ STEP 1 FAILED:", exc)
        return

    # ------------------------------------------------------------------
    # STEP 2: Fetch market data
    # ------------------------------------------------------------------
    print("\n⚙️  STEP 2: Fetching market data...")

    rows = []

    for i, sym in enumerate(symbols, 1):
        print(f"Processing {i}/{len(symbols)}: {sym}")
        try:
            df = get_market_data(sym)
            last = df.iloc[-1]

            rows.append([
                sym,
                round(float(last["Close"]), 4),
                round(float(last["ATR14"]), 4),
                round(float(last["RSI14"]), 2),
                round(float(last["HV20"]), 4),
                int(last["TrendScore"]),
            ])
        except Exception as exc:
            print(f"  ⚠️  Skipping {sym}: {exc}")

    print(f"✅ STEP 2 DONE: {len(rows)} rows collected")

    # ------------------------------------------------------------------
    # STEP 3: Validate
    # ------------------------------------------------------------------
    print("\n🧪 STEP 3: Validation...")

    if not rows:
        print("❌ NO DATA GENERATED")
        return

    print("✅ Data OK")

    # ------------------------------------------------------------------
    # STEP 4: Write to Google Sheets
    # ------------------------------------------------------------------
    print("\n📤 STEP 4: Writing to Google Sheets...")

    try:
        write_market_data(rows)
        print("✅ PIPELINE SUCCESS")
    except Exception as exc:
        print("❌ STEP 4 FAILED:", exc)
        return

    print("\n🏁 END PIPELINE")


if __name__ == "__main__":
    run_pipeline()
