#!/usr/bin/env python3
"""
Daily Rolling Window Scheduler
Automated daily maintenance of 90-day rolling windows

This script runs as a daily cron job or scheduled task to:
1. Download latest ERA5 data for all active stations
2. Maintain 90-day rolling windows (add new, remove old)
3. Ensure all stations are ready for predictions

Schedule this to run daily at a time when ERA5 data is available (e.g., 8 AM UTC)
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add Django project to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')

import django
django.setup()

from django.core.management import call_command
from django.conf import settings
from discharge_prediction.models import DischargeStation, ERA5Data
from discharge_prediction.signals import maintain_rolling_window_all_stations


def setup_logging():
    """Setup logging for the scheduler."""
    log_dir = Path(settings.BASE_DIR) / 'logs' / 'era5'
    log_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = log_dir / f'rolling_window_scheduler_{datetime.now().strftime("%Y%m%d")}.log'
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)


def check_era5_data_availability():
    """Check if ERA5 data should be available for today."""
    today = datetime.now().date()
    era5_delay = 7  # ERA5 has ~7 day delay
    latest_available = today - timedelta(days=era5_delay)
    
    return latest_available


def run_daily_maintenance():
    """Run daily rolling window maintenance for all stations."""
    logger = setup_logging()
    logger.info("Starting daily rolling window maintenance")
    
    try:
        # Check data availability
        latest_available = check_era5_data_availability()
        logger.info(f"Latest available ERA5 date: {latest_available}")
        
        # Get active stations
        active_stations = DischargeStation.objects.filter(is_active=True)
        logger.info(f"Found {active_stations.count()} active stations")
        
        if not active_stations.exists():
            logger.warning("No active stations found - nothing to maintain")
            return
        
        # Run rolling window maintenance for all stations
        logger.info("Starting rolling window maintenance for all stations...")
        maintain_rolling_window_all_stations()
        
        # Wait a moment for background threads to complete
        import time
        time.sleep(10)
        
        # Generate summary report
        generate_daily_report(logger, active_stations, latest_available)
        
        logger.info("Daily rolling window maintenance completed successfully")
        
    except Exception as e:
        logger.error(f"Daily maintenance failed: {e}")
        raise


def generate_daily_report(logger, stations, latest_available):
    """Generate a daily summary report."""
    logger.info("Generating daily maintenance report...")
    
    total_stations = stations.count()
    ready_stations = 0
    total_data_points = 0
    stations_with_issues = []
    
    for station in stations:
        # Check station data status
        era5_count = ERA5Data.objects.filter(station=station).count()
        latest_data = ERA5Data.objects.filter(station=station).order_by('-date').first()
        
        total_data_points += era5_count
        
        # Check if station is ready
        if era5_count >= 90 and latest_data and latest_data.date >= (latest_available - timedelta(days=3)):
            ready_stations += 1
        else:
            issue_details = []
            if era5_count < 90:
                issue_details.append(f"insufficient data ({era5_count}/90 days)")
            if not latest_data:
                issue_details.append("no ERA5 data found")
            elif latest_data.date < (latest_available - timedelta(days=3)):
                issue_details.append(f"data outdated (latest: {latest_data.date})")
            
            stations_with_issues.append({
                'name': station.name,
                'station_id': station.station_id,
                'issues': issue_details
            })
    
    # Log summary
    logger.info("="*60)
    logger.info("DAILY MAINTENANCE REPORT")
    logger.info("="*60)
    logger.info(f"Total active stations: {total_stations}")
    logger.info(f"Stations ready for prediction: {ready_stations}")
    logger.info(f"Total ERA5 data points: {total_data_points:,}")
    logger.info(f"Latest available ERA5 date: {latest_available}")
    
    if stations_with_issues:
        logger.warning(f"Stations with issues: {len(stations_with_issues)}")
        for station_info in stations_with_issues:
            logger.warning(f"  - {station_info['name']} ({station_info['station_id']}): {', '.join(station_info['issues'])}")
    else:
        logger.info("✅ All stations are ready for predictions!")
    
    logger.info("="*60)


def run_weekly_cleanup():
    """Run weekly cleanup tasks (call this once per week)."""
    logger = setup_logging()
    logger.info("Starting weekly cleanup tasks")
    
    try:
        # Clean up old log files (older than 30 days)
        log_dir = Path(settings.BASE_DIR) / 'logs' / 'era5'
        if log_dir.exists():
            cutoff_date = datetime.now() - timedelta(days=30)
            cleaned_files = 0
            
            for log_file in log_dir.glob('*.log'):
                if log_file.stat().st_mtime < cutoff_date.timestamp():
                    log_file.unlink()
                    cleaned_files += 1
            
            logger.info(f"Cleaned up {cleaned_files} old log files")
        
        # Optional: Clean up any orphaned ERA5 data (data without corresponding stations)
        from django.db.models import Count
        orphaned_data = ERA5Data.objects.filter(station__isnull=True)
        orphaned_count = orphaned_data.count()
        
        if orphaned_count > 0:
            orphaned_data.delete()
            logger.info(f"Cleaned up {orphaned_count} orphaned ERA5 records")
        
        logger.info("Weekly cleanup completed successfully")
        
    except Exception as e:
        logger.error(f"Weekly cleanup failed: {e}")


def main():
    """Main entry point for the scheduler."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Daily Rolling Window Scheduler')
    parser.add_argument('--daily', action='store_true', help='Run daily maintenance')
    parser.add_argument('--weekly', action='store_true', help='Run weekly cleanup')
    parser.add_argument('--status', action='store_true', help='Show current status')
    
    args = parser.parse_args()
    
    if args.daily:
        run_daily_maintenance()
    elif args.weekly:
        run_weekly_cleanup()
    elif args.status:
        # Use the management command for status
        call_command('maintain_rolling_windows', check_status=True)
    else:
        # Default to daily maintenance
        run_daily_maintenance()


if __name__ == '__main__':
    main()
