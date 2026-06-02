# TradeAnalyze

Automated daily trading-signal engine for Thai retail investors.

## What it does

1. Downloads 2 years of OHLCV data via **yfinance**
2. Classifies market regime (STRONG_BULL / BULL / BEAR / CORRECTION / RANGE)
3. Generates futures signals, options strategies, and Monte Carlo probabilities
4. Writes results to **Google Sheets** and broadcasts via **LINE Messaging API**

## Directory structure

```
alerts/          LINE notification
config/          Env vars, logging, validation
core/            Orchestrator + Google Sheets client
data/            Market data + indicator pipeline
engines/         Regime, signal, option, Monte Carlo engines
pipeline/        Batch market-data pipeline
reports/         Formatter + Google Sheets writer
utils/           Retry, safe_run, symbol loader, shared Sheets auth
main.py          Entry point
```

## Required environment variables

| Variable             | Description                          |
|----------------------|--------------------------------------|
| `SHEET_ID`           | Google Sheets document ID            |
| `GOOGLE_CREDENTIALS` | Service account JSON (stringified)   |
| `LINE_TOKEN`         | LINE Channel Access Token            |

## Running locally

```bash
pip install -r requirements.txt
export SHEET_ID=...
export GOOGLE_CREDENTIALS='{"type":"service_account",...}'
export LINE_TOKEN=...
python main.py
```

## GitHub Actions

Runs automatically at **07:00 Bangkok time** (UTC 00:00) via `.github/workflows/daily.yml`.
