from django.db import models
from django.contrib.gis.db import models as gis_models
from django.core.validators import MinValueValidator, MaxValueValidator
from datetime import datetime, timedelta, date
import uuid
import json

class DischargeStation(gis_models.Model):
    # Hydropower calculation parameters
    net_head = models.FloatField(
        help_text="Net head for energy calculation (meters)",
        null=True, blank=True, default=115.5
    )
    efficiency = models.FloatField(
        help_text="Turbine-generator efficiency (0-1)",
        null=True, blank=True, default=0.8827,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )
    max_discharge_for_energy = models.FloatField(
        help_text="Max discharge (m³/s) for energy calculation cap",
        null=True, blank=True, default=29.75
    )
    """Model for water discharge monitoring stations - each with its own PyTorch model"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, help_text="Station name (e.g., 'Hydropower X')")
    station_id = models.CharField(max_length=50, unique=True, help_text="Unique station identifier")
    location = gis_models.PointField(help_text="Station coordinates (primary point)")
    latitude = models.FloatField(
        help_text="Station latitude (decimal degrees, e.g., 27.7172)", 
        null=True, blank=True,
        validators=[MinValueValidator(-90.0), MaxValueValidator(90.0)]
    )
    longitude = models.FloatField(
        help_text="Station longitude (decimal degrees, e.g., 85.3240)", 
        null=True, blank=True,
        validators=[MinValueValidator(-180.0), MaxValueValidator(180.0)]
    )
    
    # ERA5 Download Area Configuration
    download_area_north = models.FloatField(
        help_text="North boundary for ERA5 download area (decimal degrees)", 
        null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    download_area_west = models.FloatField(
        help_text="West boundary for ERA5 download area (decimal degrees)", 
        null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )
    download_area_south = models.FloatField(
        help_text="South boundary for ERA5 download area (decimal degrees)", 
        null=True, blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)]
    )
    download_area_east = models.FloatField(
        help_text="East boundary for ERA5 download area (decimal degrees)", 
        null=True, blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)]
    )
    use_auto_area = models.BooleanField(
        default=True, 
        help_text="Use automatic area generation from location point (if False, uses custom area)"
    )
    
    elevation = models.FloatField(help_text="Station elevation in meters", null=True, blank=True)

    # Catchment Area - Numeric value provided by admin
    catchment_area = models.FloatField(
        help_text="Upstream catchment area in km² (provided by admin)",
        null=True, blank=True
    )

    # Catchment Area Geometry (GeoJSON)
    catchment_polygon = gis_models.MultiPolygonField(
        help_text="Upstream catchment area polygon geometry (GeoJSON)",
        null=True, blank=True,
        srid=4326  # WGS84 coordinate system
    )

    river_name = models.CharField(max_length=200, help_text="Name of the river", blank=True)
    country = models.CharField(max_length=100, blank=True)
    operator = models.CharField(max_length=200, help_text="Station operator/organization", blank=True)

    # Ground Station Sensor API Integration
    sensor_api_endpoint = models.URLField(
        max_length=500,
        help_text="API endpoint URL for fetching ground station sensor data",
        blank=True, null=True
    )
    # JSON key in the GST API response that contains the discharge depth value
    # e.g. 'water_depth', 'stage_m', 'depth'  — leave blank to use the default field
    gst_depth_api_field = models.CharField(
        max_length=100,
        default='water_depth',
        blank=True,
        help_text="JSON key name in the GST API response that holds the discharge depth reading"
    )

    # ── Rating curve (power-law: Q = c * (H - a)^b) ───────────────────────────
    # Used to convert raw DHM stage height (H, metres) to discharge (Q, m³/s)
    # for the nearest reference DHM gauging station.
    # Then the CAR method scales Q to this station: Q2 = Q1 * (catchment_area / reference_catchment_area_km2)
    rating_curve_c = models.FloatField(
        null=True, blank=True,
        help_text="Rating curve coefficient c in Q = c*(H-a)^b (for reference DHM station)"
    )
    rating_curve_a = models.FloatField(
        null=True, blank=True,
        help_text="Rating curve zero-flow stage offset a in Q = c*(H-a)^b (metres)"
    )
    rating_curve_b = models.FloatField(
        null=True, blank=True,
        help_text="Rating curve exponent b in Q = c*(H-a)^b"
    )
    reference_catchment_area_km2 = models.FloatField(
        null=True, blank=True,
        help_text="Catchment area of the reference DHM station (A1, km²) used in CAR scaling"
    )

    # ── Prediction pipeline mode ───────────────────────────────────────────────
    PIPELINE_ERA5_ONLY = 'era5_only'
    PIPELINE_ERA5_CAR  = 'era5_car'
    PIPELINE_CHOICES = [
        ('era5_only', 'ERA5 Only (6 features: t2m, u10, v10, tp, q, soil_moisture)'),
        ('era5_car',  'ERA5 + CAR Discharge (7 features: ERA5 ×6 + Q2 from DHM stage)'),
    ]
    prediction_pipeline = models.CharField(
        max_length=20,
        choices=PIPELINE_CHOICES,
        default='era5_only',
        help_text=(
            "Input feature pipeline for the LSTM model. "
            "'era5_car' appends the CAR-derived discharge Q2 (computed from DHM stage heights "
            "via Q1=c*(H-a)^b, Q2=Q1*(A2/A1)) as a 7th feature alongside the 6 ERA5 variables. "
            "Use 'era5_only' for stations without DHM stage data (e.g. Mailung)."
        )
    )

    # Station-specific model configuration
    model_file_path = models.CharField(max_length=500, help_text="Path to station-specific PyTorch model file", blank=True)
    scaler_file_path = models.CharField(max_length=500, help_text="Path to station-specific scaler file", blank=True)
    denormalization_scaler_path = models.CharField(max_length=500, help_text="Path to station-specific denormalization scaler file", blank=True, null=True)
    model_description = models.TextField(help_text="Description of the station-specific model", blank=True)
    model_performance_score = models.FloatField(help_text="Model validation score (R², accuracy, etc.)", null=True, blank=True)
    
    # Station status and metadata
    is_active = models.BooleanField(default=True, help_text="Is station actively forecasting")
    is_model_ready = models.BooleanField(default=False, help_text="Is PyTorch model configured and ready")
    last_forecast_date = models.DateField(help_text="Last date forecasted", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Discharge Station"
        verbose_name_plural = "Discharge Stations"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.station_id})"
    
    def save(self, *args, **kwargs):
        """Auto-sync latitude/longitude with location point field"""
        from django.contrib.gis.geos import Point
        
        # If latitude and longitude are provided, update the location point
        if self.latitude is not None and self.longitude is not None:
            self.location = Point(self.longitude, self.latitude)
        # If location point exists but lat/lon fields are empty, sync them
        elif self.location and (self.latitude is None or self.longitude is None):
            self.latitude = self.location.y
            self.longitude = self.location.x
            
        super().save(*args, **kwargs)
    
    @property
    def coordinates(self):
        """Get station coordinates as (longitude, latitude) for ERA5 downloads"""
        if self.location:
            return (self.location.x, self.location.y)
        return None
    
    @property
    def era5_download_area(self):
        """
        Get ERA5 download area as [North, West, South, East].
        Priority:
          1) Admin-specified custom area (use_auto_area=False + all 4 boundaries set)
          2) Catchment polygon bounding box + 0.1° buffer (hydrologically correct)
          3) 0.5° buffer around station point (fallback when no polygon available)
        """
        if not self.use_auto_area and self.has_custom_area():
            # Admin-specified manual boundaries — use as-is, no buffer added
            return [
                self.download_area_north,
                self.download_area_west,
                self.download_area_south,
                self.download_area_east
            ]
        elif self.catchment_polygon:
            # Derive from catchment polygon extent — covers full watershed
            # extent returns (west, south, east, north)
            west, south, east, north = self.catchment_polygon.extent
            buffer = 0.1  # small buffer around catchment edge in degrees
            return [
                round(north + buffer, 4),   # North
                round(west - buffer, 4),    # West
                round(south - buffer, 4),   # South
                round(east + buffer, 4)     # East
            ]
        elif self.location:
            # Fallback: buffer around gauge point (no polygon available)
            lat, lon = self.location.y, self.location.x
            buffer = 0.5
            return [
                lat + buffer,   # North
                lon - buffer,   # West
                lat - buffer,   # South
                lon + buffer    # East
            ]
        else:
            raise ValueError(f"Station {self.name} has no location or custom area configured")
    
    def has_custom_area(self):
        """Check if station has all custom area boundaries defined"""
        return all([
            self.download_area_north is not None,
            self.download_area_west is not None,
            self.download_area_south is not None,
            self.download_area_east is not None
        ])
    
    def set_custom_area(self, north, west, south, east):
        """Set custom download area and disable auto-area"""
        self.download_area_north = north
        self.download_area_west = west
        self.download_area_south = south
        self.download_area_east = east
        self.use_auto_area = False
        self.save()
    
    def get_area_info(self):
        """Get human-readable area information"""
        area = self.era5_download_area
        area_type = "Custom" if not self.use_auto_area and self.has_custom_area() else "Auto-generated"
        return {
            'type': area_type,
            'north': area[0],
            'west': area[1], 
            'south': area[2],
            'east': area[3],
            'size_degrees': {
                'lat_span': area[0] - area[2],  # North - South
                'lon_span': area[3] - area[1]   # East - West  
            }
        }
    def has_trained_model(self):
        """Check if station has a configured PyTorch model"""
        import os
        return (self.model_file_path and 
                os.path.exists(self.model_file_path) and
                self.is_model_ready)
    
    def get_latest_prediction(self):
        """Get the most recent prediction for this station"""
        return self.predictions.filter(processing_status='completed').first()
    
    def get_monthly_forecast(self, year, month):
        """Get monthly forecast for specific year/month"""
        return MonthlyForecast.objects.filter(
            station=self,
            target_year=year,
            target_month=month
        ).first()
    
    def get_era5_data_count(self):
        """Count available ERA5 data points for this station"""
        return self.era5_data.filter(is_complete=True).count()
    
    def get_validation_data_count(self):
        """Count available historical discharge records for validation"""
        return self.discharge_records.count()

    # Catchment Polygon Methods
    @property
    def catchment_area_km2(self):
        """
        Calculate catchment area in km² from the polygon geometry.
        Uses geodetic area calculation for accuracy.
        """
        if not self.catchment_polygon:
            return None

        # Transform to projected coordinate system for accurate area calculation
        # Using equal-area projection (e.g., Albers Equal Area for accuracy)
        from django.contrib.gis.geos import GEOSGeometry

        # Get the polygon in its native SRID (4326 - WGS84)
        polygon = self.catchment_polygon

        # Calculate geodetic area (more accurate than planar for large areas)
        # Note: area is returned in square meters, convert to km²
        area_m2 = polygon.area  # This uses geodetic calculation
        area_km2 = area_m2 / 1_000_000  # Convert m² to km²

        return round(area_km2, 2)

    def set_catchment_from_geojson(self, geojson_data):
        """
        Set catchment polygon from GeoJSON data.

        Args:
            geojson_data: GeoJSON string, dict, or file-like object

        Returns:
            bool: True if successful, False otherwise
        """
        from django.contrib.gis.geos import GEOSGeometry

        try:
            # Handle different input types
            if isinstance(geojson_data, str):
                # GeoJSON string
                geom = GEOSGeometry(geojson_data)
            elif isinstance(geojson_data, dict):
                # GeoJSON dict - convert to string first
                import json
                geojson_str = json.dumps(geojson_data)
                geom = GEOSGeometry(geojson_str)
            else:
                # Assume it's already a GEOSGeometry object
                geom = geojson_data

            # Ensure it's a MultiPolygon (convert Polygon if needed)
            if geom.geom_type == 'Polygon':
                from django.contrib.gis.geos import MultiPolygon
                geom = MultiPolygon(geom)
            elif geom.geom_type != 'MultiPolygon':
                raise ValueError(f"Invalid geometry type: {geom.geom_type}. Expected Polygon or MultiPolygon.")

            # Set the SRID to WGS84 if not already set
            if geom.srid is None or geom.srid != 4326:
                geom.srid = 4326

            self.catchment_polygon = geom
            return True

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error setting catchment polygon from GeoJSON: {e}")
            return False

    def get_catchment_geojson(self):
        """
        Get catchment polygon as GeoJSON dict.

        Returns:
            dict: GeoJSON representation of the catchment polygon
        """
        if not self.catchment_polygon:
            return None

        import json
        geojson_str = self.catchment_polygon.geojson
        return json.loads(geojson_str)

    def get_catchment_info(self):
        """Get comprehensive catchment area information"""
        if not self.catchment_polygon:
            return {
                'has_polygon': False,
                'area_km2': None,
                'num_polygons': 0
            }

        return {
            'has_polygon': True,
            'area_km2': self.catchment_area_km2,
            'num_polygons': len(self.catchment_polygon),
            'bounds': {
                'north': self.catchment_polygon.extent[3],
                'south': self.catchment_polygon.extent[1],
                'east': self.catchment_polygon.extent[2],
                'west': self.catchment_polygon.extent[0]
            },
            'centroid': {
                'latitude': self.catchment_polygon.centroid.y,
                'longitude': self.catchment_polygon.centroid.x
            }
        }

    # Ground Station Sensor Methods
    def get_latest_sensor_reading(self):
        """Get the most recent sensor reading from the ground station"""
        return self.sensor_readings.order_by('-timestamp').first()

    def get_sensor_readings(self, hours=24):
        """
        Get recent sensor readings from the ground station.

        Args:
            hours: Number of hours to look back (default: 24)

        Returns:
            QuerySet of SensorReading objects
        """
        from django.utils import timezone
        cutoff_time = timezone.now() - timedelta(hours=hours)

        return self.sensor_readings.filter(
            timestamp__gte=cutoff_time
        ).order_by('-timestamp')

    def fetch_sensor_data_from_api(self):
        """
        Fetch latest sensor data from the configured API endpoint.

        Returns:
            dict: Response data from the API or error information
        """
        if not self.sensor_api_endpoint:
            return {
                'success': False,
                'error': 'No sensor API endpoint configured for this station'
            }

        try:
            import requests
            from django.utils import timezone

            # Make API request to fetch sensor data
            response = requests.get(
                self.sensor_api_endpoint,
                timeout=30  # 30 second timeout
            )
            response.raise_for_status()

            data = response.json()

            return {
                'success': True,
                'data': data,
                'fetched_at': timezone.now().isoformat()
            }

        except requests.exceptions.RequestException as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error fetching sensor data from {self.sensor_api_endpoint}: {e}")

            return {
                'success': False,
                'error': str(e),
                'endpoint': self.sensor_api_endpoint
            }
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Unexpected error fetching sensor data: {e}")

            return {
                'success': False,
                'error': f'Unexpected error: {str(e)}'
            }

    # ── Google Sheets helpers ─────────────────────────────────────────────────

    @property
    def has_rating_curve(self):
        """True when all three rating curve parameters and reference area are set."""
        return all([
            self.rating_curve_c is not None,
            self.rating_curve_a is not None,
            self.rating_curve_b is not None,
            self.reference_catchment_area_km2 is not None,
            self.catchment_area is not None,
        ])

    def compute_discharge_from_stage(self, stage_height):
        """
        Convert a raw DHM stage height H (metres) to station discharge Q2 (m³/s)
        using the power-law rating curve and the CAR (Catchment Area Ratio) method.

        Step 1 — Rating curve for reference DHM station:
            Q1 = c * (H - a) ^ b

        Step 2 — CAR scaling to this station:
            Q2 = Q1 * (A2 / A1)
              where A2 = self.catchment_area (km²)
                    A1 = self.reference_catchment_area_km2 (km²)

        Returns None when the rating curve is not configured, or 0.0 when
        H <= a (stage below zero-flow level).
        """
        if not self.has_rating_curve:
            return None
        h_effective = stage_height - self.rating_curve_a
        if h_effective <= 0:
            return 0.0
        q1 = self.rating_curve_c * (h_effective ** self.rating_curve_b)
        q2 = q1 * (self.catchment_area / self.reference_catchment_area_km2)
        return max(0.0, round(q2, 4))

    def get_latest_gst_depth(self):
        """
        Return the most recent non-null GST discharge depth from SensorReading.

        Returns the depth value (float, meters) or None when no GST readings
        are available — the caller should degrade gracefully in that case.
        """
        reading = self.sensor_readings.filter(
            discharge_depth__isnull=False
        ).order_by('-timestamp').first()
        return reading.discharge_depth if reading else None


class DHMStage(models.Model):
    """
    Historical measurements for a station — raw stage height AND computed discharge.

    DHM River Watch returns daily Max / Min / Average **stage height** (H, metres)
    for a nearby reference gauging station (e.g. Sangutar for Lower Likhu).  The
    raw stage heights are stored in ``stage_height`` / ``stage_height_max`` /
    ``stage_height_min``.

    Stage heights drive the rating-curve conversion when needed:
        Q1 = c * (H - a)^b          [power-law rating curve]
        Q2 = Q1 * (A2 / A1)         [CAR catchment area scaling]
    """
    station = models.ForeignKey(DischargeStation, on_delete=models.CASCADE, related_name='discharge_records')
    timestamp = models.DateTimeField(help_text="Measurement timestamp (midnight UTC of measurement date)")

    # ── Raw stage height from DHM (H, metres) ─────────────────────────────────
    stage_height = models.FloatField(
        help_text="Average daily stage height H in metres (raw DHM reading)",
        null=True, blank=True,
        validators=[MinValueValidator(0)]
    )
    stage_height_max = models.FloatField(
        help_text="Maximum daily stage height H in metres (raw DHM reading)",
        null=True, blank=True,
        validators=[MinValueValidator(0)]
    )
    stage_height_min = models.FloatField(
        help_text="Minimum daily stage height H in metres (raw DHM reading)",
        null=True, blank=True,
        validators=[MinValueValidator(0)]
    )

    # ── CAR-derived discharge (7th LSTM feature for era5_car pipeline) ─────────
    discharge_q2 = models.FloatField(
        null=True, blank=True,
        help_text=(
            "Average daily discharge Q2 (m³/s) computed via the CAR method: "
            "Q1 = c*(H-a)^b  →  Q2 = Q1*(A2/A1). "
            "Used as the 7th input feature in the era5_car prediction pipeline. "
            "Auto-populated on save() when the station rating curve is configured."
        ),
        validators=[MinValueValidator(0)]
    )

    quality_flag = models.CharField(
        max_length=20,
        choices=[
            ('good', 'Good'),
            ('fair', 'Fair'),
            ('poor', 'Poor'),
            ('estimated', 'Estimated'),
            ('missing', 'Missing')
        ],
        default='good'
    )
    data_source = models.CharField(max_length=100, help_text="Source of the data", blank=True)
    notes = models.TextField(
        blank=True, null=True,
        help_text="Optional free-text notes for this record"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "DHM Stage"
        verbose_name_plural = "DHM Stage Records"
        ordering = ['-timestamp']
        unique_together = ['station', 'timestamp']

    def __str__(self):
        h = f"H={self.stage_height:.3f} m" if self.stage_height is not None else "no stage"
        return f"{self.station.name} - {self.timestamp.strftime('%Y-%m-%d')} - {h}"

    def save(self, *args, **kwargs):
        """Auto-compute discharge_q2 from stage_height whenever a record is saved."""
        if self.stage_height is not None:
            self.discharge_q2 = self.station.compute_discharge_from_stage(self.stage_height)
        else:
            self.discharge_q2 = None
        super().save(*args, **kwargs)


class DHMMeteoStation(models.Model):
    """
    Registry of DHM meteorological source stations.

    Each physical DHM station is registered here once.  Multiple hydropower
    stations can link to the same DHM meteo station via DHMMeteoRecord — e.g.
    both Mailung (rainfall from Pansayakhola) and any future station can share
    a single source record.

    variable_type controls which fields in DHMMeteoRecord are populated:
      'rainfall' → rainfall_mm
      'climate'  → temp_*, relative_humidity, wind_speed_ms, wind_direction_deg
    """
    VARIABLE_CHOICES = [
        ('rainfall', 'Rainfall'),
        ('climate',  'Temperature / RH / Wind'),
    ]

    name           = models.CharField(max_length=100, unique=True, help_text="DHM station name, e.g. 'Pansayakhola'")
    variable_type  = models.CharField(max_length=20, choices=VARIABLE_CHOICES)

    # DHM series IDs used in API requests
    seriesid            = models.CharField(max_length=20, blank=True, help_text="DHM series ID (rainfall & temperature)")
    wind_speed_seriesid = models.CharField(max_length=20, blank=True, help_text="DHM series ID for wind speed")
    wind_dir_seriesid   = models.CharField(max_length=20, blank=True, help_text="DHM series ID for wind direction")
    humidity_seriesid   = models.CharField(max_length=20, blank=True, help_text="DHM series ID for relative humidity")

    # Optional geographic metadata
    latitude  = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    elevation_m = models.FloatField(null=True, blank=True, help_text="Station elevation in metres")

    # Hydropower stations this meteo source feeds
    hydro_stations = models.ManyToManyField(
        DischargeStation,
        blank=True,
        related_name='meteo_sources',
        help_text="Hydropower stations that use this DHM meteo station as a data source",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "DHM Meteo Station"
        verbose_name_plural = "DHM Meteo Stations"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_variable_type_display()})"


class DHMMeteoRecord(models.Model):
    """
    Daily meteorological observations from a DHM meteo station.

    One record per (meteo_station, timestamp) — midnight UTC of measurement
    date.  Fields are nullable so that a rainfall-only station leaves
    temperature / wind / humidity as NULL, and a climate station leaves
    rainfall as NULL.

    Fetch strategy differs by variable_type:
      rainfall  → POST to getRainfallWatchBySeriesId_single  (like discharge)
      climate   → GET  https://dhm.gov.np/hydrology/surface-observation
                  parse embedded JS var observation_data = [...];
                  aggregate hourly → daily min/max/avg
    """
    meteo_station = models.ForeignKey(
        DHMMeteoStation,
        on_delete=models.CASCADE,
        related_name='records',
    )
    timestamp = models.DateTimeField(help_text="Midnight UTC of measurement date")

    # ── Rainfall ──────────────────────────────────────────────────────────────
    rainfall_mm = models.FloatField(
        null=True, blank=True,
        validators=[MinValueValidator(0)],
        help_text="Daily total rainfall (mm)",
    )

    # ── Temperature (°C) ──────────────────────────────────────────────────────
    temp_avg_c = models.FloatField(null=True, blank=True, help_text="Daily average temperature (°C)")
    temp_max_c = models.FloatField(null=True, blank=True, help_text="Daily maximum temperature (°C)")
    temp_min_c = models.FloatField(null=True, blank=True, help_text="Daily minimum temperature (°C)")

    # ── Relative Humidity (%) ─────────────────────────────────────────────────
    rh_avg    = models.FloatField(null=True, blank=True, help_text="Daily average relative humidity (%)")
    rh_max    = models.FloatField(null=True, blank=True, help_text="Daily maximum relative humidity (%)")
    rh_min    = models.FloatField(null=True, blank=True, help_text="Daily minimum relative humidity (%)")

    # ── Wind Speed (m/s) ──────────────────────────────────────────────────────
    wind_speed_avg_ms = models.FloatField(null=True, blank=True, help_text="Daily average wind speed (m/s)")
    wind_speed_max_ms = models.FloatField(null=True, blank=True, help_text="Daily maximum wind speed (m/s)")
    wind_speed_min_ms = models.FloatField(null=True, blank=True, help_text="Daily minimum wind speed (m/s)")

    # ── Wind Direction (degrees) ───────────────────────────────────────────────
    wind_dir_avg_deg = models.FloatField(null=True, blank=True, help_text="Daily average wind direction (°)")
    wind_dir_max_deg = models.FloatField(null=True, blank=True, help_text="Daily maximum wind direction (°)")
    wind_dir_min_deg = models.FloatField(null=True, blank=True, help_text="Daily minimum wind direction (°)")

    # ── Metadata ──────────────────────────────────────────────────────────────
    quality_flag = models.CharField(
        max_length=20,
        choices=[
            ('good',      'Good'),
            ('fair',      'Fair'),
            ('poor',      'Poor'),
            ('estimated', 'Estimated'),
            ('missing',   'Missing'),
        ],
        default='good',
    )
    data_source = models.CharField(max_length=100, default='dhm_scrape')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "DHM Meteo Record"
        verbose_name_plural = "DHM Meteo Records"
        unique_together = ['meteo_station', 'timestamp']
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.meteo_station.name} — {self.timestamp.strftime('%Y-%m-%d')}"


class DischargePrediction(models.Model):
    """Model for storing discharge predictions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    station = models.ForeignKey(DischargeStation, on_delete=models.CASCADE, related_name='predictions')
    
    # Prediction details
    target_date = models.DateField(help_text="Date for which discharge is predicted")
    predicted_discharge = models.FloatField(help_text="Predicted discharge in m³/s", validators=[MinValueValidator(0)])
    predicted_energy = models.FloatField(help_text="Predicted daily energy in MWh", null=True, blank=True)
    
    # Confidence and uncertainty
    prediction_confidence = models.FloatField(
        help_text="Prediction confidence score (0-1)", 
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        null=True, blank=True
    )
    confidence_lower = models.FloatField(help_text="Lower confidence bound in m³/s", null=True, blank=True)
    confidence_upper = models.FloatField(help_text="Upper confidence bound in m³/s", null=True, blank=True)
    
    # Model information
    model_name = models.CharField(max_length=100, help_text="Name of prediction model used")
    sequence_length = models.IntegerField(help_text="Input sequence length in days", default=90)
    forecast_type = models.CharField(
        max_length=20,
        choices=[
            ('daily', 'Daily'),
            ('monthly', 'Monthly'),
            ('seasonal', 'Seasonal')
        ],
        default='daily'
    )
    
    # Processing status
    processing_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed')
        ],
        default='pending'
    )
    
    # Validation (populated when actual discharge becomes available)
    actual_discharge = models.FloatField(help_text="Actual observed discharge in m³/s", null=True, blank=True)
    accuracy_score = models.FloatField(
        help_text="Prediction accuracy score (0-1)", 
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        null=True, blank=True
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Discharge Prediction"
        verbose_name_plural = "Discharge Predictions"
        ordering = ['-created_at']
        unique_together = ['station', 'target_date', 'model_name']

    def __str__(self):
        return f"{self.station.name} - {self.target_date} - {self.predicted_discharge:.2f} m³/s"

    @property
    def forecast_accuracy(self):
        """Calculate forecast accuracy if actual discharge is available"""
        if self.actual_discharge is not None and self.actual_discharge > 0:
            error = abs(self.predicted_discharge - self.actual_discharge)
            relative_error = error / self.actual_discharge
            accuracy = max(0, 1 - relative_error)
            return round(accuracy, 3)
        return None
        
    def calculate_accuracy(self):
        """Calculate and store accuracy score when actual data is available"""
        accuracy = self.forecast_accuracy
        if accuracy is not None:
            self.accuracy_score = accuracy
            self.save()
        return accuracy

class PredictionModel(models.Model):
    """Model for storing information about prediction models"""
    name = models.CharField(max_length=100, unique=True)
    version = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    model_type = models.CharField(
        max_length=50,
        choices=[
            ('statistical', 'Statistical'),
            ('machine_learning', 'Machine Learning'),
            ('deep_learning', 'Deep Learning'),
            ('physical', 'Physical-based'),
            ('hybrid', 'Hybrid')
        ]
    )
    input_features = models.JSONField(help_text="List of input features used by the model")
    parameters = models.JSONField(help_text="Model parameters and configuration", blank=True, null=True)
    training_period = models.CharField(max_length=100, help_text="Training data period", blank=True)
    validation_score = models.FloatField(help_text="Model validation score", null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Prediction Model"
        verbose_name_plural = "Prediction Models"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} v{self.version}"


class ERA5Data(models.Model):
    """Model for storing ERA5 reanalysis weather data"""
    station = models.ForeignKey(DischargeStation, on_delete=models.CASCADE, related_name='era5_data')
    date = models.DateField(help_text="Date of ERA5 data")
    
    # Primary ERA5 variables for discharge prediction (core 5 features for existing models)
    temperature_2m = models.FloatField(help_text="2m temperature in °C", null=True, blank=True)
    total_precipitation = models.FloatField(help_text="Total precipitation in mm", null=True, blank=True)
    u_component_10m = models.FloatField(help_text="10m U-component wind (East-West) in m/s", null=True, blank=True)
    v_component_10m = models.FloatField(help_text="10m V-component wind (North-South) in m/s", null=True, blank=True)
    specific_humidity = models.FloatField(help_text="Specific humidity in kg/kg", null=True, blank=True)

    # Additional hydrological variables
    soil_moisture = models.FloatField(
        help_text="Volumetric soil moisture in m³/m³ (0-1 range)",
        null=True,
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)]
    )

    # Data quality and processing
    data_source = models.CharField(max_length=50, default='ERA5')
    download_timestamp = models.DateTimeField(help_text="When data was downloaded")
    processing_status = models.CharField(
        max_length=20,
        choices=[
            ('raw', 'Raw Downloaded'),
            ('processed', 'Processed'),
            ('validated', 'Validated'),
            ('error', 'Error')
        ],
        default='raw'
    )
    is_complete = models.BooleanField(default=False, help_text="All required variables available")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ERA5 Data"
        verbose_name_plural = "ERA5 Data"
        ordering = ['-date']
        unique_together = ['station', 'date']

    def __str__(self):
        return f"{self.station.name} - {self.date.strftime('%Y-%m-%d')} - ERA5"

    @property
    def is_available_for_prediction(self):
        """Check if data is ready for use in prediction (7-day delay rule)"""
        delay_threshold = datetime.now().date() - timedelta(days=7)
        return self.date <= delay_threshold and self.is_complete
    
    def get_feature_vector(self):
        """Get the 5-feature vector for model input in exact training order"""
        # Feature order MUST match your SurfaceInferencePreprocessor training order: ["t2m", "u10", "v10", "tp", "q"]
        return [
            self.temperature_2m or 0.0,        # t2m
            self.u_component_10m or 0.0,       # u10
            self.v_component_10m or 0.0,       # v10
            self.total_precipitation or 0.0,   # tp
            self.specific_humidity or 0.0      # q
        ]

    def get_extended_feature_vector(self):
        """Get the 6-feature vector including soil moisture for extended models"""
        # Feature order: ["t2m", "u10", "v10", "tp", "q", "sm"]
        # NOTE: Using this requires retraining your model with soil moisture included
        return [
            self.temperature_2m or 0.0,        # t2m
            self.u_component_10m or 0.0,       # u10
            self.v_component_10m or 0.0,       # v10
            self.total_precipitation or 0.0,   # tp
            self.specific_humidity or 0.0,     # q
            self.soil_moisture or 0.0          # sm
        ]

    @classmethod
    def get_feature_names(cls):
        """Get the names of the 5 input features in exact training order"""
        # Feature order MUST match your SurfaceInferencePreprocessor: ["t2m", "u10", "v10", "tp", "q"]
        return [
            'temperature_2m',      # t2m
            'u_component_10m',     # u10
            'v_component_10m',     # v10
            'total_precipitation', # tp
            'specific_humidity'    # q
        ]

    @classmethod
    def get_extended_feature_names(cls):
        """Get the names of the 6 input features including soil moisture"""
        # Extended feature order: ["t2m", "u10", "v10", "tp", "q", "sm"]
        return [
            'temperature_2m',      # t2m
            'u_component_10m',     # u10
            'v_component_10m',     # v10
            'total_precipitation', # tp
            'specific_humidity',   # q
            'soil_moisture'        # sm
        ]


