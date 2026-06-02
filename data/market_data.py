import numpy as np
import pandas as pd
import yfinance as yf

from config.logging_config import logger
from utils.retry import retry


def get_market_data(symbol: str) -> pd.DataFrame:
    """
    Download 2 years of daily OHLCV data for *symbol* and enrich with
    technical indicators: EMA, RSI-14, ATR-14, historical volatility,
    momentum, drawdown, and composite trend / vol scores.
    """

    logger.info(f"Downloading {symbol}")

    df: pd.DataFrame = retry(
        lambda: yf.download(
            symbol,
            period="2y",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
    )

    if df is None or df.empty:
        raise ValueError(f"No data returned for {symbol}")

    # Flatten MultiIndex columns produced by yfinance for single tickers
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"{symbol}: Missing column '{col}'")

    df = df.copy()

    # ------------------------------------------------------------------
    # RETURNS
    # ------------------------------------------------------------------
    df["Return"] = df["Close"].pct_change()
    df["LogReturn"] = np.log(df["Close"] / df["Close"].shift(1))

    # ------------------------------------------------------------------
    # EMA
    # ------------------------------------------------------------------
    df["EMA20"] = df["Close"].ewm(span=20, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["EMA200"] = df["Close"].ewm(span=200, adjust=False).mean()
    df["EMA20_Slope"] = df["EMA20"].pct_change(5)

    # ------------------------------------------------------------------
    # RSI-14
    # ------------------------------------------------------------------
    delta = df["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss
    df["RSI14"] = 100 - (100 / (1 + rs))

    # ------------------------------------------------------------------
    # MOMENTUM
    # ------------------------------------------------------------------
    df["ROC20"] = df["Close"].pct_change(20) * 100
    df["Momentum20"] = df["Close"] - df["Close"].shift(20)

    # ------------------------------------------------------------------
    # ATR-14  (Wilder's EMA smoothing)
    # ------------------------------------------------------------------
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()

    # ------------------------------------------------------------------
    # HISTORICAL VOLATILITY
    # ------------------------------------------------------------------
    df["HV20"] = df["Return"].rolling(20).std() * np.sqrt(252)
    df["HV60"] = df["Return"].rolling(60).std() * np.sqrt(252)

    # ------------------------------------------------------------------
    # DRAWDOWN
    # ------------------------------------------------------------------
    rolling_max = df["Close"].cummax()
    df["Drawdown"] = (df["Close"] - rolling_max) / rolling_max

    # ------------------------------------------------------------------
    # TREND SCORE  (0–3)
    # ------------------------------------------------------------------
    df["TrendScore"] = (
        (df["EMA20"] > df["EMA50"]).astype(int)
        + (df["EMA50"] > df["EMA200"]).astype(int)
        + (df["Close"] > df["EMA20"]).astype(int)
    )

    # ------------------------------------------------------------------
    # VOL SCORE  (ATR as % of price)
    # ------------------------------------------------------------------
    df["VolScore"] = df["ATR14"] / df["Close"]

    logger.info(f"{symbol}: {len(df)} rows loaded")

    return df
