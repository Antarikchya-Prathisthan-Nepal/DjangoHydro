"""
Management command to clean up simulated data and prepare for real ERA5 data
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from discharge_prediction.models import DischargeStation, ERA5Data, DischargePrediction, ForecastSequence
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Clean up simulated data and prepare database for real ERA5 data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Confirm data deletion (required for safety)'
        )
        
        parser.add_argument(
            '--keep-stations',
            action='store_true',
            help='Keep discharge station metadata (recommended)'
        )
        
        parser.add_argument(
            '--data-type',
            type=str,
            choices=['all', 'era5', 'predictions', 'sequences'],
            default='all',
            help='Type of data to clean up'
        )
        
        parser.add_argument(
            '--station-name',
            type=str,
            help='Clean data for specific station only'
        )

    def handle(self, *args, **options):
        if not options['confirm']:
            self.stdout.write(
                self.style.ERROR(
                    'This command will delete data from the database. '
                    'Use --confirm to proceed.'
                )
            )
            return

        self.stdout.write(self.style.WARNING('🧹 Starting data cleanup...'))
        
        try:
            with transaction.atomic():
                self.cleanup_data(options)
                
        except Exception as e:
            raise CommandError(f"Data cleanup failed: {str(e)}")

    def cleanup_data(self, options):
        """Clean up specified data types."""
        station_filter = {}
        if options['station_name']:
            try:
                station = DischargeStation.objects.get(name__icontains=options['station_name'])
                station_filter['station'] = station
                self.stdout.write(f"Filtering for station: {station.name}")
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station '{options['station_name']}' not found")

        # Show current status
        self.show_current_status(station_filter)
        
        deleted_counts = {}
        
        if options['data_type'] in ['all', 'sequences']:
            count = ForecastSequence.objects.filter(**station_filter).count()
            if count > 0:
                ForecastSequence.objects.filter(**station_filter).delete()
                deleted_counts['ForecastSequence'] = count
                self.stdout.write(f"🗑️  Deleted {count} forecast sequences")

        if options['data_type'] in ['all', 'predictions']:
            count = DischargePrediction.objects.filter(**station_filter).count()
            if count > 0:
                DischargePrediction.objects.filter(**station_filter).delete()
                deleted_counts['DischargePrediction'] = count
                self.stdout.write(f"🗑️  Deleted {count} discharge predictions")

        if options['data_type'] in ['all', 'era5']:
            count = ERA5Data.objects.filter(**station_filter).count()
            if count > 0:
                ERA5Data.objects.filter(**station_filter).delete()
                deleted_counts['ERA5Data'] = count
                self.stdout.write(f"🗑️  Deleted {count} ERA5 data records")

        if options['data_type'] == 'all' and not options['keep_stations'] and not options['station_name']:
            count = DischargeStation.objects.count()
            if count > 0:
                DischargeStation.objects.all().delete()
                deleted_counts['DischargeStation'] = count
                self.stdout.write(f"🗑️  Deleted {count} discharge stations")

        # Show final status
        self.stdout.write(self.style.SUCCESS('\n✅ Cleanup completed successfully!'))
        self.show_cleanup_summary(deleted_counts)
        
        if options['keep_stations'] or options['station_name']:
            self.stdout.write(
                self.style.SUCCESS(
                    '\n🚀 Database is ready for real ERA5 data download!'
                )
            )

    def show_current_status(self, station_filter):
        """Show current database status before cleanup."""
        self.stdout.write('\n📊 CURRENT DATABASE STATUS:')
        self.stdout.write(f"   Stations: {DischargeStation.objects.count()}")
        self.stdout.write(f"   ERA5 Data: {ERA5Data.objects.filter(**station_filter).count()}")
        self.stdout.write(f"   Predictions: {DischargePrediction.objects.filter(**station_filter).count()}")
        self.stdout.write(f"   Sequences: {ForecastSequence.objects.filter(**station_filter).count()}")

    def show_cleanup_summary(self, deleted_counts):
        """Show summary of deleted data."""
        if deleted_counts:
            self.stdout.write('\n📈 CLEANUP SUMMARY:')
            for model_name, count in deleted_counts.items():
                self.stdout.write(f"   {model_name}: {count} records deleted")
        else:
            self.stdout.write('\n💡 No data was deleted (nothing to clean up)')
