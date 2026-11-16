from discharge_prediction.models import SensorReading, DischargeStation
from django.db.models import Count, Min, Max

print("=== SensorReading table ===")
print("Total rows:", SensorReading.objects.count())

print("\n=== Per-station breakdown ===")
qs = SensorReading.objects.values(
    'station__name', 'station__station_id'
).annotate(
    count=Count('id'),
    earliest=Min('timestamp'),
    latest=Max('timestamp')
).order_by('-count')

if qs:
    for r in qs:
        print("  {} ({}): {} readings | {} to {}".format(
            r['station__name'], r['station__station_id'],
            r['count'], r['earliest'], r['latest']
        ))
else:
    print("  No readings in database")

print("\n=== Latest reading ===")
r = SensorReading.objects.select_related('station').order_by('-timestamp').first()
if r:
    print("  Station:           {}".format(r.station.name))
    print("  Timestamp:         {}".format(r.timestamp))
    print("  Temperature:       {} C".format(r.temperature))
    print("  Humidity:          {} %".format(r.humidity))
    print("  Pressure:          {} hPa".format(r.pressure))
    print("  Water depth:       {} m".format(r.water_depth))
    print("  Discharge depth:   {} m".format(r.discharge_depth))
    print("  WiFi strength:     {} dBm".format(r.wifi_strength))
    print("  Device status:     {}".format(r.device_status))
    print("  Data quality:      {}".format(r.data_quality))
    print("  Processing status: {}".format(r.processing_status))
else:
    print("  No readings found")

print("\n=== DischargeStation sensor API config ===")
for s in DischargeStation.objects.all().values('name', 'station_id', 'sensor_api_endpoint', 'gst_depth_api_field'):
    ep = s['sensor_api_endpoint'] or '[NOT SET]'
    gf = s['gst_depth_api_field'] or '[NOT SET]'
    print("  {} ({}):".format(s['name'], s['station_id']))
    print("    sensor_api_endpoint: {}".format(ep))
    print("    gst_depth_api_field: {}".format(gf))
