"""
Quick smoke-test for the two prediction pipelines.
- Lower Likhu (station_id=1): era5_car  -> should return (90, 7) array
- Mailung                    : era5_only -> should return (90, 6) array
"""
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'Hydro_WebPortal.settings'
django.setup()

from datetime import date, timedelta
from discharge_prediction.models import DischargeStation, ERA5Data
from discharge_prediction.era5_utils import ERA5Downloader

downloader = ERA5Downloader()

for station_id in [1]:          # add Mailung station_id when ready
    station = DischargeStation.objects.get(station_id=station_id)
    print(f"\n{'='*60}")
    print(f"Station : {station.name}  (pipeline={station.prediction_pipeline})")
    print(f"Rating curve configured: {station.has_rating_curve}")

    # Find latest 90 days of available ERA5 data
    latest_era5 = ERA5Data.objects.filter(
        station=station, is_complete=True,
        processing_status__in=['processed', 'validated']
    ).order_by('-date').first()

    if not latest_era5:
        print("  No ERA5 data found — skipping.")
        continue

    end_date   = latest_era5.date
    start_date = end_date - timedelta(days=89)
    print(f"ERA5 window: {start_date} -> {end_date}")

    try:
        seq = downloader.preprocess_for_model_inference(station, start_date, end_date)
        print(f"Sequence shape : {seq.shape}  (expected 90 x {'7' if station.prediction_pipeline=='era5_car' else '6'})")
        print(f"Min / Max      : {seq.min():.4f} / {seq.max():.4f}")
        print(f"Last row       : {[round(v,4) for v in seq[-1].tolist()]}")
        # Last column = Q2_car for era5_car pipeline
        if station.prediction_pipeline == 'era5_car':
            print(f"Q2_car values (last 5 days): {[round(v,4) for v in seq[-5:, 6].tolist()]}")
    except Exception as e:
        print(f"ERROR: {e}")
