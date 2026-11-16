#!/usr/bin/env python3
"""
Django Management Command: download_era5_data.py
Automated ERA5 Data Download Pipeline

This command downloads ERA5 reanalysis data for discharge prediction stations,
updates station coordinates based on discharge information, and integrates with the Django application.

Usage:
    python manage.py download_era5_data --date-range 30 --variables all
    python manage.py download_era5_data --start-date 2024-01-01 --end-date 2024-01-31
    python manage.py download_era5_data --station-id 123 --force-update
"""
import os
import sys
import logging
from datetime import datetime, timedelta, date
from typing import List, Optional, Dict, Any
from pathlib import Path
import uuid
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.conf import settings
from django.utils import timezone

from discharge_prediction.models import DischargeStation, ERA5Data, PipelineRun
from discharge_prediction.era5_utils import ERA5Downloader


class Command(BaseCommand):
    help = 'Download ERA5 data for discharge prediction stations'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_logging()
        self.downloader = None
        self.pipeline_run = None
        
    def setup_logging(self):
        """Setup logging configuration for ERA5 download operations."""
        log_dir = Path(settings.BASE_DIR) / 'logs' / 'era5'
        log_dir.mkdir(parents=True, exist_ok=True)
        
        log_file = log_dir / f'era5_download_{datetime.now().strftime("%Y%m%d")}.log'
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

    def add_arguments(self, parser):
        """Define command line arguments."""
        parser.add_argument('--start-date', type=str, help='Start date for ERA5 download (YYYY-MM-DD format)')
        parser.add_argument('--end-date', type=str, help='End date for ERA5 download (YYYY-MM-DD format)')
        parser.add_argument('--date-range', type=int, default=30, help='Number of days back from today to download (default: 30)')
        parser.add_argument('--station-id', type=str, help='Download data for specific station ID (UUID) only')
        parser.add_argument('--station-name', type=str, help='Download data for specific station name only')
        parser.add_argument('--variables', type=str, default='all', choices=['all', 'surface', 'pressure', 'temperature', 'precipitation', 'wind'], help='ERA5 variables to download')
        parser.add_argument('--force-update', action='store_true', help='Force re-download even if data already exists')
        parser.add_argument('--dry-run', action='store_true', help='Show what would be downloaded without actually downloading')
        parser.add_argument('--simulate', action='store_true', help='Use simulation mode to generate test data')

    def handle(self, *args, **options):
        """Main command execution."""
        try:
            self.logger.info("Starting ERA5 data download pipeline")
            
            # Create PipelineRun record
            self.pipeline_run = PipelineRun.objects.create(
                id=uuid.uuid4(),
                station_id=None,
                run_type='download_era5_data',
                target_date=date.today(),
                status='running',
                scheduled_time=timezone.now(),
                started_at=timezone.now(),
                log_messages=[]
            )
            
            # Initialize ERA5 downloader
            simulate_mode = options.get('simulate', False)
            self.downloader = ERA5Downloader(simulate_mode=simulate_mode)
            
            if simulate_mode:
                self.stdout.write(self.style.WARNING("SIMULATION MODE - Using generated test data"))
            
            # Parse date range with validation
            start_date, end_date = self.parse_date_range(options)
            
            # Get stations to process
            stations = self.get_stations(options)
            if options['station_id'] or options['station_name']:
                self.pipeline_run.station_id = stations[0].id
            
            # Get variables to download
            variables = self.get_variables(options)
            
            self.logger.info(f"Processing {len(stations)} stations from {start_date} to {end_date}")
            self.logger.info(f"Variables: {variables}")
            
            if options['dry_run']:
                self.dry_run_summary(stations, start_date, end_date, variables)
                self.pipeline_run.status = 'completed'
                self.pipeline_run.completed_at = timezone.now()
                self.pipeline_run.log_messages = json.dumps([f"Dry run: {len(stations)} stations, {start_date} to {end_date}"])
                self.pipeline_run.save()
                return
            
            # Download data for each station
            total_downloaded = 0
            total_errors = 0
            log_messages = []
            
            for station in stations:
                try:
                    downloaded_count = self.download_station_data(
                        station, start_date, end_date, variables, options
                    )
                    total_downloaded += downloaded_count
                    log_messages.append(f"Downloaded {downloaded_count} records for {station.name}")
                except Exception as e:
                    self.logger.error(f"Error processing station {station.name}: {str(e)}")
                    log_messages.append(f"Error for {station.name}: {str(e)}")
                    total_errors += 1
                    continue
            
            # Update PipelineRun
            self.pipeline_run.processed_records = total_downloaded
            self.pipeline_run.status = 'completed' if total_errors == 0 else 'failed'
            self.pipeline_run.completed_at = timezone.now()
            self.pipeline_run.log_messages = json.dumps(log_messages)
            self.pipeline_run.save()
            
            # Summary
            self.logger.info(f"Download complete: {total_downloaded} records downloaded, {total_errors} errors")
            self.stdout.write(self.style.SUCCESS(f'Successfully downloaded {total_downloaded} ERA5 records for {len(stations)} stations'))
            
        except Exception as e:
            self.logger.error(f"Fatal error in ERA5 download pipeline: {str(e)}")
            if self.pipeline_run:
                self.pipeline_run.status = 'failed'
                self.pipeline_run.log_messages = json.dumps([f"Fatal error: {str(e)}"])
                self.pipeline_run.completed_at = timezone.now()
                self.pipeline_run.save()
            raise CommandError(f"ERA5 download failed: {str(e)}")

    def parse_date_range(self, options) -> tuple:
        """Parse and validate date range options."""
        max_date = date.today() - timedelta(days=7)
        
        if options['start_date'] and options['end_date']:
            try:
                start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
                end_date = datetime.strptime(options['end_date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError("Invalid date format. Use YYYY-MM-DD")
        elif options['start_date']:
            try:
                start_date = datetime.strptime(options['start_date'], '%Y-%m-%d').date()
                end_date = max_date
            except ValueError:
                raise CommandError("Invalid start date format. Use YYYY-MM-DD")
        else:
            end_date = max_date
            start_date = end_date - timedelta(days=options['date_range'] - 1)
        
        if start_date > end_date:
            raise CommandError("Start date must be before end date")
        
        if end_date > max_date:
            raise CommandError(f"End date {end_date} exceeds maximum allowed date {max_date} (ERA5 delay)")
        
        if start_date > max_date:
            raise CommandError(f"Start date {start_date} exceeds maximum allowed date {max_date} (ERA5 delay)")
        
        return start_date, end_date

    def get_stations(self, options) -> List[DischargeStation]:
        """Get stations to process based on command options."""
        if options['station_id']:
            sid = options['station_id']
            # Try integer station_id field first, then fall back to UUID pk
            try:
                if sid.isdigit():
                    station = DischargeStation.objects.get(station_id=int(sid))
                else:
                    station = DischargeStation.objects.get(id=sid)
                return [station]
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station with ID {sid} not found")
                
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
        
        stations = DischargeStation.objects.filter(is_active=True)
        if not stations.exists():
            raise CommandError("No active discharge stations found")
            
        return list(stations)

    def get_variables(self, options) -> List[str]:
        """Get ERA5 variables to download based on options."""
        variable_map = {
            'all': ['2m_temperature', 'total_precipitation', '10m_u_component_of_wind',
                   '10m_v_component_of_wind', 'specific_humidity', 'volumetric_soil_water_layer_1'],
            'surface': ['2m_temperature', 'total_precipitation', '10m_u_component_of_wind',
                       '10m_v_component_of_wind', 'volumetric_soil_water_layer_1'],
            'pressure': ['specific_humidity'],
            'temperature': ['2m_temperature'],
            'precipitation': ['total_precipitation'],
            'wind': ['10m_u_component_of_wind', '10m_v_component_of_wind']
        }
        
        return variable_map.get(options['variables'], variable_map['all'])

    def download_station_data(self, station: DischargeStation, start_date, end_date,
                            variables: List[str], options: Dict[str, Any]) -> int:
        """
        Download ERA5 data for a station in 7-day chunks, saving each chunk to the DB
        immediately after download.  This ensures partial progress is preserved if the
        process is interrupted, and the admin will show data growing chunk-by-chunk.
        """
        import traceback
        longitude, latitude = station.location.coords
        self.logger.info(f"Processing station: {station.name} ({latitude}, {longitude})")
        force_update = options.get('force_update', False)

        total_days = (end_date - start_date).days + 1
        downloaded_count = 0
        chunk_size = 7  # match era5_utils 7-day CDS limit

        chunk_start = start_date
        while chunk_start <= end_date:
            chunk_end = min(end_date, chunk_start + timedelta(days=chunk_size - 1))

            # Check which dates in this chunk already exist in DB
            if not force_update:
                existing_in_chunk = set(
                    ERA5Data.objects.filter(station=station, date__range=[chunk_start, chunk_end])
                    .values_list('date', flat=True)
                )
                chunk_days = (chunk_end - chunk_start).days + 1
                if len(existing_in_chunk) >= chunk_days:
                    self.logger.info(f"Chunk {chunk_start} -> {chunk_end}: all {chunk_days} days already in DB, skipping")
                    chunk_start = chunk_end + timedelta(days=1)
                    continue
            else:
                existing_in_chunk = set()

            # Download this single chunk from CDS
            self.logger.info(f"Downloading chunk {chunk_start} -> {chunk_end} for {station.name}")
            try:
                chunk_data = self.downloader.download_for_station(
                    station=station,
                    start_date=chunk_start,
                    end_date=chunk_end,
                    variables=variables,
                )
            except Exception as e:
                self.logger.error(f"Error downloading chunk {chunk_start}->{chunk_end} for {station.name}: {e}")
                self.logger.error(traceback.format_exc())
                chunk_start = chunk_end + timedelta(days=1)
                continue

            if not chunk_data:
                self.logger.warning(f"No data returned for chunk {chunk_start}->{chunk_end} for {station.name}")
                chunk_start = chunk_end + timedelta(days=1)
                continue

            # Save each day in this chunk immediately
            for date_str, day_data in sorted(chunk_data.items()):
                try:
                    current_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    self.logger.warning(f"Skipping invalid date key: {date_str}")
                    continue

                if current_date < start_date or current_date > end_date:
                    continue
                if not force_update and current_date in existing_in_chunk:
                    self.logger.debug(f"Already exists: {station.name} {current_date}, skipping")
                    continue

                check_fields = ['temperature_2m', 'total_precipitation', 'u_component_10m',
                                'v_component_10m', 'specific_humidity', 'soil_moisture']
                values = [day_data.get(f) for f in check_fields]
                if all(v is None or v == 0.0 for v in values):
                    self.logger.warning(f"All-zero/null data for {station.name} on {current_date}, skipping")
                    continue

                try:
                    # Only include fields with non-None values in defaults so that
                    # a partial download (e.g. surface file failed but pressure OK)
                    # never overwrites previously valid data with NULL.
                    era5_fields = {
                        'temperature_2m': day_data.get('temperature_2m'),
                        'total_precipitation': day_data.get('total_precipitation'),
                        'u_component_10m': day_data.get('u_component_10m'),
                        'v_component_10m': day_data.get('v_component_10m'),
                        'specific_humidity': day_data.get('specific_humidity'),
                        'soil_moisture': day_data.get('soil_moisture'),
                    }
                    defaults = {k: v for k, v in era5_fields.items() if v is not None}
                    defaults.update({
                        'download_timestamp': timezone.now(),
                        'data_source': 'ERA5_CDS' if not self.downloader.simulate_mode else 'ERA5_Simulated',
                        'is_complete': bool(day_data.get('is_complete', True)),
                        'processing_status': 'processed',
                    })
                    with transaction.atomic():
                        _, created = ERA5Data.objects.update_or_create(
                            station=station,
                            date=current_date,
                            defaults=defaults,
                        )
                    downloaded_count += 1
                    action = 'Created' if created else 'Updated'
                    t2m = day_data.get('temperature_2m')
                    tp = day_data.get('total_precipitation')
                    t2m_str = f"{t2m:.2f}K" if t2m is not None else "None"
                    tp_str = f"{tp:.4f}m" if tp is not None else "None"
                    self.logger.info(
                        f"{action} ERA5 record for {station.name} on {current_date}: "
                        f"t2m={t2m_str}, tp={tp_str}, q={day_data.get('specific_humidity')}"
                    )
                except Exception as e:
                    self.logger.error(f"Error storing ERA5 for {station.name} on {current_date}: {e}")

            self.logger.info(f"Chunk {chunk_start} -> {chunk_end} saved. Total so far: {downloaded_count}")
            chunk_start = chunk_end + timedelta(days=1)

        self.logger.info(f"Stored {downloaded_count} ERA5 records for {station.name}")
        return downloaded_count

    def dry_run_summary(self, stations, start_date, end_date, variables):
        """Show what would be downloaded in dry run mode."""
        total_days = (end_date - start_date).days + 1
        total_records = len(stations) * total_days
        
        self.stdout.write(self.style.WARNING("DRY RUN MODE - No data will be downloaded"))
        self.stdout.write(f"Stations to process: {len(stations)}")
        self.stdout.write(f"Date range: {start_date} to {end_date} ({total_days} days)")
        self.stdout.write(f"Variables: {', '.join(variables)}")
        self.stdout.write(f"Estimated records: {total_records}")
        
        self.stdout.write("\nStations:")
        for station in stations:
            longitude, latitude = station.location.coords
            self.stdout.write(f"  - {station.id}: {station.name} ({latitude}, {longitude})")