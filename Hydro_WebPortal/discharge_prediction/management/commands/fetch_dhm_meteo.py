"""
Management command: fetch_dhm_meteo
=====================================
Fetches daily meteorological data (rainfall, temperature, relative humidity,
wind speed & direction) from the DHM portal and stores it in DHMMeteoRecord.

Data sources
------------
  Rainfall    → POST https://dhm.gov.np/hydrology/getRainfallWatchBySeriesId_single
  Temperature → POST https://dhm.gov.np/hydrology/getTemperatureWatchBySeriesId_single
                     (with fallback to surface-observation page)
  Humidity    → GET  https://dhm.gov.np/hydrology/surface-observation
  Wind        → GET  https://dhm.gov.np/hydrology/surface-observation
                     (two series IDs: speed + direction)

The surface-observation page is fetched ONCE per run and reused for all
climate-type stations (humidity + wind + temperature fallback).

Usage
-----
    python manage.py fetch_dhm_meteo
    python manage.py fetch_dhm_meteo --station Nuwakot
    python manage.py fetch_dhm_meteo --date 2026-05-01
    python manage.py fetch_dhm_meteo --from-date 2025-01-01
    python manage.py fetch_dhm_meteo --dry-run
"""

import json
import logging
import re
import time
from datetime import date, datetime, timedelta
from io import StringIO

import pandas as pd
import requests

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from discharge_prediction.models import DHMMeteoStation, DHMMeteoRecord, DischargeStation
from discharge_prediction.dhm_meteo_stations import DHM_METEO_STATIONS

logger = logging.getLogger(__name__)

# ── DHM endpoint constants ────────────────────────────────────────────────────
RAINFALL_URL = "https://dhm.gov.np/hydrology/getRainfallWatchBySeriesId_single"

TEMPERATURE_ENDPOINTS = [
    "https://dhm.gov.np/hydrology/getTemperatureWatchBySeriesId_single",
    "https://www.dhm.gov.np/hydrology/getTemperatureWatchBySeriesId_single",
    "https://dhm.gov.np/site/getTemperatureWatchBySeriesId_Single",
]

SURFACE_OBSERVATION_URL = "https://dhm.gov.np/hydrology/surface-observation"

DHM_HEADERS = {"User-Agent": "Mozilla/5.0"}


# ── Low-level fetch helpers ───────────────────────────────────────────────────

def _safe_float(value):
    """Convert a value to float, returning None for NaN/None/empty."""
    try:
        f = float(value)
        import math
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def fetch_rainfall_series(seriesid: str, target_date: date) -> pd.DataFrame:
    """
    POST to DHM rainfall endpoint.
    Returns DataFrame with columns: Date (datetime), Rainfall.
    """
    payload = {
        "date": str(target_date),
        "period": "3",
        "seriesid": seriesid,
    }
    resp = requests.post(RAINFALL_URL, data=payload, headers=DHM_HEADERS, timeout=30)
    resp.raise_for_status()
    body = resp.json()
    table_html = body.get("data", {}).get("table", "")
    if not table_html:
        raise ValueError(f"Empty table in DHM rainfall response for seriesid={seriesid}")
    df = pd.read_html(StringIO(table_html))[0]
    df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
    return df


