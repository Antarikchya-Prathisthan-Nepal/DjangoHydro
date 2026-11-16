"""
Django Signals for Automatic ERA5 Data Management
Handles automatic data download and rolling window maintenance

Rolling Window Logic (Updated):
================================================================================
Previous Logic: Add new data at index 0 (left), remove from index 89 (right)
New Logic: Remove data at index 0 (left), add new data at index 89 (right)

This creates a FIFO (First In, First Out) queue where:
- Oldest data is removed from the beginning (index 0)
- Newest data is appended to the end (index 89)
- Maintains exactly 90 days of data at all times

Data Flow:
1. Initial setup: Download 90 days of historical data
2. Daily maintenance: Download newest available data → append to right side
3. Window maintenance: Remove excess oldest data from left side
4. Result: Always maintain exactly 90 days sliding window
================================================================================
"""

import logging
from datetime import datetime, timedelta
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.core.management import call_command
from django.utils import timezone
import threading

from .models import DischargeStation, ERA5Data, DischargePrediction
from .era5_utils import ERA5Downloader

logger = logging.getLogger(__name__)


@receiver(post_save, sender=DischargeStation)
def auto_download_era5_on_station_creation(sender, instance, created, **kwargs):
    """
    Automatically download 90 days of ERA5 data when a new station is added
    
    Strategy:
    1. Admin adds new DischargeStation → Signal triggers
    2. Download latest 90 days of ERA5 data (past 3 months)
    3. Process and store in ERA5Data table
    4. Set up station for daily updates
    """
    if created:  # Only trigger for new stations
        logger.info(f"🆕 New station created: {instance.name}. Starting automatic ERA5 bootstrap.")
        
        # Schedule immediate background download using threading
        download_thread = threading.Thread(
            target=bootstrap_new_station_era5,
            args=(instance.id,)
        )
        download_thread.daemon = True
        download_thread.start()
        
        logger.info(f"📅 Scheduled 90-day ERA5 bootstrap for station: {instance.name}")
    
    # Also trigger if station is activated after creation
    elif hasattr(instance, '_state') and instance._state.adding is False:
        try:
            # Check if station was just activated
            old_instance = DischargeStation.objects.get(pk=instance.pk)
            if not old_instance.is_active and instance.is_active:
                logger.info(f"🔄 Station {instance.name} was activated - checking data requirements")
                
                # Check if station needs ERA5 data
                current_data_count = ERA5Data.objects.filter(
                    station=instance,
                    is_complete=True
                ).count()
                
                if current_data_count < 90:
                    logger.info(f"📦 Station {instance.name} needs ERA5 data ({current_data_count}/90 days)")
                    download_thread = threading.Thread(
                        target=bootstrap_new_station_era5,
                        args=(instance.id,)
                    )
                    download_thread.daemon = True
                    download_thread.start()
                else:
                    logger.info(f"✅ Station {instance.name} already has sufficient ERA5 data ({current_data_count} days)")
                    
        except DischargeStation.DoesNotExist:
            # This shouldn't happen, but handle gracefully
            logger.warning(f"⚠️ Could not find previous state for station {instance.name}")


def bootstrap_new_station_era5(station_id):
    """
    Bootstrap ERA5 data for newly created stations
    Downloads 90 days of historical data and sets up for daily updates
    """
    try:
        station = DischargeStation.objects.get(id=station_id)
        
        logger.info(f"🚀 Starting ERA5 bootstrap for new station: {station.name}")
        
        # Import the ERA5 data manager
        from .era5_data_manager import ERA5DataManager
        
        manager = ERA5DataManager()
        
        # Bootstrap with 90 days of data (going back a bit extra for safety)
        saved_count = manager.bootstrap_station_data(station, days_back=90)
        
        if saved_count > 0:
            logger.info(f"✅ Bootstrap completed for {station.name}: {saved_count} records saved")
            
            # Validate data completeness
            status = manager.check_station_data_status(station)
            
            if status and status['is_ready_for_prediction']:
                # Mark station as ready
                station.is_model_ready = True  # Assuming model will be configured
                station.last_forecast_date = datetime.now().date()
                station.save()
                
                logger.info(f"🎯 Station {station.name} is now ready for predictions")
                
                # Create a record to track this bootstrap
                from .models import PipelineRun
                PipelineRun.objects.create(
                    run_type='era5_download',
                    station=station,
                    target_date=datetime.now().date(),
                    status='completed',
                    scheduled_time=timezone.now(),
                    processed_records=saved_count,
                    parameters={
                        'download_type': 'automatic_bootstrap',
                        'reason': 'New station created',
                        'days_downloaded': 90
                    }
                )
                
            else:
                logger.warning(f"⚠️ Bootstrap incomplete for {station.name}. May need manual intervention.")
        else:
            logger.error(f"❌ Bootstrap failed for {station.name}")
            
    except DischargeStation.DoesNotExist:
        logger.error(f"❌ Station with ID {station_id} not found during bootstrap")
    except Exception as e:
        logger.error(f"❌ Error in ERA5 bootstrap for station {station_id}: {e}")


