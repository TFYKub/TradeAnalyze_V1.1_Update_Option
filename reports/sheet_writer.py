"""
Google Sheets Writer
=====================
เขียนผลลัพธ์ signal + options ลง 2 ชีท:
  • TradeSignals  — สัญญาณ directional + Greek overlay
  • Options       — option strategy setup + Monte Carlo
"""

import logging
from datetime import datetime

from config.config import SHEET_ID
from utils.sheets_auth import get_sheets_client

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _first(x) -> dict:
    """คืน element แรกถ้าเป็น list หรือคืน dict ตรงๆ"""
    if isinstance(x, list) and x:
        return x[0]
    if isinstance(x, dict):
        return x
    return {}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _safe(v):
    """Convert ค่าให้เป็น Google Sheets-safe scalar"""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, list):
        return " | ".join(str(i) for i in v)   # conviction_reasons list → string
    if isinstance(v, float):
        import math
        if math.isnan(v) or math.isinf(v):
            return ""
        return round(v, 6)
    return v


def _ensure_headers(ws, headers: list[str]) -> None:
    """Insert header row ถ้ายังไม่มี"""
    try:
        first_row = ws.row_values(1)
        if not first_row or first_row[0] != headers[0]:
            ws.insert_row(headers, index=1)
    except Exception as exc:
        logger.warning(f"Header check failed: {exc}")


# ──────────────────────────────────────────────────────────────────────────────
# TRADE SIGNALS SHEET
# คอลัมน์: Timestamp | Symbol | AssetType | Regime | Position | Price |
#          Entry | SL | TP1 | TP2 | Risk | HoldingDays |
#          Conviction | ConvictionReasons | GreekStrategy |
#          IVRank | IVEnv | SkewPC | AvgIV | PCOIRatio |
#          DomDTE | NearTermRisk | AvgGamma | FastDecayPct |
#          MC_Bull | MC_Bear | MC_Sideway
# ──────────────────────────────────────────────────────────────────────────────
_TRADE_HEADERS = [
    "Timestamp", "Symbol", "AssetType", "Regime", "Position", "Price",
    "Entry", "SL", "TP1", "TP2", "Risk", "HoldingDays",
    "Conviction", "ConvictionReasons", "GreekStrategy",
    "IVRank", "IVEnvironment", "DeltaSkew", "AvgIV", "PCOIRatio",
    "DomDTE", "NearTermRisk", "AvgGamma", "FastDecayPct",
    "MC_Bull", "MC_Bear", "MC_Sideway",
]


def log_trade_signals(symbol: str, signals: list | dict, monte: list | dict) -> None:

    s = _first(signals)
    m = _first(monte)

    row = [
        _now(),
        symbol,
        _safe(s.get("asset_type", "stock")),
        _safe(s.get("regime", "")),
        _safe(s.get("position", "")),
        _safe(s.get("price", s.get("entry", ""))),
        _safe(s.get("entry", "")),
        _safe(s.get("sl", "")),
        _safe(s.get("tp1", "")),
        _safe(s.get("tp2", "")),
        _safe(s.get("risk", "")),
        _safe(s.get("holding_days", "")),
        _safe(s.get("greek_conviction", "")),
        _safe(s.get("conviction_reasons", [])),   # list → " | " string
        _safe(s.get("greek_strategy_hint", "")),
        _safe(s.get("iv_rank_proxy", "")),
        _safe(s.get("iv_environment", "")),
        _safe(s.get("put_call_delta_skew", "")),
        _safe(s.get("avg_iv", "")),
        _safe(s.get("pc_oi_ratio", "")),
        _safe(s.get("dominant_dte", "")),
        _safe(s.get("near_term_risk", "")),
        _safe(s.get("avg_gamma", "")),
        _safe(s.get("fast_decay_pct", "")),
        _safe(m.get("bull", "")),
        _safe(m.get("bear", "")),
        _safe(m.get("sideway", "")),
    ]

    try:
        gc = get_sheets_client()
        ws = gc.open_by_key(SHEET_ID).worksheet("TradeSignals")
        _ensure_headers(ws, _TRADE_HEADERS)
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"[sheet_writer] TradeSignals ← {symbol}")
    except Exception as exc:
        logger.error(f"[sheet_writer] TradeSignals write failed ({symbol}): {exc}")
        raise


# ──────────────────────────────────────────────────────────────────────────────
# OPTIONS SHEET
# คอลัมน์: Timestamp | Symbol | Strategy | Direction |
#          Entry | Target | BuyCall | SellCall | BuyPut | SellPut |
#          DTE | POP | MC_Bull | MC_Bear | MC_Sideway
# ──────────────────────────────────────────────────────────────────────────────
_OPTIONS_HEADERS = [
    "Timestamp", "Symbol", "Strategy", "Direction",
    "Entry", "Target", "BuyCall", "SellCall", "BuyPut", "SellPut",
    "DTE", "POP", "MC_Bull", "MC_Bear", "MC_Sideway",
]


def log_options_signals(symbol: str, options: list | dict, monte: list | dict) -> None:

    o = _first(options)
    m = _first(monte)

    row = [
        _now(),
        symbol,
        _safe(o.get("strategy", "")),
        _safe(o.get("direction", "")),
        _safe(o.get("entry", "")),
        _safe(o.get("target", "")),
        _safe(o.get("buy_call", "")),
        _safe(o.get("sell_call", "")),
        _safe(o.get("buy_put", "")),
        _safe(o.get("sell_put", "")),
        _safe(o.get("dte", "")),
        _safe(o.get("pop", "")),
        _safe(m.get("bull", "")),
        _safe(m.get("bear", "")),
        _safe(m.get("sideway", "")),
    ]

    try:
        gc = get_sheets_client()
        ws = gc.open_by_key(SHEET_ID).worksheet("Options")
        _ensure_headers(ws, _OPTIONS_HEADERS)
        ws.append_row(row, value_input_option="USER_ENTERED")
        logger.info(f"[sheet_writer] Options ← {symbol}")
    except Exception as exc:
        logger.error(f"[sheet_writer] Options write failed ({symbol}): {exc}")
        raise


# ──────────────────────────────────────────────────────────────────────────────
# MARKET DATA SHEET  (ใช้โดย pipeline.py)
# ──────────────────────────────────────────────────────────────────────────────
def write_market_data(rows: list[list]) -> None:
    """Append raw market snapshot rows to the MarketData worksheet."""
    try:
        gc = get_sheets_client()
        ws = gc.open_by_key(SHEET_ID).worksheet("MarketData")
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        logger.info(f"[sheet_writer] MarketData ← {len(rows)} rows")
    except Exception as exc:
        logger.error(f"[sheet_writer] MarketData write failed: {exc}")
        raise
