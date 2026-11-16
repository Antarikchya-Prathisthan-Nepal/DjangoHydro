import requests
import pandas as pd
from datetime import date
from io import StringIO
import gspread
from gspread_dataframe import set_with_dataframe
import json
import time
from rainfall_stations import RAINFALL_STATIONS


# ---------------------------
# Fetch daily rainfall data
# ---------------------------
def fetch_rainfall_daily(seriesid):
    url = "https://dhm.gov.np/hydrology/getRainfallWatchBySeriesId_single"
    payload = {
        "date": str(date.today()),
        "period": "3",  # daily
        "seriesid": seriesid,
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    resp = requests.post(url, data=payload, headers=headers, timeout=30)
    resp.raise_for_status()

    data = resp.json()
    table_html = data["data"]["table"]
    df = pd.read_html(StringIO(table_html))[0]

    df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
    return df


# ---------------------------
# Rate-limit retry helper
# ---------------------------
def api_call_with_retry(func, *args, max_retries=5, **kwargs):
    """Retry a gspread API call with exponential backoff on 429 errors."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except gspread.exceptions.APIError as e:
            if e.response.status_code == 429:
                wait = 60 * (attempt + 1)
                print(f"  ⏳ Rate limited. Waiting {wait}s before retry {attempt + 1}/{max_retries}...")
                time.sleep(wait)
            else:
                raise
    raise Exception(f"Failed after {max_retries} retries due to rate limiting.")


# ---------------------------
# Connect to Google Drive
# ---------------------------
with open("service_account.json") as f:
    creds = json.load(f)

gc = gspread.service_account_from_dict(creds)

# ---------------------------
# Open an existing spreadsheet
# ---------------------------
spreadsheet_name = "DHM_rainfall"
try:
    sh = gc.open(spreadsheet_name)
except gspread.SpreadsheetNotFound:
    raise Exception(f"Spreadsheet '{spreadsheet_name}' not found. Make sure it exists in your Google Drive and is shared with the service account.")


# ---------------------------
# Update worksheet with new data
# ---------------------------
def update_worksheet(sh, worksheet_name, new_df):
    try:
        ws = api_call_with_retry(sh.worksheet, worksheet_name)
    except gspread.WorksheetNotFound:
        ws = api_call_with_retry(sh.add_worksheet, title=worksheet_name, rows="2000", cols="10")

    existing_records = api_call_with_retry(ws.get_all_records)
    existing_df = pd.DataFrame(existing_records)

    if not existing_df.empty:
        existing_df["Date"] = pd.to_datetime(existing_df["Date"], format="ISO8601")
        min_new, max_new = new_df["Date"].min(), new_df["Date"].max()
        existing_df = existing_df[~existing_df["Date"].between(min_new, max_new)]
        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined = new_df

    combined = combined.sort_values("Date").reset_index(drop=True)

    api_call_with_retry(ws.clear)
    api_call_with_retry(set_with_dataframe, ws, combined)


# ---------------------------
# Loop over stations
# ---------------------------
for station_name, cfg in RAINFALL_STATIONS.items():
    print(f"📥 Fetching {station_name}")

    try:
        df = fetch_rainfall_daily(cfg["seriesid"])
        update_worksheet(sh, cfg["worksheet"], df)
        print(f"✅ Updated {station_name}")
        time.sleep(2)  # avoid quota limits
    except Exception as e:
        print(f"❌ Failed for {station_name}: {e}")
