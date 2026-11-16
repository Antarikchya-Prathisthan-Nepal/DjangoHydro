import json
import os
import re
import time

import gspread
import pandas as pd
import requests
from gspread_dataframe import set_with_dataframe

from humidity_stations import HUMIDITY_STATIONS


SURFACE_OBSERVATION_URL = "https://dhm.gov.np/hydrology/surface-observation"


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


def _extract_observation_data_from_html(html: str) -> list[dict]:
    match = re.search(r"var\s+observation_data\s*=\s*(\[.*?\]);", html, re.DOTALL)
    if not match:
        raise ValueError("Could not find observation_data in surface-observation HTML.")
    return json.loads(match.group(1))


def fetch_surface_observation_data() -> list[dict]:
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(SURFACE_OBSERVATION_URL, headers=headers, timeout=45)
    resp.raise_for_status()
    return _extract_observation_data_from_html(resp.text)


def _humidity_df_from_observation_data(seriesid: str, observation_data: list[dict]) -> pd.DataFrame:
    target = str(seriesid).strip()

    for station in observation_data:
        observations = station.get("observations") or []
        for obs in observations:
            if str(obs.get("series_id", "")).strip() != target:
                continue

            data_points = obs.get("data") or []
            if not data_points:
                raise ValueError(f"No data available in observation_data for seriesid {target}.")

            rows = []
            for pt in data_points:
                dt = pt.get("datetime")
                value = pt.get("value")
                if dt is None:
                    continue
                rows.append({"Date": dt, "Humidity": value})

            if not rows:
                raise ValueError(f"No valid datetime rows found for seriesid {target}.")

            df = pd.DataFrame(rows)
            df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
            df["Humidity"] = pd.to_numeric(df["Humidity"], errors="coerce")
            df = df.dropna(subset=["Date", "Humidity"])
            return df

    raise ValueError(f"seriesid {target} not found in surface-observation observation_data.")


def _aggregate_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = df["Date"].dt.normalize()
    daily = (
        df.groupby("Date")["Humidity"]
        .agg(Min="min", Max="max", Avg="mean")
        .reset_index()
    )
    daily["Avg"] = daily["Avg"].round(2)
    daily["Date"] = daily["Date"].dt.strftime("%Y-%m-%d")
    return daily


def _normalize_existing_humidity_data(existing_df: pd.DataFrame) -> pd.DataFrame:
    if existing_df.empty or "Date" not in existing_df.columns:
        return pd.DataFrame(columns=["Date", "Min", "Max", "Avg"])

    existing_df = existing_df.copy()

    if "Humidity" in existing_df.columns:
        existing_df["Date"] = pd.to_datetime(existing_df["Date"], format="ISO8601")
        existing_df["Humidity"] = pd.to_numeric(existing_df["Humidity"], errors="coerce")
        existing_df = existing_df.dropna(subset=["Date", "Humidity"])
        if existing_df.empty:
            return pd.DataFrame(columns=["Date", "Min", "Max", "Avg"])
        return _aggregate_to_daily(existing_df[["Date", "Humidity"]])

    daily_cols = {"Date", "Min", "Max", "Avg"}
    if daily_cols.issubset(existing_df.columns):
        existing_df = existing_df[["Date", "Min", "Max", "Avg"]].copy()
        existing_df["Date"] = pd.to_datetime(existing_df["Date"], format="ISO8601")
        existing_df = existing_df.dropna(subset=["Date"])
        if existing_df.empty:
            return pd.DataFrame(columns=["Date", "Min", "Max", "Avg"])
        existing_df["Date"] = existing_df["Date"].dt.strftime("%Y-%m-%d")
        return existing_df

    return pd.DataFrame(columns=["Date", "Min", "Max", "Avg"])


def fetch_humidity_daily(seriesid: str, observation_data: list[dict]) -> pd.DataFrame:
    df = _humidity_df_from_observation_data(seriesid, observation_data)
    return _aggregate_to_daily(df)


def open_spreadsheet() -> gspread.Spreadsheet:
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    with open(creds_path, "r", encoding="utf-8") as f:
        creds = json.load(f)

    gc = gspread.service_account_from_dict(creds)

    spreadsheet_name = os.getenv("DHM_HUMIDITY_SHEET", "DHM_humidity")
    try:
        return gc.open(spreadsheet_name)
    except gspread.SpreadsheetNotFound as exc:
        raise Exception(
            f"Spreadsheet '{spreadsheet_name}' not found. "
            "Create it and share with service account email."
        ) from exc


def update_worksheet(sh: gspread.Spreadsheet, worksheet_name: str, new_df: pd.DataFrame) -> None:
    try:
        ws = api_call_with_retry(sh.worksheet, worksheet_name)
    except gspread.WorksheetNotFound:
        ws = api_call_with_retry(sh.add_worksheet, title=worksheet_name, rows="5000", cols="5")

    existing_df = _normalize_existing_humidity_data(
        pd.DataFrame(api_call_with_retry(ws.get_all_records))
    )

    if not existing_df.empty and "Date" in existing_df.columns:
        existing_dates = pd.to_datetime(existing_df["Date"], errors="coerce").dt.normalize()
        new_df_dates = pd.to_datetime(new_df["Date"], errors="coerce").dt.normalize()
        min_new, max_new = new_df_dates.min(), new_df_dates.max()
        existing_df = existing_df[~existing_dates.between(min_new, max_new)]
        combined = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined = new_df

    combined = combined.sort_values("Date").reset_index(drop=True)

    api_call_with_retry(ws.clear)
    api_call_with_retry(set_with_dataframe, ws, combined)


def main() -> None:
    sh = open_spreadsheet()
    write_delay = float(os.getenv("GSHEET_WRITE_DELAY_SECONDS", "2.0"))

    try:
        observation_data = fetch_surface_observation_data()
        print("[INFO] Loaded station observation_data from surface-observation page.")
    except Exception as e:
        raise RuntimeError(f"Failed to load DHM surface-observation data: {e}")

    for station_name, cfg in HUMIDITY_STATIONS.items():
        seriesid = str(cfg.get("seriesid", "")).strip()
        worksheet = cfg.get("worksheet", station_name)

        if not seriesid or "REPLACE_WITH_DHM_SERIES_ID" in seriesid:
            print(f"[WARN] Skipping {station_name}: set a valid DHM seriesid first.")
            continue

        print(f"[INFO] Fetching {station_name}")
        try:
            df = fetch_humidity_daily(seriesid, observation_data=observation_data)
            update_worksheet(sh, worksheet, df)
            print(f"[OK] Updated {station_name}")
            time.sleep(write_delay)  # avoid quota limits
        except Exception as e:
            print(f"[ERROR] Failed for {station_name}: {e}")


if __name__ == "__main__":
    main()