def fetch_temperature_series(seriesid: str, observation_data: list | None = None) -> pd.DataFrame:
    """
    POST to DHM temperature endpoints (with fallback to surface-observation).
    Returns DataFrame with columns: Date (datetime), Min, Max, Avg (°C).
    """
    payload = {
        "date": str(date.today()),
        "period": "3",
        "seriesid": str(seriesid),
    }
    last_error = None
    for url in TEMPERATURE_ENDPOINTS:
        try:
            resp = requests.post(url, data=payload, headers=DHM_HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            table_html = (data.get("data") or {}).get("table", "")
            if not table_html:
                continue
            df = pd.read_html(StringIO(table_html))[0]
            # Normalise date column (may have various names)
            date_col = next((c for c in df.columns if str(c).strip().lower() in {"date", "date/time", "datetime"}), df.columns[0])
            df = df.rename(columns={date_col: "Date"})
            df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
            df = df.dropna(subset=["Date"])
            return _aggregate_temperature(df)
        except Exception as exc:
            last_error = f"{url}: {exc}"

    # Fallback to surface-observation data
    if observation_data is not None:
        df = _temperature_from_observation(seriesid, observation_data)
        return _aggregate_temperature(df)

    raise RuntimeError(f"All DHM temperature endpoints failed. Last: {last_error}")


def _aggregate_temperature(df: pd.DataFrame) -> pd.DataFrame:
    """Collapse any date+temperature column to daily min/max/avg."""
    temp_col = next(
        (c for c in df.columns if str(c).strip().lower() in {"temperature", "temp", "avg", "value"}),
        None
    )
    if temp_col is None:
        raise ValueError(f"No temperature column found. Columns: {list(df.columns)}")
    df = df.copy()
    df["Date"] = df["Date"].dt.normalize()
    df[temp_col] = pd.to_numeric(df[temp_col], errors="coerce")
    daily = (
        df.groupby("Date")[temp_col]
        .agg(Min="min", Max="max", Avg="mean")
        .reset_index()
    )
    daily["Avg"] = daily["Avg"].round(3)
    return daily


def _temperature_from_observation(seriesid: str, observation_data: list) -> pd.DataFrame:
    target = str(seriesid).strip()
    for station in observation_data:
        for obs in (station.get("observations") or []):
            if str(obs.get("series_id", "")).strip() != target:
                continue
            data_points = obs.get("data") or []
            rows = [{"Date": pt["datetime"], "Temperature": pt.get("value")} for pt in data_points if pt.get("datetime")]
            if not rows:
                raise ValueError(f"No data in observation_data for seriesid {target}")
            df = pd.DataFrame(rows)
            df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
            df["Temperature"] = pd.to_numeric(df["Temperature"], errors="coerce")
            return df.dropna(subset=["Date"])
    raise ValueError(f"seriesid {target} not found in surface-observation data")


def fetch_surface_observation_data() -> list:
    """
    GET the DHM surface-observation page and extract the embedded
    var observation_data = [...]; JavaScript variable.
    Returns the parsed list of station dicts.
    """
    resp = requests.get(SURFACE_OBSERVATION_URL, headers=DHM_HEADERS, timeout=45)
    resp.raise_for_status()
    match = re.search(r"var\s+observation_data\s*=\s*(\[.*?\]);", resp.text, re.DOTALL)
    if not match:
        raise ValueError("Could not find observation_data in surface-observation HTML")
    return json.loads(match.group(1))


def fetch_humidity_series(seriesid: str, observation_data: list) -> pd.DataFrame:
    """
    Extract humidity data from pre-fetched observation_data.
    Returns DataFrame with columns: Date (datetime), Min, Max, Avg (%).
    """
    target = str(seriesid).strip()
    for station in observation_data:
        for obs in (station.get("observations") or []):
            if str(obs.get("series_id", "")).strip() != target:
                continue
            data_points = obs.get("data") or []
            rows = [{"Date": pt["datetime"], "Humidity": pt.get("value")} for pt in data_points if pt.get("datetime")]
            if not rows:
                raise ValueError(f"No humidity data for seriesid {target}")
            df = pd.DataFrame(rows)
            df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
            df["Humidity"] = pd.to_numeric(df["Humidity"], errors="coerce")
            df = df.dropna(subset=["Date", "Humidity"])
            df["Date"] = df["Date"].dt.normalize()
            daily = df.groupby("Date")["Humidity"].agg(Min="min", Max="max", Avg="mean").reset_index()
            daily["Avg"] = daily["Avg"].round(3)
            return daily
    raise ValueError(f"seriesid {target} not found in surface-observation data")


def fetch_wind_series(speed_seriesid: str, dir_seriesid: str, observation_data: list) -> pd.DataFrame:
    """
    Extract wind speed + direction from pre-fetched observation_data.
    Returns DataFrame with columns: Date, Speed_Min, Speed_Max, Speed_Avg,
                                                Dir_Min, Dir_Max, Dir_Avg.
    """
    speed_target = str(speed_seriesid).strip()
    dir_target   = str(dir_seriesid).strip()
    speed_data   = {}
    dir_data     = {}

    for station in observation_data:
        for obs in (station.get("observations") or []):
            sid = str(obs.get("series_id", "")).strip()
            for pt in (obs.get("data") or []):
                dt = pt.get("datetime")
                val = pt.get("value")
                if dt is not None:
                    if sid == speed_target:
                        speed_data[dt] = val
                    elif sid == dir_target:
                        dir_data[dt] = val

    if not speed_data and not dir_data:
        raise ValueError(f"No wind data for speed={speed_seriesid} dir={dir_seriesid}")

    all_dates = sorted(set(speed_data) | set(dir_data))
    df = pd.DataFrame([
        {"Date": dt, "Wind_Speed": speed_data.get(dt), "Wind_Direction": dir_data.get(dt)}
        for dt in all_dates
    ])
    df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=True)
    df["Wind_Speed"] = pd.to_numeric(df["Wind_Speed"], errors="coerce")
    df["Wind_Direction"] = pd.to_numeric(df["Wind_Direction"], errors="coerce")
    df = df.dropna(subset=["Date"])
    df["Date"] = df["Date"].dt.normalize()

    daily = df.groupby("Date").agg(
        Speed_Min=("Wind_Speed", "min"),
        Speed_Max=("Wind_Speed", "max"),
        Speed_Avg=("Wind_Speed", "mean"),
        Dir_Min=("Wind_Direction", "min"),
        Dir_Max=("Wind_Direction", "max"),
        Dir_Avg=("Wind_Direction", "mean"),
    ).reset_index()
    daily["Speed_Avg"] = daily["Speed_Avg"].round(3)
    daily["Dir_Avg"]   = daily["Dir_Avg"].round(1)
    return daily


