"""
Data migration 0017:
  1. Copy existing discharge / discharge_max / discharge_min values
     (which are raw DHM stage heights H in metres) into the new
     stage_height / stage_height_max / stage_height_min fields.
  2. Set discharge / discharge_max / discharge_min to NULL temporarily
     (they will be recomputed once rating-curve parameters are loaded
     via the management command or Django admin).

Run after applying migration 0016.
"""

from django.db import migrations


def copy_discharge_to_stage(apps, schema_editor):
    DischargeRecord = apps.get_model('discharge_prediction', 'DischargeRecord')
    updated = 0
    for record in DischargeRecord.objects.all():
        record.stage_height     = record.discharge
        record.stage_height_max = record.discharge_max
        record.stage_height_min = record.discharge_min
        # Nullify computed fields; they will be recomputed once rating
        # curve parameters are set on the station.
        record.discharge     = None
        record.discharge_max = None
        record.discharge_min = None
        record.save(update_fields=[
            'stage_height', 'stage_height_max', 'stage_height_min',
            'discharge', 'discharge_max', 'discharge_min',
        ])
        updated += 1
    print(f"\n  Copied H values to stage_height for {updated} records."
          " Run management command to recompute Q2 once rating curve is set.")


def reverse_migration(apps, schema_editor):
    """Restore discharge from stage_height on rollback."""
    DischargeRecord = apps.get_model('discharge_prediction', 'DischargeRecord')
    for record in DischargeRecord.objects.all():
        record.discharge     = record.stage_height
        record.discharge_max = record.stage_height_max
        record.discharge_min = record.stage_height_min
        record.save(update_fields=['discharge', 'discharge_max', 'discharge_min'])


class Migration(migrations.Migration):

    dependencies = [
        ('discharge_prediction', '0016_add_stage_height_and_rating_curve'),
    ]

    operations = [
        migrations.RunPython(copy_discharge_to_stage, reverse_code=reverse_migration),
    ]
