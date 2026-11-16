import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env.production before Django setup
# ---------------------------------------------------------------------------

def load_env_file(path):
    """Load KEY=VALUE lines from a file into os.environ (non-destructive)."""
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# Resolve .env.production relative to this script's location
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / '.env.production'
load_env_file(str(ENV_FILE))

# ---------------------------------------------------------------------------
# Django setup
# ---------------------------------------------------------------------------

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings_production')

import django
django.setup()

# ---------------------------------------------------------------------------
# Imports (after Django setup)
# ---------------------------------------------------------------------------

import schedule
import time
import subprocess
from datetime import date, timedelta
from django.utils import timezone

from discharge_prediction.models import DischargeStation, ERA5Data
from discharge_prediction.era5_utils import ERA5Downloader


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def daily_era5_download():
    downloader = ERA5Downloader()
    delay_days = downloader.era5_delay_days
    today = date.today()
    target_date = today - timedelta(days=delay_days)
    stations = DischargeStation.objects.all()
    variables = [
        '2m_temperature',
        'total_precipitation',
        '10m_u_component_of_wind',
        '10m_v_component_of_wind',
        'specific_humidity',
        'volumetric_soil_water_layer_1',
    ]
    for station in stations:
        existing_data = ERA5Data.objects.filter(station=station, date=target_date).exists()
        if existing_data:
            print(f"[INFO] Data for {station.name} on {target_date} already exists, skipping.")
            continue
        try:
            print(f"[INFO] Downloading ERA5 data for {station.name} on {target_date}")
            era5_data = downloader.download_for_station(
                station=station,
                start_date=target_date,
                end_date=target_date,
                variables=variables
            )
            print(f"[DEBUG] Raw ERA5 data: {era5_data}")
            # Map and store as in management command
            if era5_data and all(isinstance(v, (int, float)) for v in era5_data.values()):
                mapped_data = {
                    '2m_temperature': era5_data.get('temperature_2m', 0.0),
                    'total_precipitation': era5_data.get('total_precipitation', 0.0),
                    '10m_u_component_of_wind': era5_data.get('u_component_10m', 0.0),
                    '10m_v_component_of_wind': era5_data.get('v_component_10m', 0.0),
                    'specific_humidity': era5_data.get('specific_humidity', 0.0),
                    'soil_moisture': era5_data.get('soil_moisture', None),
                }
            elif era5_data and target_date.strftime('%Y-%m-%d') in era5_data:
                day_vars = era5_data[target_date.strftime('%Y-%m-%d')]
                mapped_data = {
                    '2m_temperature': day_vars.get('temperature_2m', 0.0),
                    'total_precipitation': day_vars.get('total_precipitation', 0.0),
                    '10m_u_component_of_wind': day_vars.get('u_component_10m', 0.0),
                    '10m_v_component_of_wind': day_vars.get('v_component_10m', 0.0),
                    'specific_humidity': day_vars.get('specific_humidity', 0.0),
                    'soil_moisture': day_vars.get('soil_moisture', None),
                }
            else:
                print(f"[WARN] No valid data for {station.name} on {target_date}, skipping.")
                continue
            # Store in DB
            from django.db import transaction
            with transaction.atomic():
                era5_record, created = ERA5Data.objects.update_or_create(
                    station=station,
                    date=target_date,
                    defaults={
                        'temperature_2m': mapped_data.get('2m_temperature', 0.0),
                        'total_precipitation': mapped_data.get('total_precipitation', 0.0),
                        'u_component_10m': mapped_data.get('10m_u_component_of_wind', 0.0),
                        'v_component_10m': mapped_data.get('10m_v_component_of_wind', 0.0),
                        'specific_humidity': mapped_data.get('specific_humidity', 0.0),
                        'soil_moisture': mapped_data.get('soil_moisture', None),
                        'download_timestamp': timezone.now(),
                        'data_source': 'ERA5_CDS',
                        'is_complete': True,
                        'processing_status': 'processed'
                    }
                )
                print(f"[INFO] Stored ERA5 data for {station.name} on {target_date}")
        except Exception as e:
            print(f"[ERROR] Failed to download/store ERA5 data for {station.name} on {target_date}: {e}")

def daily_dhm_fetch():
    """Fetch DHM discharge data and store directly in DischargeRecord table."""
    from django.core.management import call_command
    print("[INFO] Starting DHM daily discharge fetch...")
    try:
        call_command("fetch_dhm_discharge")
        print("[INFO] DHM discharge fetch complete.")
    except Exception as e:
        print(f"[ERROR] DHM discharge fetch failed: {e}")


def fetch_dhm_meteo_task():
    """Fetch latest DHM meteorological data (rainfall, temperature, humidity, wind)."""
    from django.core.management import call_command
    print("[INFO] Starting DHM meteo fetch...")
    try:
        call_command("fetch_dhm_meteo")
        print("[INFO] DHM meteo fetch complete.")
    except Exception as e:
        print(f"[ERROR] DHM meteo fetch failed: {e}")


def run_daily_pipeline():
    try:
        _run_daily_pipeline()
    except Exception as e:
        print(f"[ERROR] Pipeline failed with unhandled exception: {e}")
        import traceback
        traceback.print_exc()

def _run_daily_pipeline():
    python_exe = sys.executable
    print("[INFO] Starting daily ERA5 data download...")
    daily_era5_download()
    print("[INFO] ERA5 data download complete. Starting prediction sequence...")

    autom_script = SCRIPT_DIR / 'automate_sequences_and_predictions.py'
    if autom_script.exists():
        try:
            result = subprocess.run([python_exe, str(autom_script)])
            if result.returncode != 0:
                print(f"[WARN] Prediction script exited with code {result.returncode}, continuing...")
        except Exception as e:
            print(f"[ERROR] Prediction script failed: {e}, continuing...")
    else:
        print(f"[WARN] Prediction script not found at {autom_script}, skipping prediction step.")

    print("[INFO] Prediction sequence complete. Starting monthly forecast aggregation...")
    monthly_script = SCRIPT_DIR / 'generate_monthly_forecasts_for_server.py'
    if monthly_script.exists():
        try:
            result = subprocess.run([python_exe, str(monthly_script)])
            if result.returncode != 0:
                print(f"[WARN] Monthly forecast script exited with code {result.returncode}, continuing...")
        except Exception as e:
            print(f"[ERROR] Monthly forecast script failed: {e}, continuing...")
    else:
        print(f"[WARN] Monthly forecast script not found at {monthly_script}, skipping monthly aggregation.")

    print("[INFO] Monthly forecast aggregation complete.")
    daily_dhm_fetch()


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

schedule.every().day.at("04:15").do(run_daily_pipeline)   # 10:00 AM NPT (UTC+5:45)
schedule.every(5).hours.do(fetch_dhm_meteo_task)           # DHM meteo every 5 hours

if __name__ == "__main__":
    print("[INFO] Starting full daily pipeline scheduler...")
    print("[INFO] Running initial pipeline execution...")
    run_daily_pipeline()
    print("[INFO] Initial pipeline execution complete.")

    print("[INFO] Running initial DHM meteo fetch...")
    fetch_dhm_meteo_task()
    print("[INFO] Initial DHM meteo fetch complete.")

    print("[INFO] Scheduler active — daily pipeline at 04:15 UTC, DHM meteo every 5 hours.")
    while True:
        schedule.run_pending()
        time.sleep(60)
