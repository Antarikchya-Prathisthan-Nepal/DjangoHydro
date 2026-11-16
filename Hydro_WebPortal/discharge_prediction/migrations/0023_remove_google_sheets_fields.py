from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('discharge_prediction', '0022_add_dhmstage_discharge_q2'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='dischargestation',
            name='google_sheets_id',
        ),
        migrations.RemoveField(
            model_name='dischargestation',
            name='google_sheets_tab',
        ),
        migrations.RemoveField(
            model_name='dischargestation',
            name='sheets_date_column',
        ),
        migrations.RemoveField(
            model_name='dischargestation',
            name='sheets_discharge_column',
        ),
        migrations.RemoveField(
            model_name='dischargestation',
            name='sheets_auto_sync',
        ),
        migrations.RemoveField(
            model_name='dischargestation',
            name='sheets_last_synced_at',
        ),
    ]
