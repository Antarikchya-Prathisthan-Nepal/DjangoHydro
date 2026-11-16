"""
GST endpoint smoke test + device status check.
Run with: python test_gst_endpoint.py
"""
import os, sys, json, time, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
sys.path.insert(0, r'C:\Users\Dell\antar\DjangoHydro\Hydro_WebPortal')
django.setup()

from datetime import datetime, timezone
from django.test import RequestFactory
from django.conf import settings
from discharge_prediction.models import SensorReading, DischargeStation
from discharge_prediction.gst_views import gst_receive

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"

def section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

# Pre-test cleanup — remove any stale test rows
SensorReading.objects.filter(device_id='GST_TEST_DEVICE').delete()

# -----------------------------------------------------------------------
# 1. Settings & credentials loaded
# -----------------------------------------------------------------------
section("1. Settings / Credentials")
creds_ok = bool(settings.GST_USERNAME and settings.GST_PASSWORD)
print(f"  GST_USERNAME:           {settings.GST_USERNAME!r} {'✓' if settings.GST_USERNAME else '✗ MISSING'}")
print(f"  GST_PASSWORD:           {'***set***' if settings.GST_PASSWORD else '✗ MISSING'}")
print(f"  GST_SEA_LEVEL_X:        {settings.GST_SEA_LEVEL_X}")
print(f"  GST_SEA_LEVEL_CONSTANT: {settings.GST_SEA_LEVEL_CONSTANT}")
print(f"  GST_FILTER_THRESHOLD:   {settings.GST_FILTER_THRESHOLD} cm")
print(f"  GST_FILTER_INITIAL:     {settings.GST_FILTER_INITIAL_DEPTH} cm")
print(f"  {PASS if creds_ok else FAIL} Credentials loaded: {creds_ok}")

# -----------------------------------------------------------------------
# 2. Station exists
# -----------------------------------------------------------------------
section("2. Mailung Station (station_id='2')")
try:
    station = DischargeStation.objects.get(station_id='2')
    print(f"  Name:       {station.name}")
    print(f"  DB pk:      {station.pk}")
    print(f"  Station ID: {station.station_id}")
    print(f"  {PASS} Station found")
except DischargeStation.DoesNotExist:
    print(f"  {FAIL} DischargeStation station_id='2' (Mailung) not found!")
    station = None

# -----------------------------------------------------------------------
# 3. SensorReading table stats
# -----------------------------------------------------------------------
section("3. SensorReading Table Status")
total = SensorReading.objects.count()
mailung_total = SensorReading.objects.filter(station__station_id='2').count() if station else 0
raw_count = SensorReading.objects.filter(station__station_id='2', processing_status='raw').count() if station else 0
calibrated_count = SensorReading.objects.filter(station__station_id='2', processing_status='calibrated').count() if station else 0
latest = SensorReading.objects.filter(station__station_id='2').order_by('-timestamp').first() if station else None
print(f"  Total rows (all stations): {total}")
print(f"  Mailung total:             {mailung_total}")
print(f"  Mailung raw:               {raw_count}")
print(f"  Mailung calibrated:        {calibrated_count}")
if latest:
    print(f"  Latest timestamp:          {latest.timestamp}")
    print(f"  Latest water_depth (cm):   {latest.water_depth}")
    print(f"  Latest WSE (cm):           {latest.water_surface_elevation}")
    print(f"  Latest discharge_depth(m): {latest.discharge_depth}")
else:
    print(f"  No readings yet (table empty — device has not POSTed to Django endpoint)")
print(f"  {INFO} Device is still sending to legacy PHP server (not yet reconfigured)")

# -----------------------------------------------------------------------
# 4. Endpoint test — valid payload
# -----------------------------------------------------------------------
section("4. Endpoint Test — Valid Payload")
factory = RequestFactory()
payload = {
    "GST_data": {
        "credentials": {
            "username": settings.GST_USERNAME,
            "password": settings.GST_PASSWORD,
        },
        "station_id": {
            "id": "GST_TEST_DEVICE",
            "location": {"lat": 27.6853, "lon": 85.5234},
            "timestamp": {"date": datetime.now(tz=timezone.utc).strftime("%d/%m/%Y"), "time": datetime.now(tz=timezone.utc).strftime("%H:%M:%S"), "day": "Wednesday"},
            "electrical_params": {"sol_current": 1.35, "load_current": 0.72},
        },
        "status": 1,
        "wifi_strength": -68,
        "station_data": [{
            "ip_address": "192.168.1.42",
            "sensors_data": {
                "temp": 28.4,
                "pressure": 1012.5,
                "humidity": 74.2,
                "depth": 268.0,         # cm — within ±5 of initial 265 → should pass filter
                "air_quality": 43.0,
            },
        }],
    }
}