# ── Django management command ─────────────────────────────────────────────────

class Command(BaseCommand):
    help = (
        "Fetch daily meteorological data (rainfall, temperature, humidity, wind) "
        "from the DHM portal and store in DHMMeteoRecord."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--station",
            dest="station",
            default=None,
            help="Restrict to a single station name (key in DHM_METEO_STATIONS).",
        )
        parser.add_argument(
            "--date",
            dest="target_date",
            default=None,
            help="Reference date for the data window (YYYY-MM-DD). Defaults to today.",
        )
        parser.add_argument(
            "--from-date",
            dest="from_date",
            default=None,
            help="Backfill start date (YYYY-MM-DD). Iterates 7-day windows.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Fetch and parse without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        target_date = None
        from_date   = None

        if options["target_date"]:
            try:
                target_date = datetime.strptime(options["target_date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--date must be YYYY-MM-DD")

        if options["from_date"]:
            try:
                from_date = datetime.strptime(options["from_date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--from-date must be YYYY-MM-DD")

        # Build date windows (same logic as fetch_dhm_discharge)
        if from_date:
            end_date = target_date or date.today()
            if from_date > end_date:
                raise CommandError("--from-date must be earlier than --date / today")
            date_windows = []
            cursor = from_date
            while cursor <= end_date:
                date_windows.append(cursor)
                cursor += timedelta(days=7)
            if date_windows[-1] != end_date:
                date_windows.append(end_date)
            self.stdout.write(
                f"Backfill mode: {from_date} → {end_date} ({len(date_windows)} windows)"
            )
        else:
            date_windows = [target_date or date.today()]

        # Filter stations
        stations_to_process = DHM_METEO_STATIONS
        if options["station"]:
            key = options["station"]
            if key not in DHM_METEO_STATIONS:
                raise CommandError(
                    f"Station '{key}' not found. Available: {', '.join(DHM_METEO_STATIONS)}"
                )
            stations_to_process = {key: DHM_METEO_STATIONS[key]}

        # Fetch surface-observation page ONCE if any climate station is in scope
        needs_surface = any(
            cfg["variable_type"] == "climate"
            for cfg in stations_to_process.values()
        )
        observation_data = None
        if needs_surface:
            self.stdout.write("Fetching DHM surface-observation page (climate data)…")
            try:
                observation_data = fetch_surface_observation_data()
                self.stdout.write(self.style.SUCCESS("  [OK] surface-observation loaded"))
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  [ERROR] surface-observation failed: {exc}"))
                logger.error("surface-observation fetch failed: %s", exc)
                # Climate stations will fail gracefully below

        total_saved = total_skipped = total_errors = 0

        for station_name, cfg in stations_to_process.items():
            variable_type = cfg["variable_type"]
            self.stdout.write(f"\n>> {station_name} ({variable_type})")

            # ── Resolve or create DHMMeteoStation row ─────────────────────────
            if not dry_run:
                meteo_station_obj, created = DHMMeteoStation.objects.get_or_create(
                    name=station_name,
                    defaults={"variable_type": variable_type},
                )
                if created:
                    # Populate series IDs on first creation
                    meteo_station_obj.seriesid            = cfg.get("seriesid", "")
                    meteo_station_obj.humidity_seriesid   = cfg.get("humidity_seriesid", "")
                    meteo_station_obj.wind_speed_seriesid = cfg.get("wind_speed_seriesid", "")
                    meteo_station_obj.wind_dir_seriesid   = cfg.get("wind_dir_seriesid", "")
                    meteo_station_obj.save()
                    self.stdout.write(f"  Created DHMMeteoStation: {station_name}")

                # Link to hydro stations
                for sid in cfg.get("links_to", []):
                    try:
                        hydro = DischargeStation.objects.get(station_id=sid)
                        meteo_station_obj.hydro_stations.add(hydro)
                    except DischargeStation.DoesNotExist:
                        self.stderr.write(
                            self.style.WARNING(f"  [WARN] DischargeStation station_id='{sid}' not found")
                        )
            else:
                meteo_station_obj = None

            station_saved = 0

            # ── Rainfall stations ─────────────────────────────────────────────
            if variable_type == "rainfall":
                seriesid = cfg.get("seriesid", "")
                if not seriesid:
                    self.stderr.write(self.style.ERROR(f"  [ERROR] No seriesid for {station_name}"))
                    total_skipped += 1
                    continue

                for window_idx, win_date in enumerate(date_windows):
                    if window_idx > 0:
                        time.sleep(1)
                    try:
                        df = fetch_rainfall_series(seriesid, win_date)
                    except Exception as exc:
                        self.stderr.write(self.style.ERROR(f"  [ERROR] Rainfall fetch ({win_date}): {exc}"))
                        total_errors += 1
                        continue

                    for _, row in df.iterrows():
                        row_date = row["Date"].date()
                        # Rainfall column may be named 'Rainfall', 'Total', 'Average' etc.
                        rainfall_col = next(
                            (c for c in df.columns if str(c).lower() not in {"date", "s.n.", "sn", "station"}),
                            None
                        )
                        rain_val = _safe_float(row.get(rainfall_col)) if rainfall_col else None

                        if dry_run:
                            self.stdout.write(f"  [dry-run] {row_date}: rainfall={rain_val} mm")
                            station_saved += 1
                            continue

                        ts = timezone.make_aware(
                            datetime.combine(row_date, datetime.min.time())
                        )
                        try:
                            with transaction.atomic():
                                _, created = DHMMeteoRecord.objects.update_or_create(
                                    meteo_station=meteo_station_obj,
                                    timestamp=ts,
                                    defaults={
                                        "rainfall_mm": rain_val,
                                        "quality_flag": "good",
                                        "data_source": "dhm_scrape",
                                    },
                                )
                                station_saved += 1
                        except Exception as exc:
                            self.stderr.write(self.style.ERROR(f"  [ERROR] DB write {row_date}: {exc}"))
                            total_errors += 1

            # ── Climate stations (temperature + humidity + wind) ──────────────
            elif variable_type == "climate":
                if observation_data is None:
                    self.stderr.write(
                        self.style.ERROR(f"  [ERROR] No surface-observation data — skipping {station_name}")
                    )
                    total_skipped += 1
                    continue

                # Fetch each variable into a dict keyed by date
                temp_by_date = {}
                rh_by_date   = {}
                wind_by_date = {}

                # Temperature
                temp_seriesid = cfg.get("seriesid", "")
                if temp_seriesid:
                    try:
                        temp_df = fetch_temperature_series(temp_seriesid, observation_data)
                        for _, r in temp_df.iterrows():
                            temp_by_date[r["Date"].date() if hasattr(r["Date"], "date") else r["Date"]] = r
                    except Exception as exc:
                        self.stderr.write(self.style.WARNING(f"  [WARN] Temperature fetch failed: {exc}"))

                # Humidity
                hum_seriesid = cfg.get("humidity_seriesid", "")
                if hum_seriesid:
                    try:
                        rh_df = fetch_humidity_series(hum_seriesid, observation_data)
                        for _, r in rh_df.iterrows():
                            rh_by_date[r["Date"].date() if hasattr(r["Date"], "date") else r["Date"]] = r
                    except Exception as exc:
                        self.stderr.write(self.style.WARNING(f"  [WARN] Humidity fetch failed: {exc}"))

                # Wind
                ws_seriesid  = cfg.get("wind_speed_seriesid", "")
                wd_seriesid  = cfg.get("wind_dir_seriesid", "")
                if ws_seriesid and wd_seriesid:
                    try:
                        wind_df = fetch_wind_series(ws_seriesid, wd_seriesid, observation_data)
                        for _, r in wind_df.iterrows():
                            wind_by_date[r["Date"].date() if hasattr(r["Date"], "date") else r["Date"]] = r
                    except Exception as exc:
                        self.stderr.write(self.style.WARNING(f"  [WARN] Wind fetch failed: {exc}"))

                # Merge all dates
                all_dates = sorted(set(temp_by_date) | set(rh_by_date) | set(wind_by_date))
                if not all_dates:
                    self.stderr.write(self.style.WARNING(f"  [WARN] No data returned for {station_name}"))
                    total_skipped += 1
                    continue

                self.stdout.write(f"  {len(all_dates)} days of climate data")

                for row_date in all_dates:
                    t    = temp_by_date.get(row_date)
                    rh   = rh_by_date.get(row_date)
                    wind = wind_by_date.get(row_date)

                    if dry_run:
                        self.stdout.write(
                            f"  [dry-run] {row_date}: "
                            f"T_avg={_safe_float(t['Avg']) if t is not None else 'N/A'} °C  "
                            f"RH_avg={_safe_float(rh['Avg']) if rh is not None else 'N/A'} %  "
                            f"WS_avg={_safe_float(wind['Speed_Avg']) if wind is not None else 'N/A'} m/s"
                        )
                        station_saved += 1
                        continue

                    ts = timezone.make_aware(
                        datetime.combine(row_date, datetime.min.time())
                    )
                    defaults = {
                        "quality_flag": "good",
                        "data_source": "dhm_scrape",
                        "temp_avg_c": _safe_float(t["Avg"]) if t is not None else None,
                        "temp_max_c": _safe_float(t["Max"]) if t is not None else None,
                        "temp_min_c": _safe_float(t["Min"]) if t is not None else None,
                        "rh_avg":     _safe_float(rh["Avg"]) if rh is not None else None,
                        "rh_max":     _safe_float(rh["Max"]) if rh is not None else None,
                        "rh_min":     _safe_float(rh["Min"]) if rh is not None else None,
                        "wind_speed_avg_ms": _safe_float(wind["Speed_Avg"]) if wind is not None else None,
                        "wind_speed_max_ms": _safe_float(wind["Speed_Max"]) if wind is not None else None,
                        "wind_speed_min_ms": _safe_float(wind["Speed_Min"]) if wind is not None else None,
                        "wind_dir_avg_deg":  _safe_float(wind["Dir_Avg"])   if wind is not None else None,
                        "wind_dir_max_deg":  _safe_float(wind["Dir_Max"])   if wind is not None else None,
                        "wind_dir_min_deg":  _safe_float(wind["Dir_Min"])   if wind is not None else None,
                    }
                    try:
                        with transaction.atomic():
                            DHMMeteoRecord.objects.update_or_create(
                                meteo_station=meteo_station_obj,
                                timestamp=ts,
                                defaults=defaults,
                            )
                            station_saved += 1
                    except Exception as exc:
                        self.stderr.write(self.style.ERROR(f"  [ERROR] DB write {row_date}: {exc}"))
                        total_errors += 1

            total_saved += station_saved
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [OK] {station_name}: {station_saved} rows {'(dry-run)' if dry_run else 'saved'}"
                )
            )

        self.stdout.write("\n" + "─" * 50)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Total saved={total_saved}  skipped={total_skipped}  errors={total_errors}"
            )
        )
