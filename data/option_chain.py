"""
Option Chain Fetcher
====================
- Stocks  → yfinance  (Ticker.options + Ticker.option_chain)
- Crypto  → Deribit REST API  (no auth required for public endpoints)

Filters applied before returning:
  • Strike within ±20 % of spot
  • DTE bucket matches one of: 7, 14, 30, 60, 90 days (±3-day tolerance)
"""

import logging
import math
from datetime import datetime, timezone
from typing import Literal

import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────
TARGET_DTES   = [7, 14, 30, 60, 90]   # desired DTE buckets
DTE_TOLERANCE = 3                      # ±3 calendar days counts as the bucket
STRIKE_BAND   = 0.20                   # ±20 % of spot
DERIBIT_BASE  = "https://www.deribit.com/api/v2/public"


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def _dte(expiry_date: datetime) -> int:
    """Calendar days from now (UTC) to *expiry_date*."""
    now = datetime.now(timezone.utc).replace(tzinfo=timezone.utc)
    expiry = expiry_date.replace(tzinfo=timezone.utc) if expiry_date.tzinfo is None else expiry_date
    return max(0, (expiry - now).days)


def _nearest_dte_bucket(dte: int) -> int | None:
    """Return the matching TARGET_DTES bucket or None if out of range."""
    for target in TARGET_DTES:
        if abs(dte - target) <= DTE_TOLERANCE:
            return target
    return None


def _strike_ok(strike: float, spot: float) -> bool:
    return spot * (1 - STRIKE_BAND) <= strike <= spot * (1 + STRIKE_BAND)


def _mid(bid, ask) -> float:
    try:
        b, a = float(bid), float(ask)
        if b > 0 and a > 0:
            return round((b + a) / 2, 6)
        return float(bid or ask or 0)
    except Exception:
        return 0.0


# ──────────────────────────────────────────────────────────────────────────────
# STOCKS — yfinance
# ──────────────────────────────────────────────────────────────────────────────
def fetch_yf_chain(symbol: str, spot: float) -> list[dict]:
    """
    Fetch option chain for *symbol* via yfinance.

    Returns a list of flat row dicts (one per strike/expiry/type combination).
    """

    rows: list[dict] = []

    try:
        tk = yf.Ticker(symbol)
        expirations = tk.options          # tuple of "YYYY-MM-DD" strings
    except Exception as exc:
        logger.warning(f"[yfinance] {symbol}: cannot fetch expirations — {exc}")
        return rows

    for exp_str in expirations:
        exp_date = datetime.strptime(exp_str, "%Y-%m-%d")
        dte = _dte(exp_date)
        bucket = _nearest_dte_bucket(dte)
        if bucket is None:
            continue

        try:
            chain = tk.option_chain(exp_str)
        except Exception as exc:
            logger.debug(f"[yfinance] {symbol} {exp_str}: {exc}")
            continue

        for opt_type, df in (("call", chain.calls), ("put", chain.puts)):
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                strike = float(row.get("strike", 0))
                if not _strike_ok(strike, spot):
                    continue

                iv = float(row.get("impliedVolatility", 0) or 0)

                rows.append({
                    "source":       "yfinance",
                    "symbol":       symbol,
                    "expiry":       exp_str,
                    "dte":          dte,
                    "dte_bucket":   bucket,
                    "option_type":  opt_type,
                    "strike":       strike,
                    "bid":          float(row.get("bid", 0) or 0),
                    "ask":          float(row.get("ask", 0) or 0),
                    "mid":          _mid(row.get("bid"), row.get("ask")),
                    "last":         float(row.get("lastPrice", 0) or 0),
                    "iv":           round(iv, 4),
                    "volume":       int(row.get("volume", 0) or 0),
                    "open_interest": int(row.get("openInterest", 0) or 0),
                    "in_the_money": bool(row.get("inTheMoney", False)),
                })

    logger.info(f"[yfinance] {symbol}: {len(rows)} option rows fetched")
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# CRYPTO — Deribit public REST
# ──────────────────────────────────────────────────────────────────────────────
_DERIBIT_CURRENCY_MAP = {
    "BTC-USD":  "BTC",
    "ETH-USD":  "ETH",
    "BTC/USD":  "BTC",
    "ETH/USD":  "ETH",
    "BTCUSDT":  "BTC",
    "ETHUSDT":  "ETH",
    "BTC":      "BTC",
    "ETH":      "ETH",
}


def _deribit_currency(symbol: str) -> str | None:
    return _DERIBIT_CURRENCY_MAP.get(symbol.upper())


