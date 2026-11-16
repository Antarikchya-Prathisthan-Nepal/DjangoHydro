import csv
import os
import sys
import django

sys.path.insert(0, r'C:\Users\Dell\antar\DjangoHydro\Hydro_WebPortal')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import ERA5Data, DischargeStation

s = DischargeStation.objects.get(station_id=2)
qs = ERA5Data.objects.filter(station=s, date__year=2026).order_by('date').values(
    'date','temperature_2m','u_component_10m','v_component_10m',
    'total_precipitation','specific_humidity','soil_moisture','is_complete'
)

out = r'C:\Users\Dell\antar\DjangoHydro\mailung_era5_2026.csv'
with open(out, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[
        'date','temperature_2m','u_component_10m','v_component_10m',
        'total_precipitation','specific_humidity','soil_moisture','is_complete'
    ])
    writer.writeheader()
    writer.writerows(qs)

count = qs.count()
first = qs.first()
last = qs.last()
print(f'Exported {count} rows to {out}')
print(f'Range: {first["date"]} to {last["date"]}')
