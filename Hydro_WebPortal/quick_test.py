#!/usr/bin/env python3
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.prediction_utils import DischargePredictionEngine
from discharge_prediction.models import DischargeStation
from datetime import date

print("🚀 Starting monthly energy test...")

# Initialize the prediction engine
engine = DischargePredictionEngine(simulate_mode=True)

# Get a station
station = DischargeStation.objects.first()
if not station:
    print("❌ No stations found!")
    exit()

print(f"✅ Testing with station: {station.name}")

# Generate monthly forecast
print("📊 Generating monthly forecast...")
forecast = engine.predict_monthly_discharge(station, date(2025, 11, 1))
print(f"✅ Monthly forecast status: {forecast.status}")

# Get energy summary
print("📈 Getting energy summary...")
summary = engine.get_monthly_energy_summary(station, 2025, 11)
print(f"⚡ Total Monthly Energy: {summary['total_monthly_energy_mwh']:.2f} MWh")
print(f"📊 Average Daily Energy: {summary['average_daily_energy_mwh']:.2f} MWh/day")
print(f"🔢 Total Predictions: {summary['total_predictions']}")

print("🎉 Test completed successfully!")