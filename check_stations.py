import django, os, sys
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
sys.path.insert(0, r'C:\Users\Dell\antar\DjangoHydro\Hydro_WebPortal')
django.setup()

from discharge_prediction.models import DischargeStation

print("=== DischargeStation sensor API config ===")
for s in DischargeStation.objects.all().values('name', 'station_id', 'sensor_api_endpoint', 'gst_depth_api_field'):
    ep = s['sensor_api_endpoint'] or '[NOT SET]'
    gf = s['gst_depth_api_field'] or '[NOT SET]'
    print("  {} ({})".format(s['name'], s['station_id']))
    print("    sensor_api_endpoint: {}".format(ep))
    print("    gst_depth_api_field: {}".format(gf))
    print()
