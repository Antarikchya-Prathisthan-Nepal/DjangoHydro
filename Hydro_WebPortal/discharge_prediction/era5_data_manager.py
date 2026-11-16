#!/usr/bin/env python3
"""
ERA5 Bootstrap and Daily Update Strategy
Handles initial 90-day download and subsequent daily updates for rolling sequences
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
import django
django.setup()

from discharge_prediction.models import DischargeStation, ERA5Data
from discharge_prediction.era5_utils import create_era5_downloader

logger = logging.getLogger(__name__)

class ERA5DataManager:
    """Manages ERA5 data downloads with bootstrap and daily update strategies"""
    
    def __init__(self):
        self.downloader = create_era5_downloader('complete')
        
    def check_station_data_status(self, station):
        """Check current data status for a station"""
        try:
            # Get latest available ERA5 data
            latest_record = ERA5Data.objects.filter(
                station=station,
                is_complete=True
            ).order_by('-date').first()
            
            total_records = ERA5Data.objects.filter(
                station=station,
                is_complete=True
            ).count()
            
            # Calculate what we need for current predictions
            today = datetime.now().date()
            
            # For prediction today, we need data up to: today - 45 days (lead time)
            required_data_end = today - timedelta(days=45)
            # And we need 90 days of data before that
            required_data_start = required_data_end - timedelta(days=89)
            
            available_data_count = ERA5Data.objects.filter(
                station=station,
                date__range=[required_data_start, required_data_end],
                is_complete=True
            ).count()
            
            status = {
                'station_name': station.name,
                'total_records': total_records,
                'latest_date': latest_record.date if latest_record else None,
                'required_start': required_data_start,
                'required_end': required_data_end,
                'available_for_prediction': available_data_count,
                'required_for_prediction': 90,
                'is_ready_for_prediction': available_data_count >= 50,  # Minimum threshold
                'needs_bootstrap': total_records < 90,
                'days_behind': (today - latest_record.date).days if latest_record else None
            }
            
            return status
            
        except Exception as e:
            logger.error(f"Error checking status for {station.name}: {e}")
            return None
    
    def bootstrap_station_data(self, station, days_back=120):
        """
        Bootstrap download for stations with insufficient data
        Downloads extra days to ensure robust 90-day sequences
        
        Args:
            station: DischargeStation object
            days_back: Number of days to download (default 120 for safety margin)
        """
        try:
            logger.info(f"🚀 Starting bootstrap download for {station.name}")
            
            # Calculate date range - go back extra days for safety
            end_date = datetime.now() - timedelta(days=8)  # Account for ERA5 delay
            start_date = end_date - timedelta(days=days_back)
            
            logger.info(f"📅 Bootstrap range: {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}")
            
            # Download in chunks to avoid timeouts
            chunk_size = 10  # Download 10 days at a time
            current_start = start_date
            total_saved = 0
            
            while current_start <= end_date:
                chunk_end = min(current_start + timedelta(days=chunk_size-1), end_date)
                
                logger.info(f"📦 Downloading chunk: {current_start.strftime('%Y-%m-%d')} to {chunk_end.strftime('%Y-%m-%d')}")
                
                try:
                    saved_count = self.downloader.download_and_save_era5_data(
                        station, current_start, chunk_end
                    )
                    total_saved += saved_count
                    logger.info(f"✅ Chunk completed: {saved_count} records saved")
                    
                except Exception as e:
                    logger.error(f"❌ Chunk failed: {e}")
                    # Continue with next chunk
                
                current_start = chunk_end + timedelta(days=1)
            
            logger.info(f"🎉 Bootstrap completed: {total_saved} total records saved for {station.name}")
            return total_saved
            
        except Exception as e:
            logger.error(f"❌ Bootstrap failed for {station.name}: {e}")
            return 0
    
    def daily_update_station(self, station, target_date=None):
        """
        Download latest daily data for rolling sequence updates
        
        Args:
            station: DischargeStation object  
            target_date: Specific date to download (default: latest missing date)
        """
        try:
            if target_date is None:
                # Find the latest missing date
                latest_record = ERA5Data.objects.filter(
                    station=station,
                    is_complete=True
                ).order_by('-date').first()
                
                if latest_record:
                    # Download the next day after latest record
                    target_date = latest_record.date + timedelta(days=1)
                else:
                    # No data exists, need bootstrap first
                    logger.warning(f"⚠️ No data for {station.name}. Bootstrap required.")
                    return 0
                
                # Don't download future dates or very recent dates (ERA5 delay)
                max_date = datetime.now().date() - timedelta(days=8)
                if target_date > max_date:
                    logger.info(f"ℹ️ {station.name} is up to date (latest available: {max_date})")
                    return 0
            
            logger.info(f"📅 Daily update for {station.name}: {target_date}")
            
            # Download single day
            saved_count = self.downloader.download_and_save_era5_data(
                station, 
                datetime.combine(target_date, datetime.min.time()),
                datetime.combine(target_date, datetime.min.time())
            )
            
            if saved_count > 0:
                logger.info(f"✅ Daily update completed: {target_date} saved for {station.name}")
            else:
                logger.warning(f"⚠️ No data saved for {station.name} on {target_date}")
                
            return saved_count
            
        except Exception as e:
            logger.error(f"❌ Daily update failed for {station.name}: {e}")
            return 0
    
    def update_all_stations(self, force_bootstrap=False):
        """
        Smart update for all active stations
        - Bootstrap stations with insufficient data
        - Daily update stations with sufficient data
        """
        try:
            active_stations = DischargeStation.objects.filter(is_active=True)
            
            logger.info(f"🔄 Updating {active_stations.count()} active stations")
            
            bootstrap_count = 0
            update_count = 0
            
            for station in active_stations:
                status = self.check_station_data_status(station)
                
                if not status:
                    continue
                
                logger.info(f"📊 {station.name}: {status['total_records']} records, "
                          f"latest: {status['latest_date']}, ready: {status['is_ready_for_prediction']}")
                
                if force_bootstrap or status['needs_bootstrap']:
                    logger.info(f"🔄 Bootstrapping {station.name}")
                    saved = self.bootstrap_station_data(station)
                    if saved > 0:
                        bootstrap_count += 1
                elif status['days_behind'] and status['days_behind'] > 0:
                    logger.info(f"🔄 Daily update for {station.name}")
                    saved = self.daily_update_station(station)
                    if saved > 0:
                        update_count += 1
                else:
                    logger.info(f"✅ {station.name} is up to date")
            
            logger.info(f"🎉 Update complete: {bootstrap_count} bootstrapped, {update_count} daily updated")
            return {'bootstrapped': bootstrap_count, 'updated': update_count}
            
        except Exception as e:
            logger.error(f"❌ Update all stations failed: {e}")
            return {'bootstrapped': 0, 'updated': 0}
    
    def fill_missing_dates(self, station, start_date=None, end_date=None):
        """
        Fill any missing dates in a date range for a station
        Useful for fixing gaps in data
        """
        try:
            if start_date is None:
                start_date = datetime.now().date() - timedelta(days=120)
            if end_date is None:
                end_date = datetime.now().date() - timedelta(days=8)
            
            logger.info(f"🔍 Checking for missing dates: {start_date} to {end_date}")
            
            # Get all dates that should exist
            current_date = start_date
            missing_dates = []
            
            while current_date <= end_date:
                exists = ERA5Data.objects.filter(
                    station=station,
                    date=current_date,
                    is_complete=True
                ).exists()
                
                if not exists:
                    missing_dates.append(current_date)
                    
                current_date += timedelta(days=1)
            
            if missing_dates:
                logger.info(f"📋 Found {len(missing_dates)} missing dates for {station.name}")
                
                # Download missing dates in small batches
                filled_count = 0
                for missing_date in missing_dates[:20]:  # Limit to 20 missing dates per run
                    try:
                        saved = self.daily_update_station(station, missing_date)
                        if saved > 0:
                            filled_count += 1
                    except Exception as e:
                        logger.error(f"Failed to fill {missing_date}: {e}")
                        continue
                
                logger.info(f"✅ Filled {filled_count} missing dates for {station.name}")
                return filled_count
            else:
                logger.info(f"✅ No missing dates for {station.name}")
                return 0
                
        except Exception as e:
            logger.error(f"❌ Fill missing dates failed: {e}")
            return 0


def main():
    """Example usage of ERA5DataManager"""
    manager = ERA5DataManager()
    
    # Get station
    station = DischargeStation.objects.get(name__icontains="Lower likhu")
    
    # Check current status
    status = manager.check_station_data_status(station)
    print("📊 Current Status:")
    for key, value in status.items():
        print(f"  {key}: {value}")
    
    # Decide what to do
    if status['needs_bootstrap']:
        print(f"\n🚀 Station needs bootstrap download")
        manager.bootstrap_station_data(station)
    else:
        print(f"\n📅 Station has sufficient data, doing daily update")
        manager.daily_update_station(station)


if __name__ == "__main__":
    main()
