import json
import os
import re
import time

import gspread
import pandas as pd
import requests
from gspread_dataframe import set_with_dataframe

from wind_stations import WIND_STATIONS


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


def _wind_df_from_observation_data(speed_seriesid: str, direction_seriesid: str, observation_data: list[dict]) -> pd.DataFrame:
    """Extract wind speed and direction data for a station."""
    speed_target = str(speed_seriesid).strip()
    direction_target = str(direction_seriesid).strip()

    speed_data = {}
    direction_data = {}

    for station in observation_data:
        observations = station.get("observations") or []
        for obs in observations:
            series_id = str(obs.get("series_id", "")).strip()
            data_points = obs.get("data") or []

            if series_id == speed_target:
                for pt in data_points:
                    dt = pt.get("datetime")
                    value = pt.get("value")
                    if dt is not None:
                        speed_data[dt] = value

            elif series_id == direction_target:
                for pt in data_points:
                    dt = pt.get("datetime")
                    value = pt.get("value")
                    if dt is not None:
                        direction_data[dt] = value

    if not speed_data and not direction_data:
        raise ValueError(f"No data found for seriesids {speed_target} or {direction_target}")

    all_dates = set(speed_data.keys()) | set(direction_data.keys())
    rows = []
    for dt in sorted(all_dates):
        row = {"Date": dt}
        row["Wind_Speed"] = speed_data.get(dt)
        row["Wind_Direction"] = direction_data.get(dt)
        rows.append(row)

    df = pd.DataFrame(rows)
    df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
    df["Wind_Speed"] = pd.to_numeric(df["Wind_Speed"], errors="coerce")
    df["Wind_Direction"] = pd.to_numeric(df["Wind_Direction"], errors="coerce")
    df = df.dropna(subset=["Date"], how="any")
    return df


def _aggregate_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate hourly data to daily min/max/avg for both wind speed and direction."""
    df = df.copy()
    df["Date"] = df["Date"].dt.normalize()

    agg_kwargs = {}
    if "Wind_Speed" in df.columns:
        agg_kwargs["Speed_Min"] = pd.NamedAgg(column="Wind_Speed", aggfunc="min")
        agg_kwargs["Speed_Max"] = pd.NamedAgg(column="Wind_Speed", aggfunc="max")
        agg_kwargs["Speed_Avg"] = pd.NamedAgg(column="Wind_Speed", aggfunc="mean")
    if "Wind_Direction" in df.columns:
        agg_kwargs["Direction_Min"] = pd.NamedAgg(column="Wind_Direction", aggfunc="min")
        agg_kwargs["Direction_Max"] = pd.NamedAgg(column="Wind_Direction", aggfunc="max")

    if not agg_kwargs:
        return pd.DataFrame(columns=["Date"])

    daily = df.groupby("Date").agg(**agg_kwargs).reset_index()

    for col in daily.columns:
        if "Avg" in col:
            daily[col] = daily[col].round(2)

    daily["Date"] = daily["Date"].dt.strftime("%Y-%m-%d")
    return daily


def _normalize_existing_wind_data(existing_df: pd.DataFrame) -> pd.DataFrame:
    if existing_df.empty or "Date" not in existing_df.columns:
        return pd.DataFrame(columns=["Date"])

    existing_df = existing_df.copy()
    existing_df["Date"] = pd.to_datetime(existing_df["Date"], format="ISO8601")
    existing_df = existing_df.dropna(subset=["Date"])

    if existing_df.empty:
        return pd.DataFrame(columns=["Date"])

    existing_df["Date"] = existing_df["Date"].dt.strftime("%Y-%m-%d")
    return existing_df


def fetch_wind_daily(speed_seriesid: str, direction_seriesid: str, observation_data: list[dict]) -> pd.DataFrame:
    """Fetch and aggregate wind speed and direction data."""
    df = _wind_df_from_observation_data(speed_seriesid, direction_seriesid, observation_data)
    return _aggregate_to_daily(df)


def open_spreadsheet() -> gspread.Spreadsheet:
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")
    with open(creds_path, "r", encoding="utf-8") as f:
        creds = json.load(f)

    gc = gspread.service_account_from_dict(creds)

    spreadsheet_name = os.getenv("DHM_WIND_SHEET", "DHM_wind")
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
        ws = api_call_with_retry(sh.add_worksheet, title=worksheet_name, rows="5000", cols="10")

    existing_df = _normalize_existing_wind_data(
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
        print(f"[ERROR] Failed to fetch surface observation data: {e}")
        raise

    for station_key, config in WIND_STATIONS.items():
        speed_seriesid = config["speed_seriesid"]
        direction_seriesid = config["direction_seriesid"]
        worksheet_name = config["worksheet"]

        try:
            print(f"[INFO] Fetching wind data for {station_key} "
                  f"(speed={speed_seriesid}, direction={direction_seriesid})...")
            new_df = fetch_wind_daily(speed_seriesid, direction_seriesid, observation_data)

            if new_df.empty:
                print(f"[WARN] No data returned for {station_key}. Skipping.")
                continue

            print(f"[INFO] Updating worksheet '{worksheet_name}' with {len(new_df)} rows...")
            update_worksheet(sh, worksheet_name, new_df)
            print(f"[OK] Updated {worksheet_name}")

            time.sleep(write_delay)  # avoid quota limits

        except Exception as e:
            print(f"[ERROR] Failed to fetch/update {station_key}: {e}")


if __name__ == "__main__":
    main()