def _deribit_get(path: str, params: dict | None = None, timeout: int = 15) -> dict:
    url = f"{DERIBIT_BASE}/{path}"
    resp = requests.get(url, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Deribit error: {data['error']}")
    return data.get("result", {})


def fetch_deribit_chain(symbol: str, spot: float) -> list[dict]:
    """
    Fetch option chain for a crypto symbol via Deribit public API.

    Returns a list of flat row dicts matching the same schema as fetch_yf_chain.
    """

    currency = _deribit_currency(symbol)
    if not currency:
        logger.warning(f"[Deribit] Unknown crypto symbol: {symbol}")
        return []

    rows: list[dict] = []

    try:
        instruments = _deribit_get(
            "get_instruments",
            {"currency": currency, "kind": "option", "expired": "false"},
        )
    except Exception as exc:
        logger.warning(f"[Deribit] {symbol}: cannot fetch instruments — {exc}")
        return rows

    # Group instruments by expiry to batch-fetch tickers
    now_ms = datetime.now(timezone.utc).timestamp() * 1000

    for inst in instruments:
        exp_ms  = inst.get("expiration_timestamp", 0)
        strike  = float(inst.get("strike", 0))
        inst_name = inst.get("instrument_name", "")

        if not inst_name or exp_ms <= now_ms:
            continue

        exp_date = datetime.fromtimestamp(exp_ms / 1000, tz=timezone.utc)
        dte      = _dte(exp_date)
        bucket   = _nearest_dte_bucket(dte)

        if bucket is None:
            continue
        if not _strike_ok(strike, spot):
            continue

        # instrument name encodes C/P: BTC-28JUN24-70000-C
        opt_type = "call" if inst_name.endswith("-C") else "put"

        try:
            ticker = _deribit_get("ticker", {"instrument_name": inst_name})
        except Exception as exc:
            logger.debug(f"[Deribit] ticker {inst_name}: {exc}")
            continue

        bid = float(ticker.get("best_bid_price", 0) or 0)
        ask = float(ticker.get("best_ask_price", 0) or 0)
        iv  = float(ticker.get("mark_iv", 0) or 0) / 100   # Deribit returns IV in %

        greeks_raw = ticker.get("greeks", {})

        rows.append({
            "source":        "deribit",
            "symbol":        symbol,
            "expiry":        exp_date.strftime("%Y-%m-%d"),
            "dte":           dte,
            "dte_bucket":    bucket,
            "option_type":   opt_type,
            "strike":        strike,
            "bid":           round(bid * spot, 4),     # convert BTC-denominated → USD
            "ask":           round(ask * spot, 4),
            "mid":           round(_mid(bid, ask) * spot, 4),
            "last":          round(float(ticker.get("last_price", 0) or 0) * spot, 4),
            "iv":            round(iv, 4),
            "volume":        int(ticker.get("stats", {}).get("volume", 0) or 0),
            "open_interest": int(ticker.get("open_interest", 0) or 0),
            "in_the_money":  strike < spot if opt_type == "call" else strike > spot,
            # Deribit provides greeks directly — we'll override with BS if IV is missing
            "_deribit_delta": float(greeks_raw.get("delta", 0) or 0),
            "_deribit_gamma": float(greeks_raw.get("gamma", 0) or 0),
            "_deribit_vega":  float(greeks_raw.get("vega",  0) or 0),
            "_deribit_theta": float(greeks_raw.get("theta", 0) or 0),
        })

    logger.info(f"[Deribit] {symbol}: {len(rows)} option rows fetched")
    return rows


# ──────────────────────────────────────────────────────────────────────────────
# UNIFIED ENTRY POINT
# ──────────────────────────────────────────────────────────────────────────────
CRYPTO_SYMBOLS = {s.upper() for s in _DERIBIT_CURRENCY_MAP}


def fetch_option_chain(symbol: str, spot: float, asset_type: str | None = None) -> list[dict]:
    """
    Auto-dispatch to the correct data source.

    Parameters
    ----------
    symbol     : ticker (e.g. "AAPL", "BTC-USD")
    spot       : current spot price
    asset_type : "stock" | "crypto"  — if None, auto-detected from symbol
    """

    if asset_type is None:
        asset_type = "crypto" if symbol.upper() in CRYPTO_SYMBOLS else "stock"

    if asset_type == "crypto":
        return fetch_deribit_chain(symbol, spot)
    else:
        return fetch_yf_chain(symbol, spot)