@receiver(post_save, sender=DischargeStation)  
def setup_daily_era5_schedule(sender, instance, created, **kwargs):
    """
    Set up daily ERA5 updates for the station after bootstrap is complete
    """
    if not created:  # Only for existing stations
        return
        
    # This will be called after bootstrap completes
    # We could set up a cron job or scheduled task here
    logger.info(f"📅 Station {instance.name} is set up for daily ERA5 updates")
    
    # You can add logic here to:
    # 1. Register station with your scheduler (cron, celery beat, etc.)
    # 2. Add to daily update queue
    # 3. Set update preferences


@receiver(post_save, sender=DischargeStation)
def update_station_metadata(sender, instance, **kwargs):
    """
    Update station metadata when coordinates or settings change
    """
    if instance.coordinates:
        lat, lon = instance.coordinates
        logger.info(f"Station {instance.name} coordinates: ({lat:.4f}, {lon:.4f})")
        
        # Update bounding box info in logs
        buffer = 0.25  # Default ±0.25 degrees
        north = lat + buffer
        south = lat - buffer
        west = lon - buffer
        east = lon + buffer
        
        logger.info(f"ERA5 download area for {instance.name}: "
                   f"North={north:.4f}, South={south:.4f}, West={west:.4f}, East={east:.4f}")


def schedule_initial_era5_download(station_id):
    """
    Background task for downloading initial 90 days of ERA5 data for new stations
    """
    try:
        station = DischargeStation.objects.get(id=station_id)
        
        # Download last 90 days of data (using current date as end)
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=89)  # 90 days total (inclusive)
        
        logger.info(f"Starting automatic ERA5 download for newly created station: {station.name}")
        logger.info(f"Downloading latest 90 days: {start_date} to {end_date}")
        
        # Use management command for real ERA5 data download
        call_command(
            'download_era5_data',
            station_name=station.name,  # Use station name instead of ID for compatibility
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            verbosity=1
        )
        
        # Verify download completeness
        downloaded_count = ERA5Data.objects.filter(
            station=station,
            date__range=[start_date, end_date],
            is_complete=True
        ).count()
        
        expected_count = (end_date - start_date).days + 1
        completeness = (downloaded_count / expected_count) * 100 if expected_count > 0 else 0
        
        logger.info(f"Automatic download completed for {station.name}: "
                   f"{downloaded_count}/{expected_count} days ({completeness:.1f}%)")
        
        # Update station status and mark as ready for predictions
        if downloaded_count >= 90:
            station.last_forecast_date = end_date
            station.is_active = True  # Ensure station is active after successful data download
            station.save()
            logger.info(f"Station {station.name} is now ready for discharge predictions with 90 days of data")
        else:
            logger.warning(f"Incomplete data download for {station.name}. Downloaded {downloaded_count}/90 days.")
            
    except DischargeStation.DoesNotExist:
        logger.error(f"Station with ID {station_id} not found during automatic download")
    except Exception as e:
        logger.error(f"Error in automatic ERA5 download for station {station_id}: {e}")
        # Don't raise exception to avoid breaking the station creation process


def maintain_rolling_window_all_stations():
    """
    Daily task to maintain 90-day rolling windows for all active stations
    """
    active_stations = DischargeStation.objects.filter(is_active=True)
    
    for station in active_stations:
        try:
            # Run in background thread
            thread = threading.Thread(
                target=maintain_station_rolling_window,
                args=(station.id,)
            )
            thread.daemon = True
            thread.start()
        except Exception as e:
            logger.error(f"Error scheduling rolling window maintenance for {station.name}: {e}")


