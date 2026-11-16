#!/usr/bin/env python3
"""
Django Management Command: maintain_rolling_windows.py
Automated Rolling Window Maintenance for ERA5 Data

This command maintains 90-day rolling windows for all active stations.
It adds new data on the left and removes old data from the right.

Usage:
    python manage.py maintain_rolling_windows
    python manage.py maintain_rolling_windows --station-id 123
    python manage.py maintain_rolling_windows --dry-run
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import List, Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings
from django.utils import timezone

from discharge_prediction.models import DischargeStation, ERA5Data
from discharge_prediction.signals import (
    maintain_station_rolling_window,
    get_station_data_summary,
    check_all_stations_readiness
)


class Command(BaseCommand):
    help = 'Maintain 90-day rolling windows for ERA5 data'
    
    def add_arguments(self, parser):
        """Define command line arguments."""
        parser.add_argument(
            '--station-id',
            type=str,
            help='Maintain rolling window for specific station ID only'
        )
        
        parser.add_argument(
            '--station-name',
            type=str,
            help='Maintain rolling window for specific station name'
        )
        
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without actually doing it'
        )
        
        parser.add_argument(
            '--force-refresh',
            action='store_true',
            help='Force refresh all data for the station(s)'
        )
        
        parser.add_argument(
            '--check-status',
            action='store_true',
            help='Check and display status of all stations'
        )

    def handle(self, *args, **options):
        """Main command execution."""
        self.setup_logging()
        
        if options['check_status']:
            self.check_stations_status()
            return
        
        if options['dry_run']:
            self.stdout.write(self.style.WARNING("DRY RUN MODE - No changes will be made"))
        
        try:
            # Get stations to process
            stations = self.get_stations(options)
            
            self.stdout.write(f"Processing {len(stations)} stations...")
            
            for station in stations:
                self.process_station_rolling_window(station, options)
            
            self.stdout.write(
                self.style.SUCCESS(f'Successfully processed {len(stations)} stations')
            )
            
        except Exception as e:
            raise CommandError(f"Rolling window maintenance failed: {str(e)}")
    
    def setup_logging(self):
        """Setup logging for the command."""
        self.logger = logging.getLogger(__name__)
    
    def get_stations(self, options) -> List[DischargeStation]:
        """Get stations to process based on command options."""
        if options['station_id']:
            try:
                station = DischargeStation.objects.get(station_id=options['station_id'])
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
                self.stdout.write(self.style.WARNING(f"Multiple stations found:"))
                for station in stations:
                    self.stdout.write(f"  - {station.station_id}: {station.name}")
                raise CommandError("Multiple stations found. Use --station-id for specific selection")
        
        # Get all active stations
        stations = DischargeStation.objects.filter(is_active=True)
        if not stations.exists():
            raise CommandError("No active discharge stations found")
        
        return list(stations)
    
    def process_station_rolling_window(self, station: DischargeStation, options: dict):
        """Process rolling window for a specific station."""
        self.stdout.write(f"\\nProcessing station: {station.name} ({station.station_id})")
        
        # Get current data summary
        summary = get_station_data_summary(station)
        self.stdout.write(f"  Current data: {summary['total_days']} days")
        if summary['date_range']:
            self.stdout.write(f"  Date range: {summary['date_range']}")
        self.stdout.write(f"  Completeness: {summary['completeness']}%")
        self.stdout.write(f"  Ready for prediction: {summary['ready_for_prediction']}")
        
        if options['dry_run']:
            self.show_dry_run_plan(station)
            return
        
        if options['force_refresh']:
            self.force_refresh_station(station)
        else:
            self.maintain_normal_rolling_window(station)
    
    def show_dry_run_plan(self, station: DischargeStation):
        """Show what would be done in dry run mode."""
        today = datetime.now().date()
        era5_delay = 7
        latest_available = today - timedelta(days=era5_delay)
        
        # Check current data
        latest_data = ERA5Data.objects.filter(station=station).order_by('-date').first()
        oldest_data = ERA5Data.objects.filter(station=station).order_by('date').first()
        
        if latest_data:
            # Plan for new data download (append to right side)
            if latest_data.date < latest_available:
                start_download = latest_data.date + timedelta(days=1)
                days_to_download = (latest_available - start_download).days + 1
                self.stdout.write(f"  📥 Would append to right side: {start_download} to {latest_available} ({days_to_download} days)")
            else:
                self.stdout.write(f"  ✅ Data is up to date (latest: {latest_data.date})")
            
            # Plan for old data removal (remove from left side to maintain 90 days)
            all_data = ERA5Data.objects.filter(station=station).order_by('date')
            total_count = all_data.count()
            
            if total_count > 90:
                excess_count = total_count - 90
                self.stdout.write(f"  🗑️  Would remove {excess_count} oldest records from left side")
                if oldest_data:
                    self.stdout.write(f"      Oldest data to remove starts from: {oldest_data.date}")
            else:
                self.stdout.write(f"  ✅ Window size OK ({total_count}/90 days)")
        else:
            self.stdout.write(f"  🚨 No existing data - would download 90 days")
    
    def maintain_normal_rolling_window(self, station: DischargeStation):
        """Maintain normal rolling window for a station."""
        try:
            # Use the signal function for consistency
            maintain_station_rolling_window(station.id)
            
            # Get updated summary
            summary = get_station_data_summary(station)
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✅ Rolling window updated: {summary['total_days']} days maintained"
                )
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"  ❌ Error maintaining rolling window: {e}")
            )
    
    def force_refresh_station(self, station: DischargeStation):
        """Force refresh all data for a station."""
        self.stdout.write(f"  🔄 Force refreshing data for {station.name}...")
        
        try:
            # Delete existing data
            old_count = ERA5Data.objects.filter(station=station).count()
            if old_count > 0:
                ERA5Data.objects.filter(station=station).delete()
                self.stdout.write(f"  🗑️  Deleted {old_count} existing records")
            
            # Download fresh 90 days
            from django.core.management import call_command
            
            end_date = datetime.now().date() - timedelta(days=7)
            start_date = end_date - timedelta(days=89)
            
            self.stdout.write(f"  📥 Downloading fresh data: {start_date} to {end_date}")
            
            call_command(
                'download_era5_data',
                station_id=station.station_id,
                start_date=start_date.strftime('%Y-%m-%d'),
                end_date=end_date.strftime('%Y-%m-%d'),
                variables='all',
                verbosity=0  # Quiet mode
            )
            
            # Verify refresh
            new_count = ERA5Data.objects.filter(station=station).count()
            self.stdout.write(
                self.style.SUCCESS(f"  ✅ Force refresh completed: {new_count} records")
            )
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"  ❌ Force refresh failed: {e}")
            )
    
    def check_stations_status(self):
        """Check and display status of all stations."""
        self.stdout.write("\\n" + "="*60)
        self.stdout.write("STATION READINESS STATUS")
        self.stdout.write("="*60)
        
        readiness_report = check_all_stations_readiness()
        
        ready_count = 0
        total_count = len(readiness_report)
        
        for station_info in readiness_report:
            status_icon = "✅" if station_info['ready_for_prediction'] else "❌"
            
            self.stdout.write(f"\\n{status_icon} {station_info['station']} ({station_info['station_id']})")
            if station_info['coordinates']:
                lat, lon = station_info['coordinates']
                self.stdout.write(f"   📍 Coordinates: ({lat:.4f}, {lon:.4f})")
            
            if station_info['total_days'] > 0:
                self.stdout.write(f"   📊 Data: {station_info['total_days']} days")
                self.stdout.write(f"   📅 Range: {station_info['date_range']}")
                self.stdout.write(f"   📈 Completeness: {station_info['completeness']}%")
            else:
                self.stdout.write(f"   🚨 No ERA5 data available")
            
            if station_info['ready_for_prediction']:
                ready_count += 1
        
        # Summary
        self.stdout.write(f"\\n{'='*60}")
        self.stdout.write(f"SUMMARY: {ready_count}/{total_count} stations ready for predictions")
        
        if ready_count < total_count:
            self.stdout.write(f"\\n🔧 To fix non-ready stations, run:")
            self.stdout.write(f"   python manage.py maintain_rolling_windows --force-refresh")
        
        self.stdout.write("="*60)
