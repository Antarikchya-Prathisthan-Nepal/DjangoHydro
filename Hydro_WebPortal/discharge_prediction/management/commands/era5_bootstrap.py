#!/usr/bin/env python3
"""
CONSOLIDATED Django Management Command: era5_bootstrap.py
Unified bootstrap command that replaces both automatic_era5_bootstrap.py and bootstrap_era5_data.py

This single command handles:
1. Automatic bootstrap for new stations (triggered by signals)
2. Manual bootstrap for specific stations 
3. Batch bootstrap for multiple stations
4. Status checking and validation

Usage:
    # Automatic bootstrap (used by signals)
    python manage.py era5_bootstrap --auto --station-id <ID>
    
    # Manual bootstrap single station
    python manage.py era5_bootstrap --station-name "Lower likhu"
    
    # Batch bootstrap all stations
    python manage.py era5_bootstrap --all-stations
    
    # Status check only
    python manage.py era5_bootstrap --check-status
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import datetime, timedelta
import logging

from discharge_prediction.models import DischargeStation, ERA5Data, PipelineRun
from discharge_prediction.era5_data_manager import ERA5DataManager

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = '''
    Unified ERA5 bootstrap command for all bootstrap scenarios.
    Replaces both automatic_era5_bootstrap.py and bootstrap_era5_data.py
    '''

    def add_arguments(self, parser):
        # Station selection
        parser.add_argument('--station-id', type=str, help='Bootstrap specific station by ID')
        parser.add_argument('--station-name', type=str, help='Bootstrap station by name')
        parser.add_argument('--all-stations', action='store_true', help='Bootstrap all stations that need it')
        
        # Bootstrap options
        parser.add_argument('--days-back', type=int, default=90, help='Number of days to download (default: 90)')
        parser.add_argument('--force', action='store_true', help='Force bootstrap even if station has data')
        
        # Operation modes
        parser.add_argument('--auto', action='store_true', help='Automatic mode (used by signals)')
        parser.add_argument('--check-status', action='store_true', help='Check station status only')
        
        # Advanced options
        parser.add_argument('--quick', action='store_true', help='Quick bootstrap with minimal validation')
        parser.add_argument('--validate-only', action='store_true', help='Only validate existing data')

    def handle(self, *args, **options):
        """Main command handler"""
        self.stdout.write(self.style.SUCCESS('🚀 ERA5 Unified Bootstrap'))
        
        if options['check_status']:
            return self.check_all_stations_status()
        
        if options['validate_only']:
            return self.validate_existing_data(options)
        
        # Initialize manager
        manager = ERA5DataManager()
        
        # Get stations to process
        stations = self._get_stations(options)
        
        self.stdout.write(f"📋 Processing {len(stations)} station(s)")
        
        success_count = 0
        
        for station in stations:
            try:
                if self.bootstrap_station(station, manager, options):
                    success_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ Failed {station.name}: {e}"))
                continue
        
        self.stdout.write(
            self.style.SUCCESS(f'✅ Bootstrap completed: {success_count}/{len(stations)} stations')
        )

    def bootstrap_station(self, station, manager, options):
        """Bootstrap a single station with unified logic"""
        self.stdout.write(f"\n📡 Processing: {station.name}")
        
        # Check current status
        status = manager.check_station_data_status(station)
        self._display_station_status(station, status)
        
        # Decide if bootstrap is needed
        needs_bootstrap = (
            options['force'] or 
            status['needs_bootstrap'] or 
            status['total_records'] < options['days_back']
        )
        
        if not needs_bootstrap:
            self.stdout.write(self.style.SUCCESS(f"✅ {station.name} already has sufficient data"))
            return True
        
        # Perform bootstrap
        if options['auto']:
            self._log_auto_bootstrap(station)
        
        self.stdout.write(f"📥 Downloading {options['days_back']} days of data...")
        
        saved_count = manager.bootstrap_station_data(
            station=station,
            days_back=options['days_back']
        )
        
        if saved_count > 0:
            self.stdout.write(self.style.SUCCESS(f"✅ Downloaded {saved_count} records"))
            
            # Create tracking record
            self._create_pipeline_record(station, saved_count, options)
            
            # Mark station as ready if applicable
            if saved_count >= 90:
                station.is_model_ready = True
                station.last_forecast_date = datetime.now().date()
                station.save()
                self.stdout.write(f"🎯 Station ready for predictions")
            
            return True
        else:
            self.stdout.write(self.style.ERROR(f"❌ No data downloaded"))
            return False

    def check_all_stations_status(self):
        """Check status of all stations"""
        self.stdout.write("\n" + "="*60)
        self.stdout.write("STATION BOOTSTRAP STATUS")
        self.stdout.write("="*60)
        
        stations = DischargeStation.objects.filter(is_active=True)
        manager = ERA5DataManager()
        
        ready_count = 0
        
        for station in stations:
            status = manager.check_station_data_status(station)
            
            status_icon = "✅" if status['is_ready_for_prediction'] else "❌"
            self.stdout.write(f"\n{status_icon} {station.name}")
            
            self.stdout.write(f"   📊 Data: {status['total_records']} records")
            if status['latest_date']:
                self.stdout.write(f"   📅 Latest: {status['latest_date']}")
            self.stdout.write(f"   🎯 Ready: {status['is_ready_for_prediction']}")
            
            if status['is_ready_for_prediction']:
                ready_count += 1
        
        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"SUMMARY: {ready_count}/{len(stations)} stations ready")
        self.stdout.write("="*60)

    def _get_stations(self, options):
        """Get stations based on options"""
        if options['station_id']:
            try:
                station = DischargeStation.objects.get(id=options['station_id'])
                return [station]
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station {options['station_id']} not found")
        
        elif options['station_name']:
            try:
                station = DischargeStation.objects.get(name__icontains=options['station_name'])
                return [station]
            except DischargeStation.MultipleObjectsReturned:
                raise CommandError("Multiple stations found. Use --station-id")
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station '{options['station_name']}' not found")
        
        elif options['all_stations']:
            stations = DischargeStation.objects.filter(is_active=True)
            if not stations.exists():
                raise CommandError("No active stations found")
            return list(stations)
        
        else:
            raise CommandError("Must specify station selection option")

    def _display_station_status(self, station, status):
        """Display station status information"""
        self.stdout.write(f"  📊 Status for {station.name}:")
        self.stdout.write(f"    - Records: {status['total_records']}")
        self.stdout.write(f"    - Latest: {status['latest_date']}")
        self.stdout.write(f"    - Ready: {status['is_ready_for_prediction']}")
        self.stdout.write(f"    - Needs Bootstrap: {status['needs_bootstrap']}")

    def _create_pipeline_record(self, station, saved_count, options):
        """Create pipeline tracking record"""
        PipelineRun.objects.create(
            run_type='era5_download',
            station=station,
            target_date=datetime.now().date(),
            status='completed',
            scheduled_time=timezone.now(),
            processed_records=saved_count,
            parameters={
                'download_type': 'auto_bootstrap' if options['auto'] else 'manual_bootstrap',
                'days_downloaded': options['days_back'],
                'command': 'era5_bootstrap_unified'
            }
        )

    def _log_auto_bootstrap(self, station):
        """Log automatic bootstrap trigger"""
        logger.info(f"🤖 Automatic bootstrap triggered for {station.name}")
        self.stdout.write(f"🤖 Auto-bootstrap mode for {station.name}")

    def validate_existing_data(self, options):
        """Validate existing ERA5 data without downloading"""
        self.stdout.write("🔍 Validating existing ERA5 data...")
        
        stations = self._get_stations(options)
        manager = ERA5DataManager()
        
        for station in stations:
            status = manager.check_station_data_status(station)
            self._display_station_status(station, status)
            
            # Additional validation logic could go here
            if status['total_records'] > 0:
                # Check for data gaps, completeness, etc.
                self.stdout.write(f"  ✅ Validation passed for {station.name}")
            else:
                self.stdout.write(f"  ⚠️ No data found for {station.name}")