class ForecastSequence(models.Model):
    """Model for managing input sequences for predictions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    station = models.ForeignKey(DischargeStation, on_delete=models.CASCADE, related_name='forecast_sequences')
    target_date = models.DateField(help_text="Date for which discharge is predicted")
    sequence_start_date = models.DateField(help_text="First date in 90-day input sequence")
    sequence_end_date = models.DateField(help_text="Last date in 90-day input sequence")
    
    # Sequence configuration with correct lead time logic
    sequence_length = models.IntegerField(default=90, help_text="Length of input sequence (90 days)")
    lead_time_days = models.IntegerField(default=45, help_text="Lead time from last input to prediction (45 days)")
    era5_delay_days = models.IntegerField(default=7, help_text="ERA5 data delay in days (informational)")
    
    # Input data validation
    data_completeness = models.FloatField(
        help_text="Percentage of complete data in sequence",
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        null=True, blank=True
    )
    is_ready_for_prediction = models.BooleanField(default=False)
    
    # Rolling window metadata
    window_position = models.IntegerField(default=1, help_text="Position in monthly sequence (1-31)")
    is_rolling_window = models.BooleanField(default=True, help_text="Is this part of a rolling window sequence")
    
    # Processing metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_processed = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Forecast Sequence"
        verbose_name_plural = "Forecast Sequences"
        ordering = ['-target_date']
        unique_together = ['station', 'target_date']

    def __str__(self):
        return f"{self.station.name} - Target: {self.target_date} - Sequence: {self.sequence_start_date} to {self.sequence_end_date}"

    def calculate_sequence_dates(self):
        """Calculate sequence start and end dates based on sequence_length and lead_time_days."""
        lead_days = self.lead_time_days  # per-station (e.g. 45)
        input_days = self.sequence_length  # per-station (e.g. 90 or 365)

        # Last input date: lead_time_days before the prediction target
        self.sequence_end_date = self.target_date - timedelta(days=lead_days)

        # First input date: (sequence_length - 1) days before the last input date
        self.sequence_start_date = self.sequence_end_date - timedelta(days=input_days - 1)
        
    def validate_data_availability(self):
        """
        Check data availability across all three input sources for the 90-day window.

        ERA5 data is the *primary* (and currently only) model input and determines
        whether a prediction can be generated.  DischargeRecord and SensorReading
        availability is annotated for informational purposes and will be used for
        future multi-source inference.
        """
        total_days = self.sequence_length
        date_range = [self.sequence_start_date, self.sequence_end_date]

        # ── ERA5 (primary model input) ────────────────────────────────────
        era5_count = ERA5Data.objects.filter(
            station=self.station,
            date__range=date_range,
            is_complete=True,
            processing_status__in=['validated', 'processed'],
        ).count()

        self.data_completeness = (era5_count / total_days) * 100
        # Require at least 50% of the sequence to be available
        self.is_ready_for_prediction = era5_count >= max(50, int(total_days * 0.5))

        return self.is_ready_for_prediction

    def get_available_data_sources(self):
        """
        Return a summary dict of how many days of each input source are available
        in the 90-day sequence window.

        Used by the prediction pipeline to decide which sources can supplement
        or validate ERA5-based inference.

        Returns:
            {
                'era5':             {'count': int, 'completeness_pct': float},
                'discharge_records':{'count': int, 'completeness_pct': float,
                                     'has_min_max': bool},
                'sensor_readings':  {'count': int, 'has_discharge_depth': bool},
                'sequence_days':    int,
            }
        """
        total_days = self.sequence_length
        date_range = [self.sequence_start_date, self.sequence_end_date]

        # ERA5
        era5_count = ERA5Data.objects.filter(
            station=self.station,
            date__range=date_range,
            is_complete=True,
            processing_status__in=['validated', 'processed'],
        ).count()

        # DischargeRecord — keyed on timestamp date  
        from django.db.models import Count as _Count
        dr_qs = DHMStage.objects.filter(
            station=self.station,
            timestamp__date__range=date_range,
        )
        dr_count = dr_qs.count()
        has_min_max = dr_qs.filter(
            stage_height__isnull=False
        ).exists()

        # SensorReading — sub-daily, so group by date
        sr_qs = SensorReading.objects.filter(
            station=self.station,
            timestamp__date__range=date_range,
        )
        sr_day_count = sr_qs.dates('timestamp', 'day').count()
        has_discharge_depth = sr_qs.filter(discharge_depth__isnull=False).exists()

        return {
            'era5': {
                'count': era5_count,
                'completeness_pct': round((era5_count / total_days) * 100, 1),
            },
            'discharge_records': {
                'count': dr_count,
                'completeness_pct': round((dr_count / total_days) * 100, 1),
                'has_min_max': has_min_max,
            },
            'sensor_readings': {
                'count': sr_day_count,
                'has_discharge_depth': has_discharge_depth,
            },
            'sequence_days': total_days,
        }
        
    def get_rolling_window_sequence(self):
        """Get the next sequence in rolling window (shift by 1 day)"""
        next_target = self.target_date + timedelta(days=1)
        next_sequence = ForecastSequence(
            station=self.station,
            target_date=next_target,
            sequence_length=self.sequence_length,
            lead_time_days=self.lead_time_days,
            era5_delay_days=self.era5_delay_days,
            window_position=self.window_position + 1,
            is_rolling_window=True
        )
        next_sequence.calculate_sequence_dates()
        return next_sequence
        
    def save(self, *args, **kwargs):
        if not self.sequence_start_date or not self.sequence_end_date:
            self.calculate_sequence_dates()
        super().save(*args, **kwargs)


class MonthlyForecast(models.Model):
    """Monthly forecast aggregating daily predictions with rolling window approach"""
    station = models.ForeignKey(DischargeStation, on_delete=models.CASCADE)
    target_year = models.IntegerField()
    target_month = models.IntegerField()
    
    # Aggregated forecast statistics from all daily predictions in the month
    mean_discharge = models.FloatField(null=True, blank=True, help_text="Mean predicted discharge for month")
    min_discharge = models.FloatField(null=True, blank=True, help_text="Minimum predicted discharge")
    max_discharge = models.FloatField(null=True, blank=True, help_text="Maximum predicted discharge")
    std_discharge = models.FloatField(null=True, blank=True, help_text="Standard deviation of predictions")
    
    # Monthly energy statistics (calculated using average monthly discharge method)
    total_energy_mwh = models.FloatField(null=True, blank=True, help_text="Total monthly energy using average discharge method: avg_Q × 24hrs × days_in_month")
    mean_energy_mwh = models.FloatField(null=True, blank=True, help_text="Daily energy using average monthly discharge: η×ρ×g×Q_avg×H×24/10^6")
    min_energy_mwh = models.FloatField(null=True, blank=True, help_text="Minimum daily energy prediction in MWh/day")
    max_energy_mwh = models.FloatField(null=True, blank=True, help_text="Maximum daily energy prediction in MWh/day")
    std_energy_mwh = models.FloatField(null=True, blank=True, help_text="Standard deviation of daily energy predictions in MWh/day")
    
    # Rolling window metadata
    total_daily_forecasts = models.IntegerField(default=0, help_text="Number of daily predictions aggregated")
    rolling_window_days = models.IntegerField(default=90, help_text="Length of rolling sequence window")
    
    # Uncertainty quantification
    prediction_confidence = models.FloatField(null=True, blank=True, help_text="Average confidence across daily predictions")
    uncertainty_band_lower = models.FloatField(null=True, blank=True, help_text="Lower uncertainty bound")
    uncertainty_band_upper = models.FloatField(null=True, blank=True, help_text="Upper uncertainty bound")
    
    # Processing metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processing_status = models.CharField(
        max_length=20,
        choices=[
            ('pending', 'Pending'),
            ('processing', 'Processing'),
            ('completed', 'Completed'),
            ('failed', 'Failed')
        ],
        default='pending'
    )
    
    class Meta:
        unique_together = ['station', 'target_year', 'target_month']
        ordering = ['-target_year', '-target_month']
        
    def __str__(self):
        return f"{self.station.name} - {self.target_year}-{self.target_month:02d}"
        
    def get_month_date_range(self):
        """Get the first and last day of the target month"""
        from calendar import monthrange
        first_day = date(self.target_year, self.target_month, 1)
        last_day_num = monthrange(self.target_year, self.target_month)[1]
        last_day = date(self.target_year, self.target_month, last_day_num)
        return first_day, last_day
        
    def aggregate_daily_predictions(self):
        """
        Aggregate all daily predictions for this month using average monthly discharge approach.
        
        Energy Calculation Method:
        1. Calculate average monthly discharge from all daily predictions
        2. Apply discharge cap (max_discharge_for_energy)
        3. Calculate daily energy: Power = η × ρ × g × Q_avg × H / 10^6, Energy = Power × 24
        4. Calculate total monthly energy: Daily Energy × Days in Month
        
        Only calculates energy when complete month data is available (predictions == days_in_month)
        """
        from django.db.models import Avg, Min, Max, StdDev, Count, Sum
        from calendar import monthrange
        import numpy as np
        
        first_day, last_day = self.get_month_date_range()
        
        # Calculate expected number of days in this month
        days_in_month = monthrange(self.target_year, self.target_month)[1]
        
        # Get all daily predictions for this month
        daily_predictions = DischargePrediction.objects.filter(
            station=self.station,
            target_date__range=[first_day, last_day]
        ).aggregate(
            mean_discharge=Avg('predicted_discharge'),
            min_discharge=Min('predicted_discharge'),
            max_discharge=Max('predicted_discharge'),
            std_discharge=StdDev('predicted_discharge'),
            count=Count('id'),
            avg_confidence=Avg('prediction_confidence'),
            # Energy aggregations
            total_energy=Sum('predicted_energy'),
            mean_energy=Avg('predicted_energy'),
            min_energy=Min('predicted_energy'),
            max_energy=Max('predicted_energy'),
            std_energy=StdDev('predicted_energy')
        )
        
        # Update monthly forecast with aggregated discharge values
        self.mean_discharge = daily_predictions['mean_discharge']
        self.min_discharge = daily_predictions['min_discharge'] 
        self.max_discharge = daily_predictions['max_discharge']
        self.std_discharge = daily_predictions['std_discharge'] or 0
        self.total_daily_forecasts = daily_predictions['count'] or 0
        self.prediction_confidence = daily_predictions['avg_confidence']
        
        # Monthly Energy Calculation using Average Monthly Discharge (Your Preferred Approach)
        predictions_count = daily_predictions['count'] or 0
        
        if predictions_count == days_in_month:
            # Complete month data available - use sum of per-day capped energy values
            # Each DischargePrediction.predicted_energy was computed with the cap applied
            # per day, so summing them is more accurate than recalculating from avg discharge.
            
            if daily_predictions['total_energy'] is not None:
                self.total_energy_mwh = daily_predictions['total_energy']
                self.mean_energy_mwh  = daily_predictions['mean_energy']
                self.min_energy_mwh   = daily_predictions['min_energy']
                self.max_energy_mwh   = daily_predictions['max_energy']
                self.std_energy_mwh   = daily_predictions['std_energy'] or 0
                
                print(f"✓ Complete month data: {predictions_count}/{days_in_month} days")
                print(f"  Average monthly discharge: {daily_predictions['mean_discharge']:.2f} m³/s")
                print(f"  Total monthly energy (sum of daily): {self.total_energy_mwh:.2f} MWh")
                print(f"  Mean daily energy: {self.mean_energy_mwh:.2f} MWh/day")
                
            else:
                # Fallback: daily predicted_energy values not yet populated
                self.total_energy_mwh = None
                self.mean_energy_mwh = None
                self.min_energy_mwh = None
                self.max_energy_mwh = None
                self.std_energy_mwh = None
                print(f"✗ No daily energy data available for energy calculation")
                
        else:
            # Incomplete month data - do not calculate monthly energy yet
            self.total_energy_mwh = None
            self.mean_energy_mwh = None
            self.min_energy_mwh = None
            self.max_energy_mwh = None
            self.std_energy_mwh = None
            
            print(f"✗ Incomplete month data: {predictions_count}/{days_in_month} days")
            print(f"  Monthly energy calculation postponed until complete data available")
        
        # Calculate uncertainty bands (assuming normal distribution)
        if self.mean_discharge and self.std_discharge:
            confidence_interval = 1.96 * self.std_discharge  # 95% confidence interval
            self.uncertainty_band_lower = max(0, self.mean_discharge - confidence_interval)
            self.uncertainty_band_upper = self.mean_discharge + confidence_interval
        
        self.processing_status = 'completed'
        self.save()
    
    def calculate_monthly_energy_from_average_discharge(self):
        """
        Alternative energy calculation using average monthly discharge
        Monthly Energy = η × ρ × g × Q_avg × H × 24 / 10^6
        where Q_avg is the average monthly discharge
        """
        from calendar import monthrange
        
        first_day, last_day = self.get_month_date_range()
        days_in_month = monthrange(self.target_year, self.target_month)[1]
        
        # Check if we have complete discharge data for the month
        predictions_count = DischargePrediction.objects.filter(
            station=self.station,
            target_date__range=[first_day, last_day]
        ).count()
        
        if predictions_count == days_in_month:
            # Complete month data available - sum per-day capped energy from DischargePrediction
            from django.db.models import Sum, Avg
            energy_agg = DischargePrediction.objects.filter(
                station=self.station,
                target_date__range=[first_day, last_day]
            ).aggregate(
                total_energy=Sum('predicted_energy'),
                mean_energy=Avg('predicted_energy'),
            )
            
            if energy_agg['total_energy'] is not None:
                return {
                    'method': 'sum_of_daily_capped_energy',
                    'average_monthly_discharge_m3s': self.mean_discharge,
                    'total_monthly_energy_mwh': energy_agg['total_energy'],
                    'daily_energy_mwh': energy_agg['mean_energy'],
                    'days_in_month': days_in_month,
                    'data_completeness': 'complete',
                    'days_available': predictions_count,
                }
            else:
                return {
                    'method': 'sum_of_daily_capped_energy',
                    'error': 'No energy data available in daily predictions',
                    'data_completeness': 'incomplete'
                }
        else:
            return {
                'method': 'average_discharge',
                'error': f'Incomplete month data: {predictions_count}/{days_in_month} days',
                'data_completeness': 'incomplete',
                'days_available': predictions_count,
                'days_in_month': days_in_month
            }
    
    def compare_energy_calculation_methods(self):
        """
        Compare both energy calculation methods:
        1. Sum of daily energies approach (existing)
        2. Average monthly discharge approach (new)
        """
        # Method 1: Sum of daily energies (your original implementation)
        method1_total = self.total_energy_mwh
        method1_avg_daily = self.mean_energy_mwh
        
        # Method 2: Average monthly discharge approach
        method2_result = self.calculate_monthly_energy_from_average_discharge()
        
        comparison = {
            'station': self.station.name,
            'period': f"{self.target_year}-{self.target_month:02d}",
            
            'method1_daily_sum': {
                'approach': 'Sum of individual daily energies',
                'total_monthly_energy_mwh': method1_total,
                'average_daily_energy_mwh': method1_avg_daily,
                'data_available': method1_total is not None
            },
            
            'method2_avg_discharge': {
                'approach': 'Average monthly discharge × 24 hours × days',
                'total_monthly_energy_mwh': method2_result.get('total_monthly_energy_mwh'),
                'daily_energy_mwh': method2_result.get('daily_energy_mwh'),
                'average_discharge_used': method2_result.get('average_monthly_discharge_m3s'),
                'monthly_power_mw': method2_result.get('monthly_power_mw'),
                'data_available': method2_result.get('data_completeness') == 'complete'
            }
        }
        
        # Calculate difference if both methods have results
        if (method1_total is not None and 
            method2_result.get('total_monthly_energy_mwh') is not None):
            
            difference = abs(method1_total - method2_result['total_monthly_energy_mwh'])
            percentage_diff = (difference / method1_total) * 100
            
            comparison['comparison'] = {
                'both_methods_available': True,
                'difference_mwh': difference,
                'percentage_difference': percentage_diff,
                'similar_results': percentage_diff < 5  # Within 5%
            }
        else:
            comparison['comparison'] = {
                'both_methods_available': False,
                'reason': 'One or both methods lack complete data'
            }
            
        return comparison
    
    def get_monthly_energy_summary(self):
        """Get comprehensive monthly energy summary using average discharge method"""
        return {
            'station_name': self.station.name,
            'station_id': str(self.station.id),
            'year': self.target_year,
            'month': self.target_month,
            'month_name': date(self.target_year, self.target_month, 1).strftime('%B'),
            
            # Energy statistics (calculated using average monthly discharge)
            'calculation_method': 'average_monthly_discharge',
            'total_monthly_energy_mwh': self.total_energy_mwh or 0,
            'daily_energy_from_avg_discharge_mwh': self.mean_energy_mwh or 0,
            'min_daily_energy_mwh': self.min_energy_mwh or 0,
            'max_daily_energy_mwh': self.max_energy_mwh or 0,
            'energy_std_deviation': self.std_energy_mwh or 0,
            
            # Discharge statistics (source data for energy calculation)
            'average_monthly_discharge_m3s': self.mean_discharge or 0,
            'min_daily_discharge_m3s': self.min_discharge or 0,
            'max_daily_discharge_m3s': self.max_discharge or 0,
            'discharge_std_deviation': self.std_discharge or 0,
            
            # Station parameters used in calculation
            'hydropower_parameters': {
                'efficiency': self.station.efficiency,
                'net_head_m': self.station.net_head,
                'max_discharge_for_energy_m3s': self.station.max_discharge_for_energy
            },
            
            # Metadata
            'total_daily_forecasts': self.total_daily_forecasts,
            'prediction_confidence': self.prediction_confidence or 0,
            'processing_status': self.processing_status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
    
    def get_daily_predictions_with_energy(self):
        """Get all daily predictions for this month with energy data"""
        first_day, last_day = self.get_month_date_range()
        
        return DischargePrediction.objects.filter(
            station=self.station,
            target_date__range=[first_day, last_day]
        ).values(
            'target_date',
            'predicted_discharge',
            'predicted_energy',
            'prediction_confidence',
            'processing_status'
        ).order_by('target_date')


class PipelineRun(models.Model):
    """Model for tracking automated pipeline executions"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    run_type = models.CharField(
        max_length=20,
        choices=[
            ('daily', 'Daily Update'),
            ('monthly', 'Monthly Forecast'),
            ('era5_download', 'ERA5 Download'),
            ('data_validation', 'Data Validation'),
            ('model_prediction', 'Model Prediction'),
            ('plot_generation', 'Plot Generation')
        ]
    )
    station = models.ForeignKey(DischargeStation, on_delete=models.CASCADE, related_name='pipeline_runs', null=True, blank=True)
    target_date = models.DateField(help_text="Target date for processing")
    
    # Execution status
    status = models.CharField(
        max_length=20,
        choices=[
            ('queued', 'Queued'),
            ('running', 'Running'),
            ('completed', 'Completed'),
            ('failed', 'Failed'),
            ('cancelled', 'Cancelled')
        ],
        default='queued'
    )
    
    # Timing
    scheduled_time = models.DateTimeField(help_text="When pipeline was scheduled to run")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True)
    
    # Results and logging
    processed_records = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    log_messages = models.JSONField(default=list, blank=True)
    output_files = models.JSONField(default=list, blank=True, help_text="Generated files (plots, data)")
    
    # Configuration
    parameters = models.JSONField(default=dict, blank=True, help_text="Run parameters")
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Pipeline Run"
        verbose_name_plural = "Pipeline Runs"
        ordering = ['-scheduled_time']

    def __str__(self):
        station_name = self.station.name if self.station else "All Stations"
        return f"{self.run_type} - {station_name} - {self.target_date} - {self.status}"

    def add_log(self, level, message):
        """Add log message to the run"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message
        }
        self.log_messages.append(log_entry)
        self.save()

    def mark_started(self):
        """Mark pipeline run as started"""
        self.status = 'running'
        self.started_at = datetime.now()
        self.save()

    def mark_completed(self):
        """Mark pipeline run as completed"""
        self.status = 'completed'
        self.completed_at = datetime.now()
        if self.started_at:
            duration = self.completed_at - self.started_at
            self.duration_seconds = int(duration.total_seconds())
        self.save()

    def mark_failed(self, error_message):
        """Mark pipeline run as failed"""
        self.status = 'failed'
        self.completed_at = datetime.now()
        if self.started_at:
            duration = self.completed_at - self.started_at
            self.duration_seconds = int(duration.total_seconds())
        self.add_log('ERROR', error_message)
        self.save()


class SensorReading(models.Model):
    """Model for storing real-time sensor telemetry data from discharge stations"""
    
    # Relationship to discharge station
    station = models.ForeignKey(
        DischargeStation, 
        on_delete=models.CASCADE, 
        related_name='sensor_readings',
        help_text="Station this sensor reading belongs to"
    )
    
    # Basic identification and timing
    record_id = models.CharField(
        max_length=50, 
        help_text="Sensor record ID or sequence number",
        blank=True, null=True
    )
    timestamp = models.DateTimeField(
        help_text="When the sensor reading was taken"
    )
    
    # Device/connectivity information
    device_username = models.CharField(
        max_length=100,
        help_text="Device authentication username",
        blank=True, null=True
    )
    device_id = models.CharField(
        max_length=50,
        help_text="Device/sensor identifier",
        blank=True, null=True
    )
    wifi_strength = models.IntegerField(
        help_text="WiFi signal strength in dBm",
        null=True, blank=True,
        validators=[MinValueValidator(-100), MaxValueValidator(0)]
    )
    ip_address = models.GenericIPAddressField(
        help_text="Device IP address",
        null=True, blank=True
    )
    device_status = models.IntegerField(
        help_text="Device operational status (1=active, 0=inactive)",
        default=1,
        validators=[MinValueValidator(0), MaxValueValidator(1)]
    )
    
    # Environmental sensor readings
    temperature = models.FloatField(
        help_text="Air temperature in degrees Celsius",
        null=True, blank=True,
        validators=[MinValueValidator(-50.0), MaxValueValidator(60.0)]
    )
    humidity = models.FloatField(
        help_text="Relative humidity percentage",
        null=True, blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(100.0)]
    )
    pressure = models.FloatField(
        help_text="Atmospheric pressure in hPa (hectopascals)",
        null=True, blank=True,
        validators=[MinValueValidator(800.0), MaxValueValidator(1100.0)]
    )
    air_quality = models.FloatField(
        help_text="Air quality index or measurement",
        null=True, blank=True,
        validators=[MinValueValidator(0.0)]
    )
    
    # Water/hydrological measurements
    water_depth = models.FloatField(
        help_text="Water depth measurement in meters or sensor units",
        null=True, blank=True,
        validators=[MinValueValidator(0.0)]
    )
    # GST (Ground Station Telemetry) specific discharge depth measurement.
    # This is read from the field device via the station's sensor_api_endpoint
    # and is distinct from the generic water_depth above.  Null when the device
    # did not report a value or the station has no GST device configured.
    discharge_depth = models.FloatField(
        help_text="GST discharge depth from ground station device (meters). "
                  "Null when not reported by the device.",
        null=True, blank=True,
        validators=[MinValueValidator(0.0)]
    )

    # GST water surface elevation (WSE) — computed as: 205300 - (835 - depth_cm)
    # Stored in cm (raw from pipeline). Divide by 100 to get meters.
    water_surface_elevation = models.FloatField(
        help_text="Water surface elevation in cm, computed from sensor depth using "
                  "station calibration constants. Null when not yet computed.",
        null=True, blank=True,
        validators=[MinValueValidator(0.0)]
    )

    # Electrical parameters from device
    solar_current = models.FloatField(
        help_text="Solar panel current in Amps",
        null=True, blank=True
    )
    load_current = models.FloatField(
        help_text="Load current in Amps",
        null=True, blank=True
    )

    # GPS coordinates (can differ from station location for mobile sensors)
    latitude = models.FloatField(
        help_text="Sensor latitude in decimal degrees",
        null=True, blank=True,
        validators=[MinValueValidator(-90.0), MaxValueValidator(90.0)]
    )
    longitude = models.FloatField(
        help_text="Sensor longitude in decimal degrees",
        null=True, blank=True,
        validators=[MinValueValidator(-180.0), MaxValueValidator(180.0)]
    )
    
    # Data quality and processing
    data_quality = models.CharField(
        max_length=20,
        choices=[
            ('excellent', 'Excellent'),
            ('good', 'Good'),
            ('fair', 'Fair'),
            ('poor', 'Poor'),
            ('invalid', 'Invalid')
        ],
        default='good',
        help_text="Quality assessment of sensor data"
    )
    is_validated = models.BooleanField(
        default=False,
        help_text="Has this reading been validated against other sources"
    )
    processing_status = models.CharField(
        max_length=20,
        choices=[
            ('raw', 'Raw Data'),
            ('processed', 'Processed'),
            ('calibrated', 'Calibrated'),
            ('error', 'Error')
        ],
        default='raw',
        help_text="Processing status of the sensor reading"
    )
    
    # Metadata
    notes = models.TextField(
        blank=True, null=True,
        help_text="Additional notes about this reading"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sensor Reading"
        verbose_name_plural = "Sensor Readings"
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['station', '-timestamp']),
            models.Index(fields=['timestamp']),
            models.Index(fields=['device_status']),
            models.Index(fields=['data_quality']),
        ]
        # Ensure unique readings per station per timestamp
        unique_together = ['station', 'timestamp', 'device_id']

    def __str__(self):
        return f"{self.station.name} - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - Temp: {self.temperature}°C"

    @property
    def coordinates(self):
        """Get sensor coordinates as (longitude, latitude) tuple"""
        if self.latitude is not None and self.longitude is not None:
            return (self.longitude, self.latitude)
        return None
    
    def get_environmental_summary(self):
        """Get a summary of environmental conditions"""
        return {
            'temperature_c': self.temperature,
            'humidity_percent': self.humidity,
            'pressure_hpa': self.pressure,
            'air_quality': self.air_quality,
            'water_depth': self.water_depth,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None
        }
    
    def validate_against_era5(self, era5_data=None):
        """
        Compare sensor readings with ERA5 weather data for validation
        Returns validation results and flags potential anomalies
        """
        if not era5_data:
            # Try to find ERA5 data for the same station and date
            try:
                era5_data = self.station.era5_data.filter(
                    date=self.timestamp.date()
                ).first()
            except:
                return {'error': 'No ERA5 data available for comparison'}
        
        if not era5_data:
            return {'error': 'No ERA5 data found for this date'}
        
        validation_results = {
            'timestamp': self.timestamp.isoformat(),
            'era5_date': era5_data.date.isoformat(),
            'comparisons': {},
            'anomalies': [],
            'overall_quality': 'unknown'
        }
        
        # Compare temperature (sensor in °C, ERA5 in °C)
        if self.temperature is not None and era5_data.temperature_2m is not None:
            temp_diff = abs(self.temperature - era5_data.temperature_2m)
            validation_results['comparisons']['temperature'] = {
                'sensor_value': self.temperature,
                'era5_value': era5_data.temperature_2m,
                'difference': temp_diff,
                'status': 'good' if temp_diff < 5.0 else 'anomaly'
            }
            if temp_diff > 10.0:
                validation_results['anomalies'].append(f"Large temperature difference: {temp_diff:.1f}°C")
        
        # Add humidity comparison if available (would need ERA5 humidity conversion)
        # For now, just flag extreme values
        if self.humidity is not None:
            if self.humidity < 10 or self.humidity > 95:
                validation_results['anomalies'].append(f"Extreme humidity: {self.humidity}%")
        
        # Flag overall quality
        anomaly_count = len(validation_results['anomalies'])
        if anomaly_count == 0:
            validation_results['overall_quality'] = 'excellent'
        elif anomaly_count <= 2:
            validation_results['overall_quality'] = 'good'
        else:
            validation_results['overall_quality'] = 'poor'
        
        return validation_results
    
    def calculate_discharge_correlation(self):
        """
        Attempt to correlate water depth with predicted discharge values
        Useful for model validation and calibration
        """
        if not self.water_depth:
            return None
        
        # Find discharge predictions for the same day
        try:
            predictions = self.station.predictions.filter(
                target_date=self.timestamp.date()
            )
            
            if predictions.exists():
                prediction = predictions.first()
                return {
                    'sensor_depth': self.water_depth,
                    'predicted_discharge': prediction.predicted_discharge,
                    'timestamp': self.timestamp.isoformat(),
                    'prediction_confidence': prediction.prediction_confidence,
                    'correlation_possible': True
                }
        except:
            pass
            
        return {'correlation_possible': False}
    
    @classmethod
    def get_recent_readings(cls, station, hours=24):
        """Get recent sensor readings for a station"""
        from django.utils import timezone
        cutoff_time = timezone.now() - timedelta(hours=hours)
        
        return cls.objects.filter(
            station=station,
            timestamp__gte=cutoff_time
        ).order_by('-timestamp')
    
    @classmethod
    def get_data_summary_for_station(cls, station, days=7):
        """Get summary statistics of sensor data for a station over the last N days"""
        from django.utils import timezone
        from django.db.models import Avg, Min, Max, Count
        
        cutoff_date = timezone.now().date() - timedelta(days=days)
        
        readings = cls.objects.filter(
            station=station,
            timestamp__date__gte=cutoff_date,
            data_quality__in=['excellent', 'good']
        )
        
        if not readings.exists():
            return {'error': f'No quality sensor data available for last {days} days'}
        
        summary = readings.aggregate(
            count=Count('id'),
            avg_temperature=Avg('temperature'),
            min_temperature=Min('temperature'),
            max_temperature=Max('temperature'),
            avg_humidity=Avg('humidity'),
            min_humidity=Min('humidity'),
            max_humidity=Max('humidity'),
            avg_pressure=Avg('pressure'),
            min_pressure=Min('pressure'),
            max_pressure=Max('pressure'),
            avg_water_depth=Avg('water_depth'),
            min_water_depth=Min('water_depth'),
            max_water_depth=Max('water_depth')
        )
        
        summary['station_name'] = station.name
        summary['period_days'] = days
        summary['latest_reading'] = readings.first().timestamp.isoformat() if readings.exists() else None
        
        return summary
