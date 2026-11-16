# DischargeStation Model Update Summary

## Overview
Updated the `DischargeStation` model to support:
1. **Catchment Area as GeoJSON Polygon** - Replaced numeric `catchment_area` field with `catchment_polygon` MultiPolygonField
2. **Ground Station Sensor Integration** - Added `sensor_api_endpoint` field for API-based sensor data fetching

---

## 🔄 Changes Made

### 1. Database Model Changes (`models.py`)

#### **Removed:**
- `catchment_area` (FloatField) - Numeric area in km²

#### **Added:**
```python
# Catchment Area Geometry (GeoJSON)
catchment_polygon = gis_models.MultiPolygonField(
    help_text="Upstream catchment area polygon geometry (GeoJSON)",
    null=True, blank=True,
    srid=4326  # WGS84 coordinate system
)

# Ground Station Sensor API Integration
sensor_api_endpoint = models.URLField(
    max_length=500,
    help_text="API endpoint URL for fetching ground station sensor data",
    blank=True, null=True
)
```

---

### 2. New Model Properties & Methods

#### **Catchment Polygon Methods:**

##### `catchment_area_km2` (Property)
Automatically calculates area in km² from the polygon geometry.
```python
station = DischargeStation.objects.get(station_id='STATION_01')
area = station.catchment_area_km2  # Returns: 1234.56 (km²)
```

##### `set_catchment_from_geojson(geojson_data)`
Import catchment area from GeoJSON data (string, dict, or GEOSGeometry).
```python
# From GeoJSON dict
geojson_dict = {
    "type": "Polygon",
    "coordinates": [[[lon1, lat1], [lon2, lat2], ...]]
}
station.set_catchment_from_geojson(geojson_dict)

# From GeoJSON string
station.set_catchment_from_geojson('{"type": "Polygon", ...}')
```

##### `get_catchment_geojson()`
Export catchment polygon as GeoJSON dict.
```python
geojson = station.get_catchment_geojson()
# Returns: {"type": "MultiPolygon", "coordinates": [...]}
```

##### `get_catchment_info()`
Get comprehensive catchment area information.
```python
info = station.get_catchment_info()
# Returns:
# {
#     'has_polygon': True,
#     'area_km2': 1234.56,
#     'num_polygons': 1,
#     'bounds': {
#         'north': 28.5,
#         'south': 27.5,
#         'east': 86.0,
#         'west': 85.0
#     },
#     'centroid': {
#         'latitude': 28.0,
#         'longitude': 85.5
#     }
# }
```

#### **Sensor Integration Methods:**

##### `get_latest_sensor_reading()`
Get the most recent sensor reading from the ground station.
```python
latest_reading = station.get_latest_sensor_reading()
# Returns: SensorReading object or None
```

##### `get_sensor_readings(hours=24)`
Get recent sensor readings from the last N hours.
```python
# Get readings from last 48 hours
readings = station.get_sensor_readings(hours=48)
# Returns: QuerySet of SensorReading objects
```

##### `fetch_sensor_data_from_api()`
Fetch latest sensor data from the configured API endpoint.
```python
result = station.fetch_sensor_data_from_api()
# Returns:
# {
#     'success': True,
#     'data': {...},  # Raw API response
#     'fetched_at': '2026-02-17T12:30:00Z'
# }
# OR
# {
#     'success': False,
#     'error': 'Error message',
#     'endpoint': 'https://api.example.com/sensor'
# }
```

---

### 3. Admin Interface Updates (`admin.py`)

#### **New List Display Column:**
- `catchment_area_display` - Shows calculated area in km² with color coding

#### **New Readonly Fields:**
- `catchment_area_display` - Calculated area display
- `catchment_info_display` - Detailed catchment polygon information

#### **Updated Fieldsets:**
```python
('Catchment Area (GeoJSON)', {
    'fields': ('catchment_polygon', 'catchment_area_display', 'catchment_info_display'),
    'description': 'Upload or draw the catchment area polygon. The area in km² will be automatically calculated from the geometry.'
}),

('Ground Station Sensor Integration', {
    'fields': ('sensor_api_endpoint',),
    'description': 'Configure the API endpoint URL for fetching real-time sensor data from the ground station.'
})
```

#### **Display Methods:**
- **catchment_area_display** - Shows area with green color if polygon exists
- **catchment_info_display** - Shows detailed info (area, bounds, centroid, number of polygons)

