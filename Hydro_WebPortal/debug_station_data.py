#!/usr/bin/env python
"""
Check available stations and investigate November 2025 issue
"""
import os
import sys
import django
from datetime import date, datetime
from calendar import monthrange

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, DischargePrediction, MonthlyForecast

def list_available_stations():
    """List all available stations"""
    
    print("=" * 60)
    print("AVAILABLE DISCHARGE STATIONS")
    print("=" * 60)
    
    stations = DischargeStation.objects.all()
    
    if not stations:
        print("✗ No stations found in database!")
        return None
    
    for i, station in enumerate(stations, 1):
        print(f"{i}. Name: {station.name}")
        print(f"   ID: {station.station_id}")
        print(f"   UUID: {station.id}")
        print(f"   Active: {station.is_active}")
        print(f"   Model Ready: {station.is_model_ready}")
        print("")
    
    return stations[0] if stations else None

def debug_monthly_forecasts():
    """Check all monthly forecasts"""
    
    print("=" * 60)
    print("ALL MONTHLY FORECASTS")
    print("=" * 60)
    
    monthly_forecasts = MonthlyForecast.objects.all().order_by('-target_year', '-target_month')
    
    if not monthly_forecasts:
        print("✗ No monthly forecasts found!")
        return
    
    for forecast in monthly_forecasts:
        print(f"Station: {forecast.station.name}")
        print(f"Period: {forecast.target_year}-{forecast.target_month:02d}")
        print(f"Status: {forecast.processing_status}")
        print(f"Daily Forecasts: {forecast.total_daily_forecasts}")
        print(f"Mean Discharge: {forecast.mean_discharge}")
        print(f"Total Energy: {forecast.total_energy_mwh}")
        print(f"Created: {forecast.created_at}")
        print("-" * 40)

def investigate_november_2025(station):
    """Investigate November 2025 specifically"""
    
    print("=" * 60)
    print("NOVEMBER 2025 INVESTIGATION")
    print("=" * 60)
    
    year, month = 2025, 11
    days_in_month = monthrange(year, month)[1]  # 30 days
    
    # Check daily predictions
    november_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=year,
        target_date__month=month
    ).order_by('target_date')
    
    total_count = november_predictions.count()
    print(f"November 2025 has {total_count} daily predictions (expected: {days_in_month})")
    
    if total_count == 0:
        print("✗ No predictions found for November 2025!")
        return
    
    # Check for duplicates
    from collections import Counter
    date_counts = Counter([pred.target_date for pred in november_predictions])
    duplicates = {date: count for date, count in date_counts.items() if count > 1}
    
    if duplicates:
        print(f"⚠️  DUPLICATE DATES FOUND:")
        for date_dup, count in duplicates.items():
            print(f"   {date_dup}: {count} predictions")
        
        print(f"\nThis explains the failure! You have {total_count} predictions for a {days_in_month}-day month.")
        print("The system requires exactly 1 prediction per day.")
        
        # Show sample duplicates
        print("\nSample duplicate entries:")
        for dup_date in list(duplicates.keys())[:3]:
            dup_predictions = november_predictions.filter(target_date=dup_date)
            for i, pred in enumerate(dup_predictions):
                print(f"   {dup_date} #{i+1}: {pred.predicted_discharge:.2f} m³/s, ID: {pred.id}")
    
    # Check date coverage
    prediction_dates = set(pred.target_date for pred in november_predictions)
    expected_dates = set(date(year, month, day) for day in range(1, days_in_month + 1))
    
    missing_dates = expected_dates - prediction_dates
    if missing_dates:
        print(f"\nMissing dates: {sorted(missing_dates)}")
    
    unique_days = len(prediction_dates)
    print(f"\nUnique days covered: {unique_days}/{days_in_month}")
    print(f"Total prediction records: {total_count}")
    
    if total_count > days_in_month:
        print(f"\n🔍 ROOT CAUSE: Data quality issue - {total_count} records for {days_in_month} days")
        print("✅ SOLUTION: Remove duplicate predictions to have exactly 1 per day")

def check_recent_predictions(station):
    """Check recent predictions to understand data pattern"""
    
    print("=" * 60)
    print("RECENT PREDICTIONS OVERVIEW")
    print("=" * 60)
    
    # Get predictions from Sep 1 to Nov 14, 2025
    start_date = date(2025, 9, 1)
    end_date = date(2025, 11, 14)
    
    predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__range=[start_date, end_date]
    ).order_by('target_date')
    
    total_predictions = predictions.count()
    print(f"Total predictions from {start_date} to {end_date}: {total_predictions}")
    
    # Group by month
    from collections import defaultdict
    monthly_counts = defaultdict(int)
    
    for pred in predictions:
        month_key = f"{pred.target_date.year}-{pred.target_date.month:02d}"
        monthly_counts[month_key] += 1
    
    print("\nMonthly breakdown:")
    for month_key, count in sorted(monthly_counts.items()):
        year_month = month_key.split('-')
        year, month = int(year_month[0]), int(year_month[1])
        expected_days = monthrange(year, month)[1]
        
        if month <= 11:  # Only check complete months up to November
            status = "✓" if count == expected_days else "⚠️" if count > expected_days else "✗"
            print(f"   {month_key}: {count} predictions (expected: {expected_days}) {status}")

if __name__ == "__main__":
    # First, list available stations
    station = list_available_stations()
    
    if station:
        print(f"\nUsing station: {station.name}")
        
        # Check all monthly forecasts
        debug_monthly_forecasts()
        
        # Investigate November 2025 specifically
        investigate_november_2025(station)
        
        # Check overall recent data
        check_recent_predictions(station)
    else:
        print("Cannot proceed without stations in database")