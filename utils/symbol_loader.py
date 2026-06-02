from config.config import SHEET_ID
from utils.sheets_auth import get_sheets_client


def load_symbols(group: str = "LINE") -> list[str]:
    """Load symbols from the SYMBOL_CONFIG worksheet filtered by group."""

    gc = get_sheets_client()
    sheet = gc.open_by_key(SHEET_ID)
    ws = sheet.worksheet("SYMBOL_CONFIG")

    rows = ws.get_all_records()

    return [r["symbol"] for r in rows if r.get("group") == group]


def load_symbols_with_type(group: str = "LINE") -> list[dict]:
    """
    Load symbols with their asset_type from SYMBOL_CONFIG.

    Expected columns: symbol | group | asset_type (stock | crypto)
    If asset_type column is absent, defaults to "stock".

    Returns: [{"symbol": "AAPL", "asset_type": "stock"}, ...]
    """

    gc = get_sheets_client()
    sheet = gc.open_by_key(SHEET_ID)
    ws = sheet.worksheet("SYMBOL_CONFIG")

    rows = ws.get_all_records()

    return [
        {
            "symbol":     r["symbol"],
            "asset_type": r.get("asset_type", "stock").lower(),
        }
        for r in rows
        if r.get("group") == group
    ]