---

## 🚀 How to Use

### Step 1: Apply the Migration
```bash
cd Hydro_WebPortal
python manage.py migrate discharge_prediction
```

### Step 2: Update Existing Stations

#### **Option A: Via Django Admin**
1. Go to Django Admin → Discharge Stations
2. Edit a station
3. In the "Catchment Area (GeoJSON)" section:
   - Use the map widget to draw the catchment polygon
   - OR upload a GeoJSON file
4. The area in km² will be automatically calculated and displayed

#### **Option B: Via Django Shell**
```python
from discharge_prediction.models import DischargeStation
import json

# Load station
station = DischargeStation.objects.get(station_id='STATION_01')

# Set catchment from GeoJSON file
with open('catchment_area.geojson', 'r') as f:
    geojson_data = json.load(f)
    station.set_catchment_from_geojson(geojson_data)
    station.save()

# Verify
print(f"Catchment area: {station.catchment_area_km2} km²")
print(station.get_catchment_info())
```

#### **Option C: Via API or Script**
```python
# Example: Bulk import catchment polygons
import json
from discharge_prediction.models import DischargeStation

catchment_data = {
    'STATION_01': 'path/to/station01_catchment.geojson',
    'STATION_02': 'path/to/station02_catchment.geojson',
}

for station_id, geojson_file in catchment_data.items():
    try:
        station = DischargeStation.objects.get(station_id=station_id)

        with open(geojson_file, 'r') as f:
            geojson = json.load(f)

        if station.set_catchment_from_geojson(geojson):
            station.save()
            print(f"✓ Updated {station_id}: {station.catchment_area_km2} km²")
        else:
            print(f"✗ Failed to update {station_id}")
    except Exception as e:
        print(f"✗ Error with {station_id}: {e}")
```

### Step 3: Configure Sensor API Endpoints

#### **Via Django Admin:**
1. Edit a station
2. In "Ground Station Sensor Integration" section
3. Enter the API endpoint URL (e.g., `https://sensor-api.example.com/stations/STATION_01/latest`)
4. Save the station

#### **Via Django Shell:**
```python
from discharge_prediction.models import DischargeStation

station = DischargeStation.objects.get(station_id='STATION_01')
station.sensor_api_endpoint = 'https://sensor-api.example.com/stations/STATION_01/latest'
station.save()

# Test API connection
result = station.fetch_sensor_data_from_api()
if result['success']:
    print("✓ Sensor API connected successfully")
    print(f"Data: {result['data']}")
else:
    print(f"✗ API Error: {result['error']}")
```

---

## 📊 Data Migration Notes

### **Important: Existing Data**
The migration **removes** the old `catchment_area` numeric field. If you have existing catchment area values:

1. **Before migration**, export existing data:
```python
# Run this BEFORE migrating
from discharge_prediction.models import DischargeStation
import json

data = []
for station in DischargeStation.objects.all():
    if station.catchment_area:
        data.append({
            'station_id': station.station_id,
            'catchment_area_km2': station.catchment_area
        })

with open('catchment_areas_backup.json', 'w') as f:
    json.dump(data, f, indent=2)
```

2. **After migration**, you can reference this data to verify polygon areas match expected values.

### **Converting Numeric Areas to Polygons**
If you need to preserve numeric catchment area values, you can:
1. Keep the backup JSON file
2. Load catchment polygons from GIS data sources
3. Verify the calculated `catchment_area_km2` matches your backup values

---

## 🧪 Testing the New Features

### Test Catchment Polygon Functionality
```python
from discharge_prediction.models import DischargeStation

station = DischargeStation.objects.first()

# Test 1: Set from GeoJSON
geojson = {
    "type": "Polygon",
    "coordinates": [[[85.0, 27.0], [86.0, 27.0], [86.0, 28.0], [85.0, 28.0], [85.0, 27.0]]]
}
assert station.set_catchment_from_geojson(geojson) == True

# Test 2: Verify area calculation
area = station.catchment_area_km2
assert area is not None
assert area > 0
print(f"✓ Catchment area: {area} km²")

# Test 3: Get catchment info
info = station.get_catchment_info()
assert info['has_polygon'] == True
assert info['num_polygons'] >= 1
print(f"✓ Catchment info: {info}")

# Test 4: Export GeoJSON
exported_geojson = station.get_catchment_geojson()
assert exported_geojson is not None
assert exported_geojson['type'] in ['Polygon', 'MultiPolygon']
print(f"✓ Exported GeoJSON: {exported_geojson}")
```

