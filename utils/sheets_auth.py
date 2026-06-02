"""
Shared Google Sheets authentication helper.
Single source of truth — imported by symbol_loader and sheet_writer.
"""

import json
import os

import gspread
from oauth2client.service_account import ServiceAccountCredentials

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def get_sheets_client() -> gspread.Client:
    """Authenticate and return an authorised gspread client."""

    creds_json = os.getenv("GOOGLE_CREDENTIALS")

    if not creds_json:
        raise EnvironmentError("Missing GOOGLE_CREDENTIALS environment variable")

    creds_dict = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, SCOPES)

    return gspread.authorize(creds)
