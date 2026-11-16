#!/usr/bin/env python3
"""
Monthly Forecast Generator Script
=================================

This script generates monthly forecasts by aggregating daily discharge predictions
using the average monthly discharge method for energy calculation.

Usage:
    python run_monthly_forecast.py

Features:
- Processes all stations with daily predictions
- Uses average monthly discharge method for energy calculation
- Only processes months with complete data (predictions == days_in_month)
- Provides detailed progress reporting
"""

import os
import sys
import django
from datetime import date, datetime
from calendar import monthrange

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, DischargePrediction, MonthlyForecast
from django.db.models import Min, Max, Count

def get_available_month_ranges():
    """Get all year-month combinations that have daily predictions"""
    # Get date range of all predictions
    date_stats = DischargePrediction.objects.aggregate(
        min_date=Min('target_date'),
        max_date=Max('target_date'),
        total_predictions=Count('id')
    )
    
    if not date_stats['min_date']:
        print("❌ No daily predictions found in database")
        return []
    
    print(f"📅 Prediction date range: {date_stats['min_date']} to {date_stats['max_date']}")
    print(f"📊 Total predictions: {date_stats['total_predictions']}")
    
    # Generate list of all year-month combinations in range
    months_to_process = []
    current_date = date_stats['min_date'].replace(day=1)  # Start from first day of first month
    end_date = date_stats['max_date']
    
    while current_date <= end_date:
        months_to_process.append((current_date.year, current_date.month))
        
        # Move to next month
        if current_date.month == 12:
            current_date = current_date.replace(year=current_date.year + 1, month=1)
        else:
            current_date = current_date.replace(month=current_date.month + 1)
    
    print(f"🗓️  Found {len(months_to_process)} months to potentially process")
    return months_to_process

def check_month_completeness(station, year, month):
    """Check if a month has complete daily prediction data"""
    # Get expected days in month
    days_in_month = monthrange(year, month)[1]
    
    # Get first and last day of month
    first_day = date(year, month, 1)
    last_day = date(year, month, days_in_month)
    
    # Count predictions for this month
    predictions_count = DischargePrediction.objects.filter(
        station=station,
        target_date__range=[first_day, last_day]
    ).count()
    
    return {
        'days_in_month': days_in_month,
        'predictions_count': predictions_count,
        'is_complete': predictions_count == days_in_month,
        'first_day': first_day,
        'last_day': last_day
    }

def process_monthly_forecast(station, year, month):
    """Process monthly forecast for a specific station and month"""
    print(f"\n🔄 Processing {station.name} - {year}-{month:02d}")
    
    # Check if month has complete data
    completeness = check_month_completeness(station, year, month)
    
    if not completeness['is_complete']:
        print(f"   ⚠️  Incomplete data: {completeness['predictions_count']}/{completeness['days_in_month']} days - skipping")
        return False
    
    print(f"   ✅ Complete data: {completeness['predictions_count']}/{completeness['days_in_month']} days")
    
    # Get or create monthly forecast
    monthly_forecast, created = MonthlyForecast.objects.get_or_create(
        station=station,
        target_year=year,
        target_month=month,
        defaults={
            'processing_status': 'pending'
        }
    )
    
    if created:
        print(f"   📝 Created new monthly forecast")
    else:
        print(f"   🔄 Updating existing monthly forecast")
    
    try:
        # Run the aggregation using average monthly discharge method
        monthly_forecast.aggregate_daily_predictions()
        
        # Get the results
        summary = monthly_forecast.get_monthly_energy_summary()
        
        print(f"   📊 Results:")
        print(f"      Average discharge: {summary['average_monthly_discharge_m3s']:.2f} m³/s")
        print(f"      Daily energy (avg method): {summary['daily_energy_from_avg_discharge_mwh']:.2f} MWh/day")
        print(f"      Total monthly energy: {summary['total_monthly_energy_mwh']:.2f} MWh")
        print(f"      Processing status: {summary['processing_status']}")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Error processing monthly forecast: {e}")
        monthly_forecast.processing_status = 'failed'
        monthly_forecast.save()
        return False

def main():
    """Main execution function"""
    print("=" * 60)
    print("🌊 MONTHLY FORECAST GENERATOR")
    print("=" * 60)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Get all active stations
    stations = DischargeStation.objects.filter(is_active=True)
    print(f"🏭 Found {stations.count()} active stations")
    
    if stations.count() == 0:
        print("❌ No active stations found")
        return
    
    # Get available month ranges
    available_months = get_available_month_ranges()
    
    if not available_months:
        print("❌ No prediction data available")
        return
    
    # Statistics tracking
    total_processed = 0
    total_successful = 0
    total_skipped = 0
    
    # Process each station
    for station in stations:
        print(f"\n{'='*50}")
        print(f"🏭 STATION: {station.name} ({station.station_id})")
        print(f"{'='*50}")
        
        station_processed = 0
        station_successful = 0
        station_skipped = 0
        
        # Process each available month for this station
        for year, month in available_months:
            result = process_monthly_forecast(station, year, month)
            
            station_processed += 1
            total_processed += 1
            
            if result:
                station_successful += 1
                total_successful += 1
            else:
                station_skipped += 1
                total_skipped += 1
        
        print(f"\n📊 Station Summary for {station.name}:")
        print(f"   Processed: {station_processed}")
        print(f"   Successful: {station_successful}")
        print(f"   Skipped: {station_skipped}")
    
    # Final summary
    print(f"\n{'='*60}")
    print("📊 FINAL SUMMARY")
    print(f"{'='*60}")
    print(f"🏭 Stations processed: {stations.count()}")
    print(f"📅 Months processed: {total_processed}")
    print(f"✅ Successful: {total_successful}")
    print(f"⚠️  Skipped (incomplete data): {total_skipped}")
    print(f"⏰ Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Show some example results
    if total_successful > 0:
        print(f"\n🎯 SAMPLE RESULTS")
        print(f"{'='*60}")
        
        # Get latest monthly forecasts
        recent_forecasts = MonthlyForecast.objects.filter(
            processing_status='completed'
        ).order_by('-target_year', '-target_month')[:3]
        
        for forecast in recent_forecasts:
            summary = forecast.get_monthly_energy_summary()
            print(f"📊 {summary['station_name']} - {summary['month_name']} {summary['year']}")
            print(f"   Avg Discharge: {summary['average_monthly_discharge_m3s']:.2f} m³/s")
            print(f"   Monthly Energy: {summary['total_monthly_energy_mwh']:.2f} MWh")
            print(f"   Daily Forecasts: {summary['total_daily_forecasts']}")

if __name__ == "__main__":
    main()