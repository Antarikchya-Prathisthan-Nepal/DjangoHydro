"""
Run discharge predictions for Lower Likhu using the era5_car pipeline.

With ERA5 data Jan 1 – Apr 13 2026 and a 45-day lead time, target dates
of ~May 6 – May 28 2026 have sufficient input windows.
"""
import os, sys, django, warnings
warnings.filterwarnings('ignore')
os.environ['DJANGO_SETTINGS_MODULE'] = 'Hydro_WebPortal.settings'
django.setup()

from datetime import date, timedelta
from discharge_prediction.models import DischargeStation, DischargePrediction
from discharge_prediction.prediction_utils import DischargePredictionEngine

# ── Station ────────────────────────────────────────────────────────────────────
station = DischargeStation.objects.get(station_id=1)
print(f"Station  : {station.name}")
print(f"Pipeline : {station.prediction_pipeline}")
print(f"Model    : {station.model_file_path}")
print()

# ── Engine ─────────────────────────────────────────────────────────────────────
engine = DischargePredictionEngine(
    model_path=station.model_file_path,
    normalization_scaler_path=station.scaler_file_path,
    denormalization_scaler_path=station.denormalization_scaler_path,
)
engine.load_model()
print(f"Model loaded: {engine.model_name}  n_features={engine.n_features}")
print()

# ── Date range to predict ──────────────────────────────────────────────────────
# ERA5 available Aug 17 2025 → Apr 13 2026
# 90-day input window + 45-day lead → earliest target = Aug 17 + 134 = Dec 29 2025
# Latest target = Apr 13 2026 + 45 days = May 28 2026
era5_last_date = date(2026, 4, 13)
predict_start  = date(2025, 12, 29)  # first date with full 90-day ERA5 window
predict_end    = era5_last_date + timedelta(days=45)   # = May 28 2026

print(f"Predicting: {predict_start}  →  {predict_end}")
print("-" * 60)

results = []
current = predict_start
while current <= predict_end:
    q, ci, ok = engine.predict_single_day(station, current)
    if ok:
        lo, hi = ci
        results.append((current, q, lo, hi))
        print(f"  {current}  Q={q:7.3f} m³/s  CI=[{lo:.3f}, {hi:.3f}]")
    else:
        print(f"  {current}  SKIPPED (insufficient data)")
    current += timedelta(days=1)

print()
print("=" * 60)
print(f"Successful predictions: {len(results)}/{(predict_end - predict_start).days + 1}")
if results:
    qs = [r[1] for r in results]
    print(f"  Q range  : {min(qs):.3f} – {max(qs):.3f} m³/s")
    print(f"  Q mean   : {sum(qs)/len(qs):.3f} m³/s")
    print(f"  Period   : {results[0][0]}  →  {results[-1][0]}")
print()

# ── Verify in DB ───────────────────────────────────────────────────────────────
saved = DischargePrediction.objects.filter(station=station).order_by('target_date')
print(f"DischargePrediction records saved: {saved.count()}")
if saved.exists():
    first, last = saved.first(), saved.last()
    print(f"  Date range: {first.target_date}  →  {last.target_date}")
