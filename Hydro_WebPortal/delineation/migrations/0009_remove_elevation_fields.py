from django.db import migrations

class Migration(migrations.Migration):
    """
    This migration removes all elevation-related fields from the WatershedDelineation model.
    """
    dependencies = [
        ('delineation', '0008_merge_20250915_1444'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='elevation_thresholds_data',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='min_elevation_m',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='max_elevation_m',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='mean_elevation_m',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='median_elevation_m',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='std_elevation_m',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='area_below_3000m_km2',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='area_below_3000m_percent',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='area_below_5000m_km2',
        ),
        migrations.RemoveField(
            model_name='watersheddelineation',
            name='area_below_5000m_percent',
        ),
    ]