def maintain_station_rolling_window(station_id):
    """
    Maintain 90-day rolling window for a specific station
    Rolling logic: Remove oldest data at index 0 (left), add newest data at index 89 (right)
    This creates a FIFO queue where oldest data is removed and newest is appended
    """
    try:
        station = DischargeStation.objects.get(id=station_id)
        
        # Get current data range
        latest_data = ERA5Data.objects.filter(station=station).order_by('-date').first()
        oldest_data = ERA5Data.objects.filter(station=station).order_by('date').first()
        
        if not latest_data:
            logger.warning(f"No ERA5 data found for {station.name}")
            return
            
        # Check if we need new data (download latest available)
        today = datetime.now().date()
        era5_delay = 7  # ERA5 has ~7 day delay
        latest_available = today - timedelta(days=era5_delay)
        
        # Step 1: Download new data and append to the right side (index 89)
        if latest_data.date < latest_available:
            start_download = latest_data.date + timedelta(days=1)
            
            logger.info(f"Appending new data to right side for {station.name}: {start_download} to {latest_available}")
            
            call_command(
                'download_era5_data',
                station_id=station.id,
                start_date=start_download.strftime('%Y-%m-%d'),
                end_date=latest_available.strftime('%Y-%m-%d'),
                variables='all',
                verbosity=1
            )
        
        # Step 2: Maintain 90-day window by removing oldest data from left side (index 0)
        # Get all data ordered by date (oldest first)
        all_data = ERA5Data.objects.filter(station=station).order_by('date')
        total_count = all_data.count()
        
        if total_count > 90:
            # Remove excess oldest records to maintain exactly 90 days
            excess_count = total_count - 90
            oldest_records = all_data[:excess_count]
            
            logger.info(f"Removing {excess_count} oldest records from left side for {station.name}")
            
            # Get the dates of records to delete
            dates_to_delete = [record.date for record in oldest_records]
            
            # Delete the oldest records
            ERA5Data.objects.filter(
                station=station,
                date__in=dates_to_delete
            ).delete()
            
            logger.info(f"Successfully removed oldest data. Window now maintains exactly 90 days")
        
        # Log current window status
        remaining_data = ERA5Data.objects.filter(station=station).order_by('date')
        if remaining_data.exists():
            first_date = remaining_data.first().date
            last_date = remaining_data.last().date
            current_count = remaining_data.count()
            logger.info(f"Rolling window for {station.name}: {current_count} days ({first_date} to {last_date})")
        
        # Verify window size
        current_count = ERA5Data.objects.filter(station=station).count()
        logger.info(f"Rolling window for {station.name}: {current_count} days maintained")
        
        # Update station metadata
        station.last_forecast_date = latest_available
        station.save()
        
    except DischargeStation.DoesNotExist:
        logger.error(f"Station with ID {station_id} not found")
    except Exception as e:
        logger.error(f"Error maintaining rolling window for station {station_id}: {e}")


@receiver(pre_delete, sender=DischargeStation)
def cleanup_station_data(sender, instance, **kwargs):
    """
    Clean up ERA5 data when a station is deleted
    """
    era5_count = instance.era5_data.count()
    if era5_count > 0:
        logger.info(f"Cleaning up {era5_count} ERA5 records for deleted station: {instance.name}")
        instance.era5_data.all().delete()


@receiver(post_save, sender=ERA5Data)
def auto_trigger_prediction_on_era5_update(sender, instance, created, **kwargs):
    """
    Automatically trigger discharge prediction when new ERA5 data is added
    and station has sufficient data (≥90 days) for model inference
    """
    if created and instance.is_complete and instance.station.is_active:
        station = instance.station
        
        # Check if station has a trained model
        if not station.is_model_ready:
            logger.debug(f"Station {station.name} not model-ready, skipping automatic prediction")
            return
        
        # Check if station has sufficient data for prediction using validation method
        from .models import ForecastSequence
        from datetime import date, timedelta
        
        # Create a proper ForecastSequence object for validation (45-day lead time)
        target_date = date.today() + timedelta(days=45)
        forecast_sequence = ForecastSequence(
            station=station,
            target_date=target_date,
            sequence_length=90,  # 90-day sequence
            lead_time_days=45    # 45-day lead time
        )
        # Calculate sequence dates before validation
        forecast_sequence.calculate_sequence_dates()
        
        is_ready = forecast_sequence.validate_data_availability()
        data_count = ERA5Data.objects.filter(
            station=station,
            is_complete=True,
            processing_status__in=['validated', 'processed']
        ).count()
        
        if is_ready:
            logger.info(f"Auto-triggering prediction for {station.name} - sufficient data ({data_count} days)")
            
            # Calculate prediction date (45-day lead time from latest data)
            latest_data = ERA5Data.objects.filter(
                station=station,
                is_complete=True
            ).order_by('-date').first()
            
            if latest_data:
                prediction_date = latest_data.date + timedelta(days=45)
                
                # Schedule prediction in background thread to avoid blocking the request
                prediction_thread = threading.Thread(
                    target=schedule_automatic_prediction,
                    args=(station.id, prediction_date, instance.date)
                )
                prediction_thread.daemon = True
                prediction_thread.start()
                
                logger.info(f"Scheduled automatic prediction for {station.name} targeting {prediction_date}")
        else:
            logger.debug(f"Station {station.name} has insufficient data for prediction ({data_count} days)")


