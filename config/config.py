import os

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_TOKEN")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDENTIALS = os.getenv("GOOGLE_CREDENTIALS")

if not SHEET_ID:
    raise EnvironmentError("Missing SHEET_ID in environment variables")

if not GOOGLE_CREDENTIALS:
    raise EnvironmentError("Missing GOOGLE_CREDENTIALS in environment variables")

TIMEZONE = "Asia/Bangkok"
