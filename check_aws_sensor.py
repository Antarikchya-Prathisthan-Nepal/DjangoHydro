import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'Hydro_WebPortal.settings_production'
import django
django.setup()

from discharge_prediction.models import SensorReading, DischargeStation

station = DischargeStation.objects.get(station_id='2')
total = SensorReading.objects.filter(station=station).count()
calibrated = SensorReading.objects.filter(station=station, processing_status='calibrated').count()
raw_only = SensorReading.objects.filter(station=station, processing_status='raw').count()
latest = SensorReading.objects.filter(station=station).order_by('-timestamp').first()

print("=== SensorReading table (AWS) ===")
print("Station:               ", station.name)
print("Total rows:            ", total)
print("Raw (rejected by filter):", raw_only)
print("Calibrated (accepted): ", calibrated)
if latest:
    print("Latest timestamp:      ", latest.timestamp)
    print("Latest water_depth cm: ", latest.water_depth)
    print("Latest WSE cm:         ", latest.water_surface_elevation)
    print("Latest discharge_depth:", latest.discharge_depth, "m")
    print("Latest device_id:      ", latest.device_id)
else:
    print("No readings yet from real device")
    print("")
    print("=== How data will populate ===")
    print("1. Device POSTs JSON to: https://hydro.antarikchya.org.np/discharge-prediction/api/gst/receive/")
    print("2. Django validates credentials -> saves row (processing_status=raw)")
    print("3. If |depth - prev_depth| <= 5cm -> updates to processing_status=calibrated + computes WSE")
    print("4. Once 5+ calibrated rows exist -> sets discharge_depth (rolling median in metres)")