before_count = SensorReading.objects.filter(station__station_id='2').count() if station else 0
req = factory.post(
    '/discharge-prediction/api/gst/receive/',
    data=json.dumps(payload),
    content_type='application/json',
)
resp = gst_receive(req)
after_count = SensorReading.objects.filter(station__station_id='2').count() if station else 0
resp_data = json.loads(resp.content)

print(f"  HTTP status:        {resp.status_code}")
print(f"  Response:           {json.dumps(resp_data, indent=4)}")
print(f"  Rows before:        {before_count}")
print(f"  Rows after:         {after_count}")
row_saved = after_count > before_count
print(f"  {PASS if row_saved else FAIL} Row saved to database: {row_saved}")
if row_saved:
    r = SensorReading.objects.filter(station__station_id='2').order_by('-created_at').first()
    print(f"  Saved processing_status:  {r.processing_status}")
    print(f"  Saved water_depth (cm):   {r.water_depth}")
    print(f"  Saved WSE (cm):           {r.water_surface_elevation}")
    print(f"  Saved discharge_depth (m):{r.discharge_depth}")

# -----------------------------------------------------------------------
# 5. Endpoint test — invalid credentials
# -----------------------------------------------------------------------
section("5. Endpoint Test — Wrong Credentials")
bad_payload = json.loads(json.dumps(payload))
bad_payload["GST_data"]["credentials"]["password"] = "wrong_password"
req2 = factory.post(
    '/discharge-prediction/api/gst/receive/',
    data=json.dumps(bad_payload),
    content_type='application/json',
)
resp2 = gst_receive(req2)
resp2_data = json.loads(resp2.content)
auth_rejected = resp2.status_code == 401
print(f"  HTTP status:  {resp2.status_code} (expected 401)")
print(f"  Response:     {resp2_data}")
print(f"  {PASS if auth_rejected else FAIL} Bad credentials rejected: {auth_rejected}")

# -----------------------------------------------------------------------
# 6. Endpoint test — depth out of threshold (should be rejected by filter)
# -----------------------------------------------------------------------
section("6. Endpoint Test — Depth Spike (exceeds ±5cm threshold)")
spike_payload = json.loads(json.dumps(payload))
time.sleep(1)  # ensure different second
spike_payload["GST_data"]["station_id"]["timestamp"]["time"] = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
spike_payload["GST_data"]["station_data"][0]["sensors_data"]["depth"] = 400.0  # 400cm vs prev ~271cm → spike
req3 = factory.post(
    '/discharge-prediction/api/gst/receive/',
    data=json.dumps(spike_payload),
    content_type='application/json',
)
resp3 = gst_receive(req3)
resp3_data = json.loads(resp3.content)
spike_rejected = not resp3_data.get("filtered", True)
print(f"  HTTP status:         {resp3.status_code}")
print(f"  filtered:            {resp3_data.get('filtered')}")
print(f"  reason:              {resp3_data.get('reason')}")
print(f"  depth_difference_cm: {resp3_data.get('depth_difference_cm')}")
print(f"  {PASS if spike_rejected else FAIL} Spike rejected by filter: {spike_rejected}")

# -----------------------------------------------------------------------
# 7. Sea-level formula verification
# -----------------------------------------------------------------------
section("7. Sea-Level Formula Verification")
x = settings.GST_SEA_LEVEL_X
c = settings.GST_SEA_LEVEL_CONSTANT
test_depth = 268.0
expected_wse = round(c - (x - test_depth), 2)
print(f"  Formula:  {c} - ({x} - {test_depth}) = {expected_wse} cm")
print(f"  In metres: {round(expected_wse/100, 4)} m")
# verify against saved reading
if row_saved:
    saved_wse = SensorReading.objects.filter(station__station_id='2', water_surface_elevation__isnull=False).order_by('-created_at').first()
    if saved_wse:
        match = abs(saved_wse.water_surface_elevation - expected_wse) < 0.01
        print(f"  DB stored WSE: {saved_wse.water_surface_elevation} cm")
        print(f"  {PASS if match else FAIL} WSE formula correct: {match}")

print(f"\n{'='*60}")
print("  SUMMARY")
print('='*60)
if station:
    print(f"  {PASS} Mailung station found in DB")
print(f"  {PASS if creds_ok else FAIL} GST credentials loaded from .env")
print(f"  {PASS if row_saved else FAIL} Valid payload accepted & stored")
print(f"  {PASS if auth_rejected else FAIL} Invalid credentials rejected (401)")
print(f"  {PASS if spike_rejected else FAIL} Depth spike rejected by noise filter")
print(f"  {INFO} Device status: NOT YET connected to Django (still on PHP server)")
print(f"  {INFO} Device URL to configure: https://hydro.antarikchya.org.np/discharge-prediction/api/gst/receive/")
print()

# Cleanup test rows
SensorReading.objects.filter(device_id='GST_TEST_DEVICE').delete()
print("  [Cleanup] Test rows removed from DB")
