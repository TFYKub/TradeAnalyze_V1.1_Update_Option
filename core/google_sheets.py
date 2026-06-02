import time

import gspread
import numpy as np
import pandas as pd
from oauth2client.service_account import ServiceAccountCredentials


class GoogleSheetsClient:

    def __init__(self, sheet_id: str, cred_file: str):
        self.sheet_id = sheet_id
        self.cred_file = cred_file
        self.client = self._auth()
        self.sheet = self.client.open_by_key(sheet_id)

    # ------------------------------------------------------------------
    # AUTH
    # ------------------------------------------------------------------
    def _auth(self) -> gspread.Client:
        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            self.cred_file, scope
        )
        return gspread.authorize(creds)

    # ------------------------------------------------------------------
    # WORKSHEET (auto-create if missing)
    # ------------------------------------------------------------------
    def get_ws(self, name: str) -> gspread.Worksheet:
        try:
            return self.sheet.worksheet(name)
        except gspread.WorksheetNotFound:
            return self.sheet.add_worksheet(title=name, rows=1000, cols=30)

    # ------------------------------------------------------------------
    # CLEAN DATAFRAME  (single definition — no duplicate)
    # ------------------------------------------------------------------
    def clean_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Replace inf/NaN and convert all columns to Google-Sheets-safe strings."""

        df = df.copy()
        df.replace([np.inf, -np.inf], np.nan, inplace=True)
        df.fillna("", inplace=True)

        for col in df.columns:
            df[col] = df[col].astype(str)

        return df

    # ------------------------------------------------------------------
    # WRITE FULL DATAFRAME (overwrite)
    # ------------------------------------------------------------------
    def write_df(self, ws_name: str, df: pd.DataFrame, retries: int = 3) -> bool:
        ws = self.get_ws(ws_name)
        df = self.clean_df(df)
        values = [df.columns.tolist()] + df.values.tolist()

        for attempt in range(1, retries + 1):
            try:
                ws.clear()
                ws.update(values)
                print(f"[GoogleSheets] Write success → {ws_name}")
                return True
            except Exception as exc:
                print(f"[GoogleSheets] Error attempt {attempt}/{retries}: {exc}")
                time.sleep(2)

        raise RuntimeError(f"Failed to write to sheet after {retries} attempts: {ws_name}")

    # ------------------------------------------------------------------
    # APPEND SINGLE ROW
    # ------------------------------------------------------------------
    def append_row(self, ws_name: str, row: list) -> None:
        ws = self.get_ws(ws_name)
        clean = ["" if (isinstance(x, float) and np.isnan(x)) else x for x in row]
        ws.append_row(clean, value_input_option="USER_ENTERED")

    # ------------------------------------------------------------------
    # BATCH APPEND (fast)
    # ------------------------------------------------------------------
    def append_rows(self, ws_name: str, rows: list[list]) -> None:
        ws = self.get_ws(ws_name)
        clean_rows = [
            ["" if (isinstance(x, float) and np.isnan(x)) else x for x in row]
            for row in rows
        ]
        ws.append_rows(clean_rows, value_input_option="USER_ENTERED")
