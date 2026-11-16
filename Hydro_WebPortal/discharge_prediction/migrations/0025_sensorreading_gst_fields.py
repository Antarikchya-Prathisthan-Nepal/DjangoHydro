from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('discharge_prediction', '0024_dhm_meteo_station_and_record'),
    ]

    operations = [
        migrations.AddField(
            model_name='sensorreading',
            name='water_surface_elevation',
            field=models.FloatField(
                blank=True,
                help_text='Water surface elevation in cm, computed from sensor depth using station calibration constants. Null when not yet computed.',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='sensorreading',
            name='solar_current',
            field=models.FloatField(
                blank=True,
                help_text='Solar panel current in Amps',
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='sensorreading',
            name='load_current',
            field=models.FloatField(
                blank=True,
                help_text='Load current in Amps',
                null=True,
            ),
        ),
    ]
