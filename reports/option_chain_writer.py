"""
Option Chain Sheet Writer
==========================
Writes enriched option-chain rows (with Greeks) to the
"Option_Chain" worksheet in Google Sheets.

Performance strategy
--------------------
• clear_symbol_rows() → uses batch-delete with a single values fetch,
  then reverses indices — no row-by-row API calls.
• write_option_chain() → single append_rows() call per symbol.

Sheet schema (26 columns)
--------------------------
Timestamp | Symbol | Source | Expiry | DTE | DTE_Bucket | Type
Strike | Bid | Ask | Mid | Last | IV | Volume | OI | ITM
Delta | Gamma | Theta | Vega | Rho
Moneyness | High_Gamma | Theta_Category | Vega_Category | Direction_Bias
"""

import logging
import math
from datetime import datetime

from config.config import SHEET_ID
from utils.sheets_auth import get_sheets_client

logger = logging.getLogger(__name__)

SHEET_NAME = "Option_Chain"

HEADERS = [
    "Timestamp", "Symbol", "Source",
    "Expiry", "DTE", "DTE_Bucket", "Type",
    "Strike", "Bid", "Ask", "Mid", "Last",
    "IV", "Volume", "OI", "ITM",
    "Delta", "Gamma", "Theta", "Vega", "Rho",
    "Moneyness", "High_Gamma",
    "Theta_Category", "Vega_Category", "Direction_Bias",
]

# Column B (index 1) = Symbol
_SYMBOL_COL_IDX = 1


def _safe(v):
    """Convert to a Google-Sheets-safe scalar."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v) or math.isinf(v):
            return ""
        return round(v, 6)
    return v


def _row_from(ts: str, symbol: str, r: dict) -> list:
    return [
        ts,
        symbol,
        _safe(r.get("source")),
        _safe(r.get("expiry")),
        _safe(r.get("dte")),
        _safe(r.get("dte_bucket")),
        _safe(r.get("option_type")),
        _safe(r.get("strike")),
        _safe(r.get("bid")),
        _safe(r.get("ask")),
        _safe(r.get("mid")),
        _safe(r.get("last")),
        _safe(r.get("iv")),
        _safe(r.get("volume")),
        _safe(r.get("open_interest")),
        _safe(r.get("in_the_money")),
        _safe(r.get("delta")),
        _safe(r.get("gamma")),
        _safe(r.get("theta")),
        _safe(r.get("vega")),
        _safe(r.get("rho")),
        _safe(r.get("moneyness")),
        _safe(r.get("high_gamma")),
        _safe(r.get("theta_category")),
        _safe(r.get("vega_category")),
        _safe(r.get("direction_bias")),
    ]


def _ensure_headers(ws) -> None:
    """Write header row if the sheet is empty or header is missing."""
    try:
        first = ws.row_values(1)
        if not first or first[0] != "Timestamp":
            ws.insert_row(HEADERS, index=1)
            logger.info("[option_chain_writer] Header row inserted")
    except Exception as exc:
        logger.warning(f"[option_chain_writer] header check failed: {exc}")


def write_option_chain(symbol: str, enriched_rows: list[dict]) -> int:
    """
    Append enriched option rows to the Option_Chain sheet.

    Returns the number of rows written.
    """

    if not enriched_rows:
        logger.info(f"[option_chain_writer] {symbol}: no rows to write")
        return 0

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    gc = get_sheets_client()
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    _ensure_headers(ws)

    batch = [_row_from(ts, symbol, r) for r in enriched_rows]

    try:
        ws.append_rows(batch, value_input_option="USER_ENTERED")
        logger.info(f"[option_chain_writer] {symbol}: wrote {len(batch)} rows")
        return len(batch)
    except Exception as exc:
        logger.error(f"[option_chain_writer] {symbol}: write failed — {exc}")
        raise


def clear_symbol_rows(symbol: str) -> int:
    """
    Delete all existing data rows for *symbol* in one batch operation.

    Strategy
    --------
    1. Fetch all values in one API call.
    2. Collect 1-indexed row numbers where column B == symbol (skip header).
    3. Delete in reverse order (bottom-up) to keep row indices stable.

    Returns number of rows deleted.
    """

    gc = get_sheets_client()
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)

    try:
        all_values = ws.get_all_values()   # single API call
    except Exception as exc:
        logger.warning(f"[option_chain_writer] clear: read failed — {exc}")
        return 0

    # Skip header row (index 0), find matching rows (1-indexed for Sheets API)
    to_delete = [
        i + 1
        for i, row in enumerate(all_values)
        if i > 0
        and len(row) > _SYMBOL_COL_IDX
        and row[_SYMBOL_COL_IDX] == symbol
    ]

    if not to_delete:
        return 0

    # Delete bottom-up so row indices don't shift
    deleted = 0
    for row_idx in reversed(to_delete):
        try:
            ws.delete_rows(row_idx)
            deleted += 1
        except Exception as exc:
            logger.debug(f"[option_chain_writer] delete row {row_idx}: {exc}")

    logger.info(f"[option_chain_writer] {symbol}: cleared {deleted} stale rows")
    return deleted


def overwrite_all_symbols(all_enriched: dict[str, list[dict]]) -> int:
    """
    Full refresh: clear ALL data rows and rewrite every symbol in one session.

    More efficient than clear_symbol_rows() per symbol when processing many
    symbols at once — only one `get_all_values()` call total.

    Parameters
    ----------
    all_enriched : {symbol: [enriched_rows]}

    Returns total rows written.
    """

    if not all_enriched:
        return 0

    gc = get_sheets_client()
    ws = gc.open_by_key(SHEET_ID).worksheet(SHEET_NAME)
    _ensure_headers(ws)

    # Clear all data below header in one call
    try:
        last_row = ws.row_count
        if last_row > 1:
            ws.delete_rows(2, last_row)
    except Exception as exc:
        logger.warning(f"[option_chain_writer] bulk clear failed: {exc}")

    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    all_rows: list[list] = []

    for symbol, enriched_rows in all_enriched.items():
        for r in enriched_rows:
            all_rows.append(_row_from(ts, symbol, r))

    if not all_rows:
        return 0

    ws.append_rows(all_rows, value_input_option="USER_ENTERED")
    logger.info(f"[option_chain_writer] bulk write: {len(all_rows)} total rows")
    return len(all_rows)
