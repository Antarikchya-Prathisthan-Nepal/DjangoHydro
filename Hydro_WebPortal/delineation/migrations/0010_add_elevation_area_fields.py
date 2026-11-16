from django.db import migrations, models

class Migration(migrations.Migration):
    """
    This migration adds back the elevation area fields to the WatershedDelineation model.
    """
    dependencies = [
        ('delineation', '0009_remove_elevation_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='watersheddelineation',
            name='area_below_3000m_km2',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='watersheddelineation',
            name='area_below_3000m_percent',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='watersheddelineation',
            name='area_below_5000m_km2',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='watersheddelineation',
            name='area_below_5000m_percent',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
