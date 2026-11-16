import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'Hydro_WebPortal.settings_production'
django.setup()

from discharge_prediction.models import SensorReading, DischargeStation
from django.db import connection

# Total count
total = SensorReading.objects.count()
print(f"Total SensorReading rows: {total}")

# Per station breakdown
print("\n--- Per Station ---")
from django.db.models import Count, Min, Max
qs = SensorReading.objects.values('station__name', 'station__station_id').annotate(
    count=Count('id'),
    earliest=Min('timestamp'),
    latest=Max('timestamp')
).order_by('-count')
for r in qs:
    print(f"  {r['station__name']} ({r['station__station_id']}): {r['count']} rows | {r['earliest']} → {r['latest']}")

if total == 0:
    print("\nNo sensor readings found.")

# Check which stations have sensor_api_endpoint configured
print("\n--- Stations with sensor_api_endpoint ---")
stations = DischargeStation.objects.all().values('name', 'station_id', 'sensor_api_endpoint', 'gst_depth_api_field')
for s in stations:
    ep = s['sensor_api_endpoint'] or '(not set)'
    field = s['gst_depth_api_field'] or '(not set)'
    print(f"  {s['name']} ({s['station_id']}): endpoint={ep} | depth_field={field}")

# Sample latest reading if exists
if total > 0:
    print("\n--- Latest Reading ---")
    r = SensorReading.objects.order_by('-timestamp').first()
    print(f"  Station:           {r.station.name}")
    print(f"  Timestamp:         {r.timestamp}")
    print(f"  Temperature:       {r.temperature}")
    print(f"  Humidity:          {r.humidity}")
    print(f"  Pressure:          {r.pressure}")
    print(f"  Water Depth:       {r.water_depth}")
    print(f"  Discharge Depth:   {r.discharge_depth}")
    print(f"  WiFi Strength:     {r.wifi_strength}")
    print(f"  Device Status:     {r.device_status}")
    print(f"  Data Quality:      {r.data_quality}")
    print(f"  Processing Status: {r.processing_status}")
