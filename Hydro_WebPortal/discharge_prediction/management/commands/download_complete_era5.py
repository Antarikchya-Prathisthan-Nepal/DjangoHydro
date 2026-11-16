#!/usr/bin/env python3
"""
Django Management Command: download_complete_era5.py
Downloads surface and pressure ERA5 data and saves to database
"""

import logging
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from discharge_prediction.models import DischargeStation
from discharge_prediction.era5_utils import create_era5_downloader

# Setup logging
logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Download complete ERA5 data (surface + pressure) and save to database'
    
    def add_arguments(self, parser):
        """Define command line arguments."""
        parser.add_argument(
            '--station-name',
            type=str,
            help='Station name to download data for'
        )
        
        parser.add_argument(
            '--station-id',
            type=str,
            help='Station UUID to download data for'
        )
        
        parser.add_argument(
            '--start-date',
            type=str,
            help='Start date (YYYY-MM-DD)'
        )
        
        parser.add_argument(
            '--end-date',
            type=str,
            help='End date (YYYY-MM-DD)'
        )
        
        parser.add_argument(
            '--days-back',
            type=int,
            default=7,
            help='Number of days back from today to download (default: 7)'
        )
        
        parser.add_argument(
            '--all-stations',
            action='store_true',
            help='Download data for all active stations'
        )
        
    def handle(self, *args, **options):
        """Main command handler"""
        try:
            # Setup logging
            logging.basicConfig(
                level=logging.INFO,
                format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            
            # Get date range
            start_date, end_date = self._get_date_range(options)
            
            # Get stations to process
            stations = self._get_stations(options)
            
            # Initialize downloader using the unified factory
            downloader = create_era5_downloader('complete')
            
            total_saved = 0
            
            # Process each station
            for station in stations:
                try:
                    self.stdout.write(
                        self.style.SUCCESS(f"🚀 Processing station: {station.name}")
                    )
                    
                    saved_count = downloader.download_and_save_era5_data(
                        station, start_date, end_date
                    )
                    
                    total_saved += saved_count
                    
                    self.stdout.write(
                        self.style.SUCCESS(f"✅ Saved {saved_count} records for {station.name}")
                    )
                    
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"❌ Failed for {station.name}: {e}")
                    )
                    continue
            
            self.stdout.write(
                self.style.SUCCESS(f"🎉 Completed! Total records saved: {total_saved}")
            )
            
        except Exception as e:
            raise CommandError(f"Command failed: {e}")
    
    def _get_date_range(self, options):
        """Get start and end dates from options"""
        if options['start_date'] and options['end_date']:
            start_date = datetime.strptime(options['start_date'], '%Y-%m-%d')
            end_date = datetime.strptime(options['end_date'], '%Y-%m-%d')
        else:
            # Use days_back from today
            end_date = datetime.now() - timedelta(days=1)  # Yesterday
            start_date = end_date - timedelta(days=options['days_back'])
        
        self.stdout.write(f"📅 Date range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
        return start_date, end_date
    
    def _get_stations(self, options):
        """Get stations to process based on options"""
        if options['station_id']:
            try:
                station = DischargeStation.objects.get(id=options['station_id'])
                return [station]
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station with ID {options['station_id']} not found")
                
        elif options['station_name']:
            try:
                station = DischargeStation.objects.get(name__icontains=options['station_name'])
                return [station]
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station with name '{options['station_name']}' not found")
            except DischargeStation.MultipleObjectsReturned:
                stations = DischargeStation.objects.filter(name__icontains=options['station_name'])
                self.stdout.write("Multiple stations found:")
                for station in stations:
                    self.stdout.write(f"  - {station.id}: {station.name}")
                raise CommandError("Multiple stations found. Use --station-id for specific selection")
        
        elif options['all_stations']:
            stations = DischargeStation.objects.filter(is_active=True)
            if not stations.exists():
                raise CommandError("No active stations found")
            return list(stations)
        
        else:
            raise CommandError("Must specify --station-name, --station-id, or --all-stations")
        
        return list(stations)
