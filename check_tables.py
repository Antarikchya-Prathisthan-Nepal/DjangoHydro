import django, os
os.environ['DJANGO_SETTINGS_MODULE'] = 'Hydro_WebPortal.settings_production'
django.setup()
from django.db import connection
c = connection.cursor()
c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename LIKE 'users_%' ORDER BY tablename")
print("=== users_* tables ===")
for r in c.fetchall(): print(" ", r[0])
for tbl in ['users_user','users_pendingregistration','users_emailverificationtoken','users_accessrequest','users_stationaccess']:
    c.execute(f"SELECT COUNT(*) FROM {tbl}")
    print(f"  {tbl}: {c.fetchone()[0]} rows")
