from django.contrib.gis.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
import uuid
import geopandas as gpd
from shapely.geometry import Polygon

class WatershedDelineation(models.Model):
    """Model to store watershed delineation results"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key = models.CharField(max_length=40, db_index=True)
    # Input parameters
    click_point = models.PointField(srid=4326)  # WGS84
    click_latitude = models.FloatField(
        validators=[MinValueValidator(26.0), MaxValueValidator(31.0)]
    )  # Nepal bounds
    click_longitude = models.FloatField(
        validators=[MinValueValidator(80.0), MaxValueValidator(89.0)]
    )  # Nepal bounds
    # Watershed results
    watershed_polygon = models.MultiPolygonField(srid=4326, null=True, blank=True)
    watershed_area_km2 = models.FloatField(null=True, blank=True)
    # Stream network info
    main_stream_length_km = models.FloatField(null=True, blank=True)
    stream_order = models.IntegerField(null=True, blank=True)
    drainage_density = models.FloatField(null=True, blank=True)
    # Elevation statistics
    area_below_3000m_km2 = models.FloatField(null=True, blank=True)
    area_below_3000m_percent = models.FloatField(null=True, blank=True)
    area_below_5000m_km2 = models.FloatField(null=True, blank=True)
    area_below_5000m_percent = models.FloatField(null=True, blank=True)
    # Processing metadata
    processing_time_seconds = models.FloatField(null=True, blank=True)
    success = models.BooleanField(default=False)
    error_message = models.TextField(blank=True, null=True)
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session_key', '-created_at']),
            models.Index(fields=['success']),
        ]

    def __str__(self):
        return f"Watershed {self.id} at ({self.click_latitude:.4f}, {self.click_longitude:.4f})"

    @property
    def coordinates(self):
        """Return coordinates as tuple"""
        return (self.click_longitude, self.click_latitude)

    @property
    def watershed_geojson(self):
        """Return watershed polygon as GeoJSON FeatureCollection, robust to Polygon/MultiPolygon/None."""
        if not self.watershed_polygon:
            return None
        try:
            from django.contrib.gis.geos import GEOSGeometry
            from shapely.geometry import shape, mapping, Polygon, MultiPolygon
            import json
            # Convert GEOSGeometry to GeoJSON dict
            geojson_str = self.watershed_polygon.geojson if hasattr(self.watershed_polygon, 'geojson') else self.watershed_polygon.json
            shapely_geom = shape(json.loads(geojson_str))
            if isinstance(shapely_geom, (Polygon, MultiPolygon)):
                return {
                    "type": "FeatureCollection",
                    "features": [{
                        "type": "Feature",
                        "geometry": mapping(shapely_geom),
                        "properties": {}
                    }]
                }
            else:
                return mapping(shapely_geom)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"Error converting watershed_polygon to GeoJSON: {e}")
            return None

class ProcessingLog(models.Model):
    """Model to log processing activities and errors"""
    watershed = models.ForeignKey(
        WatershedDelineation, 
        on_delete=models.CASCADE,
        related_name='processing_logs'
    )
    step = models.CharField(max_length=50)
    message = models.TextField()
    level = models.CharField(max_length=10, choices=[
        ('DEBUG', 'Debug'),
        ('INFO', 'Info'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
    ], default='INFO')
    timestamp = models.DateTimeField(auto_now_add=True)
    duration_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['timestamp']

    def __str__(self):
        return f"{self.watershed.id} - {self.step}: {self.level}"

class UserSession(models.Model):
    """Model to track user sessions and their watersheds"""
    session_key = models.CharField(max_length=40, unique=True, db_index=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    # Usage statistics
    total_watersheds = models.IntegerField(default=0)
    successful_watersheds = models.IntegerField(default=0)
    last_activity = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-last_activity']

    def __str__(self):
        return f"Session {self.session_key[:8]} - {self.total_watersheds} watersheds"

    def get_recent_watersheds(self, limit=10):
        """Get recent watersheds for this session"""
        return WatershedDelineation.objects.filter(
            session_key=self.session_key
        ).order_by('-created_at')[:limit]