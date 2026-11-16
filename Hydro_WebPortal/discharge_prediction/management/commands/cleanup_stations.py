"""
Management command to remove all discharge stations and related data from the database
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from discharge_prediction.models import (
    DischargeStation, DischargeRecord, DischargePrediction,
    ERA5Data, ForecastSequence, MonthlyForecast, PipelineRun
)
import os


class Command(BaseCommand):
    help = 'Remove all discharge stations and related data from the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm deletion without prompting',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be deleted without actually deleting',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        confirm = options['confirm']

        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE - No data will be deleted')
            )

        # Count existing data
        station_count = DischargeStation.objects.count()
        record_count = DischargeRecord.objects.count()
        prediction_count = DischargePrediction.objects.count()
        era5_count = ERA5Data.objects.count()
        sequence_count = ForecastSequence.objects.count()
        monthly_count = MonthlyForecast.objects.count()
        pipeline_count = PipelineRun.objects.count()

        self.stdout.write(f"\nCurrent database contents:")
        self.stdout.write(f"  • Discharge Stations: {station_count}")
        self.stdout.write(f"  • Discharge Records: {record_count}")
        self.stdout.write(f"  • Predictions: {prediction_count}")
        self.stdout.write(f"  • ERA5 Data: {era5_count}")
        self.stdout.write(f"  • Forecast Sequences: {sequence_count}")
        self.stdout.write(f"  • Monthly Forecasts: {monthly_count}")
        self.stdout.write(f"  • Pipeline Runs: {pipeline_count}")

        total_records = (station_count + record_count + prediction_count + 
                        era5_count + sequence_count + monthly_count + pipeline_count)

        if total_records == 0:
            self.stdout.write(
                self.style.SUCCESS('\nDatabase is already clean - no data to remove')
            )
            return

        if not dry_run:
            if not confirm:
                self.stdout.write(
                    self.style.WARNING(
                        f'\nThis will permanently delete {total_records} records from the database!'
                    )
                )
                response = input('Are you sure you want to continue? (yes/no): ')
                if response.lower() != 'yes':
                    self.stdout.write(self.style.ERROR('Operation cancelled'))
                    return

            self.stdout.write('\nStarting cleanup...')

            try:
                with transaction.atomic():
                    # Delete in order to respect foreign key constraints
                    deleted_pipeline = PipelineRun.objects.all().delete()[0]
                    deleted_monthly = MonthlyForecast.objects.all().delete()[0]
                    deleted_sequences = ForecastSequence.objects.all().delete()[0]
                    deleted_predictions = DischargePrediction.objects.all().delete()[0]
                    deleted_records = DischargeRecord.objects.all().delete()[0]
                    deleted_era5 = ERA5Data.objects.all().delete()[0]
                    deleted_stations = DischargeStation.objects.all().delete()[0]

                    self.stdout.write(
                        self.style.SUCCESS(f'\nSuccessfully deleted:')
                    )
                    self.stdout.write(f"  ✓ {deleted_stations} Discharge Stations")
                    self.stdout.write(f"  ✓ {deleted_records} Discharge Records")
                    self.stdout.write(f"  ✓ {deleted_predictions} Predictions")
                    self.stdout.write(f"  ✓ {deleted_era5} ERA5 Data records")
                    self.stdout.write(f"  ✓ {deleted_sequences} Forecast Sequences")
                    self.stdout.write(f"  ✓ {deleted_monthly} Monthly Forecasts")
                    self.stdout.write(f"  ✓ {deleted_pipeline} Pipeline Runs")

                    # Also clean up any model files if they exist
                    model_dir = 'models'
                    if os.path.exists(model_dir):
                        self.stdout.write(f"\nModel directory exists at: {model_dir}")
                        self.stdout.write("Note: Model files are not automatically deleted.")
                        self.stdout.write("You may want to clean them manually if needed.")

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'Error during cleanup: {str(e)}')
                )
                raise

        else:
            self.stdout.write(
                self.style.WARNING(f'\nDRY RUN: Would delete {total_records} records')
            )

        self.stdout.write(
            self.style.SUCCESS('\nDatabase cleanup completed successfully!')
        )
        self.stdout.write(
            '\nYou can now add new discharge stations and test the pipeline.'
        )
