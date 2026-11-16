import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):
    """
    Adds two new optional data sources to the discharge_prediction schema:

    1. Google Sheets integration (DischargeStation)
       - google_sheets_id        : spreadsheet ID from the Google Sheets URL
       - google_sheets_tab       : optional tab / sheet name
       - sheets_date_column      : header of the date column (default 'date')
       - sheets_discharge_column : header of the discharge column (default 'discharge')
       - sheets_auto_sync        : enable daily automatic sync
       - sheets_last_synced_at   : timestamp of last successful sync
       - gst_depth_api_field     : JSON key in the GST API response for depth

    2. GST discharge depth (SensorReading)
       - discharge_depth : depth reading (m) from the ground-station telemetry
                          device, fetched via the station's sensor_api_endpoint.

    All new fields are nullable / have safe defaults so the system continues to
    operate normally when neither data source is configured.
    """

    dependencies = [
        ("discharge_prediction", "0011_add_soil_moisture_to_era5"),
    ]

    operations = [
        # ── Google Sheets configuration fields on DischargeStation ──────────
        migrations.AddField(
            model_name="dischargestation",
            name="google_sheets_id",
            field=models.CharField(
                blank=True,
                null=True,
                max_length=200,
                help_text=(
                    "Google Spreadsheet ID extracted from the sheet URL "
                    "(the long alphanumeric string between /d/ and /edit)"
                ),
            ),
        ),
        migrations.AddField(
            model_name="dischargestation",
            name="google_sheets_tab",
            field=models.CharField(
                blank=True,
                null=True,
                max_length=100,
                help_text=(
                    "Sheet/tab name inside the spreadsheet. "
                    "Leave blank to use the first visible tab."
                ),
            ),
        ),
        migrations.AddField(
            model_name="dischargestation",
            name="sheets_date_column",
            field=models.CharField(
                blank=True,
                max_length=50,
                default="date",
                help_text="Column header in the sheet that contains the date (YYYY-MM-DD or DD/MM/YYYY)",
            ),
        ),
        migrations.AddField(
            model_name="dischargestation",
            name="sheets_discharge_column",
            field=models.CharField(
                blank=True,
                max_length=50,
                default="discharge",
                help_text="Column header in the sheet that contains observed discharge in m\u00b3/s",
            ),
        ),
        migrations.AddField(
            model_name="dischargestation",
            name="sheets_auto_sync",
            field=models.BooleanField(
                default=False,
                help_text="Enable automatic daily sync of observed discharge from Google Sheets",
            ),
        ),
        migrations.AddField(
            model_name="dischargestation",
            name="sheets_last_synced_at",
            field=models.DateTimeField(
                blank=True,
                null=True,
                help_text="Timestamp of the last successful Google Sheets data sync",
            ),
        ),
        # ── GST API field name configuration on DischargeStation ────────────
        migrations.AddField(
            model_name="dischargestation",
            name="gst_depth_api_field",
            field=models.CharField(
                blank=True,
                max_length=100,
                default="water_depth",
                help_text=(
                    "JSON key name in the GST API response that holds the "
                    "discharge depth reading"
                ),
            ),
        ),
        # ── GST discharge depth measurement on SensorReading ────────────────
        migrations.AddField(
            model_name="sensorreading",
            name="discharge_depth",
            field=models.FloatField(
                blank=True,
                null=True,
                help_text=(
                    "GST discharge depth from ground station device (meters). "
                    "Null when not reported by the device."
                ),
                validators=[django.core.validators.MinValueValidator(0.0)],
            ),
        ),
    ]
