from django.conf import settings
from django.db import models


class WatershedReport(models.Model):
    user       = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='watershed_reports',
    )
    name       = models.CharField(max_length=200, blank=True, default='')
    geometry   = models.JSONField()   # GeoJSON geometry (Polygon/MultiPolygon)
    results    = models.JSONField()   # Full analysis output dict
    area_km2   = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def display_name(self):
        return self.name or f'Report #{self.pk}'

    def __str__(self):
        return f'{self.user} — {self.display_name()} ({self.created_at:%Y-%m-%d})'