### Test Sensor API Integration
```python
from discharge_prediction.models import DischargeStation

station = DischargeStation.objects.first()

# Test 1: Set API endpoint
station.sensor_api_endpoint = 'https://api.example.com/sensor/data'
station.save()
print(f"✓ API endpoint set: {station.sensor_api_endpoint}")

# Test 2: Fetch sensor data
result = station.fetch_sensor_data_from_api()
if result['success']:
    print(f"✓ API fetch successful")
    print(f"  Data: {result['data']}")
else:
    print(f"⚠ API fetch failed: {result['error']}")

# Test 3: Get sensor readings
latest = station.get_latest_sensor_reading()
print(f"✓ Latest sensor reading: {latest}")

recent_readings = station.get_sensor_readings(hours=24)
print(f"✓ Recent readings count: {recent_readings.count()}")
```

---

## 📝 API Integration Example

Here's how to integrate with a sensor API that returns JSON data:

```python
# Example: Periodic sensor data fetching task
from discharge_prediction.models import DischargeStation, SensorReading
from django.utils import timezone

def fetch_and_store_sensor_data():
    """Fetch sensor data from all stations with configured API endpoints"""

    stations = DischargeStation.objects.filter(
        is_active=True,
        sensor_api_endpoint__isnull=False
    ).exclude(sensor_api_endpoint='')

    for station in stations:
        result = station.fetch_sensor_data_from_api()

        if result['success']:
            # Parse the API response and create SensorReading
            data = result['data']

            SensorReading.objects.create(
                station=station,
                timestamp=timezone.now(),
                temperature=data.get('temperature'),
                humidity=data.get('humidity'),
                pressure=data.get('pressure'),
                water_depth=data.get('water_depth'),
                # ... map other fields
                data_quality='good',
                processing_status='processed'
            )
            print(f"✓ Stored sensor data for {station.station_id}")
        else:
            print(f"✗ Failed to fetch data for {station.station_id}: {result['error']}")
```

You can schedule this function using Django's management commands or Celery:
```python
# In a management command or Celery task
from django.core.management.base import BaseCommand

class Command(BaseCommand):
    help = 'Fetch sensor data from all station APIs'

    def handle(self, *args, **options):
        fetch_and_store_sensor_data()
```

---

## 🔍 Admin Interface Features

### Visual Indicators
- **Catchment Area Display**: Shows calculated area with green color indicator
- **Catchment Info**: Expandable section showing:
  - Total area in km²
  - Number of polygons (if MultiPolygon)
  - Geographic bounds (N/S/E/W)
  - Centroid coordinates

### Map Integration
The Django GIS admin provides:
- Interactive map widget for drawing polygons
- OpenLayers or Leaflet integration
- Ability to upload GeoJSON files directly
- Visual editing of polygon boundaries

---

## ⚠️ Important Notes

1. **SRID**: All catchment polygons use SRID 4326 (WGS84) for global compatibility
2. **Area Calculation**: Uses geodetic calculation for accuracy over large areas
3. **MultiPolygon Support**: Can handle complex catchment areas with multiple disconnected regions
4. **API Timeout**: Sensor API requests have a 30-second timeout
5. **Polygon Conversion**: Single Polygon geometries are automatically converted to MultiPolygon

---

## 📚 Additional Resources

- **Django GIS Documentation**: https://docs.djangoproject.com/en/stable/ref/contrib/gis/
- **GeoJSON Specification**: https://geojson.org/
- **GDAL/OGR Tools**: For converting between GIS formats

---

## ✅ Migration Applied

Generated migration file: `0009_add_catchment_polygon_and_sensor_api.py`

**Operations:**
1. ❌ Remove `catchment_area` field (FloatField)
2. ✅ Add `catchment_polygon` field (MultiPolygonField, SRID 4326)
3. ✅ Add `sensor_api_endpoint` field (URLField, max 500 chars)

**To apply:**
```bash
python manage.py migrate discharge_prediction
```

---

**Updated by:** Claude Code
**Date:** 2026-02-17
**Files Modified:**
- `discharge_prediction/models.py`
- `discharge_prediction/admin.py`
- `discharge_prediction/migrations/0009_add_catchment_polygon_and_sensor_api.py`