def schedule_automatic_prediction(station_id, prediction_date, trigger_date):
    """
    Background task for generating automatic predictions when sufficient ERA5 data is available
    """
    try:
        station = DischargeStation.objects.get(id=station_id)
        
        # Add small delay to avoid race conditions with data updates
        import time
        time.sleep(2)
        
        logger.info(f"Starting automatic prediction for {station.name}")
        logger.info(f"Trigger: New ERA5 data for {trigger_date}")
        logger.info(f"Target prediction date: {prediction_date}")
        
        # Check if prediction already exists for this date
        existing_prediction = DischargePrediction.objects.filter(
            station=station,
            target_date=prediction_date
        ).first()
        
        if existing_prediction:
            logger.info(f"Prediction already exists for {station.name} on {prediction_date}, skipping")
            return
        
        # Import here to avoid circular imports
        from .prediction_utils import DischargePredictionEngine
        
        # Initialize prediction engine for this station
        if station.has_trained_model:
            model_path = station.model_file_path if station.model_file_path else None
            scaler_path = station.scaler_file_path if station.scaler_file_path else None
            prediction_engine = DischargePredictionEngine(
                model_path=model_path,
                normalization_scaler_path=scaler_path,
            )
        else:
            # Use simulation mode if no trained model configured
            prediction_engine = DischargePredictionEngine()
        
        # Load model
        if not prediction_engine.load_model():
            logger.error(f"Failed to load model for automatic prediction - {station.name}")
            return
        
        # Generate prediction
        logger.info(f"Generating automatic prediction for {station.name}...")
        predicted_discharge, confidence_bounds, success = prediction_engine.predict_single_day(
            station, prediction_date
        )
        
        if success and predicted_discharge:
            logger.info(f"Automatic prediction successful for {station.name}")
            logger.info(f"Predicted discharge: {predicted_discharge:.2f} m³/s")
            
            # Update station's last forecast date
            station.last_forecast_date = prediction_date
            station.save()
            
            logger.info(f"Station {station.name} forecast updated automatically")
        else:
            logger.error(f"Automatic prediction failed for {station.name}")
            
    except DischargeStation.DoesNotExist:
        logger.error(f"Station with ID {station_id} not found during automatic prediction")
    except Exception as e:
        logger.error(f"Error in automatic prediction for station {station_id}: {e}")
        # Don't raise exception to avoid breaking the ERA5 data save process


# Additional utility functions for rolling window management

def get_station_data_summary(station):
    """
    Get summary of ERA5 data availability for a station
    """
    data_queryset = ERA5Data.objects.filter(station=station).order_by('date')
    
    if not data_queryset.exists():
        return {
            'total_days': 0,
            'date_range': None,
            'completeness': 0,
            'ready_for_prediction': False
        }
    
    earliest = data_queryset.first().date
    latest = data_queryset.last().date
    total_days = data_queryset.count()
    expected_days = (latest - earliest).days + 1
    completeness = (total_days / expected_days) * 100 if expected_days > 0 else 0
    
    return {
        'total_days': total_days,
        'date_range': f"{earliest} to {latest}",
        'completeness': round(completeness, 1),
        'ready_for_prediction': total_days >= 90 and completeness >= 80
    }


def check_all_stations_readiness():
    """
    Check readiness status of all active stations
    """
    active_stations = DischargeStation.objects.filter(is_active=True)
    readiness_report = []
    
    for station in active_stations:
        summary = get_station_data_summary(station)
        readiness_report.append({
            'station': station.name,
            'station_id': station.station_id,
            'coordinates': station.coordinates,
            **summary
        })
    
    return readiness_report


def force_refresh_station_data(station_id, days=90):
    """
    Force refresh ERA5 data for a station (useful for troubleshooting)
    """
    try:
        station = DischargeStation.objects.get(id=station_id)
        
        # Delete existing data
        ERA5Data.objects.filter(station=station).delete()
        
        # Re-download last N days
        end_date = datetime.now().date() - timedelta(days=7)
        start_date = end_date - timedelta(days=days-1)
        
        call_command(
            'download_era5_data',
            station_id=station.id,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            variables='all',
            force_update=True,
            verbosity=2
        )
        
        logger.info(f"Force refresh completed for {station.name}")
        return True
        
    except Exception as e:
        logger.error(f"Error in force refresh for station {station_id}: {e}")
        return False
