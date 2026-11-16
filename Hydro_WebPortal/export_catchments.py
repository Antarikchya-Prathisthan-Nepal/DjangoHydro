import os, django, json
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Hydro_WebPortal.settings")
django.setup()

from discharge_prediction.models import DischargeStation

for s in DischargeStation.objects.all():
    if not s.catchment_polygon:
        continue
    safe_name = s.name.replace(" ", "_")
    fname = f"catchment_{s.station_id}_{safe_name}.geojson"
    feature = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": json.loads(s.catchment_polygon.geojson),
            "properties": {
                "station": s.name,
                "station_id": s.station_id,
                "gauge_lat": s.latitude,
                "gauge_lon": s.longitude,
                "extent_W": s.catchment_polygon.extent[0],
                "extent_S": s.catchment_polygon.extent[1],
                "extent_E": s.catchment_polygon.extent[2],
                "extent_N": s.catchment_polygon.extent[3],
            }
        }]
    }
    with open(fname, "w") as f:
        json.dump(feature, f, indent=2)
    print(f"Exported: {fname}")
    print(f"  Extent: W={s.catchment_polygon.extent[0]:.4f}  S={s.catchment_polygon.extent[1]:.4f}  "
          f"E={s.catchment_polygon.extent[2]:.4f}  N={s.catchment_polygon.extent[3]:.4f}")
    w, sb, e, n = s.catchment_polygon.extent
    area_km2 = (e - w) * (n - sb) * 111 * 111
    print(f"  Bounding-box area: ~{area_km2:.0f} km²")
    print(f"  Gauge point: lat={s.latitude}  lon={s.longitude}")
    print(f"  Gauge inside polygon: {s.catchment_polygon.contains(s.location)}")
    print()
