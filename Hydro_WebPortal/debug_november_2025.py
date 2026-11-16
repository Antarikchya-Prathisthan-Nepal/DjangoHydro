#!/usr/bin/env python
"""
Debug script to investigate why November 2025 monthly forecast is failing
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

def debug_november_2025():
    """Debug November 2025 monthly forecast failure"""
    
    print("=" * 60)
    print("DEBUGGING NOVEMBER 2025 MONTHLY FORECAST FAILURE")
    print("=" * 60)
    
    # Get the station
    try:
        station = DischargeStation.objects.get(name__icontains="Lower Ilkhu")
        print(f"✓ Found station: {station.name} (ID: {station.station_id})")
    except DischargeStation.DoesNotExist:
        print("✗ Station 'Lower Ilkhu' not found!")
        return
    
    # Check November 2025 date range
    year, month = 2025, 11
    first_day = date(year, month, 1)
    days_in_month = monthrange(year, month)[1]  # 30 days in November
    last_day = date(year, month, days_in_month)
    
    print(f"\n📅 November 2025 Analysis:")
    print(f"   Date range: {first_day} to {last_day}")
    print(f"   Expected days in month: {days_in_month}")
    
    # Check daily predictions for November 2025
    november_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=year,
        target_date__month=month
    ).order_by('target_date')
    
    total_predictions = november_predictions.count()
    print(f"   Total predictions found: {total_predictions}")
    
    if total_predictions == 0:
        print("   ✗ NO PREDICTIONS FOUND for November 2025!")
        print("   This explains why the monthly forecast failed.")
        return
    
    # Analyze the predictions
    print(f"\n📊 Daily Predictions Analysis:")
    
    # Check for duplicates
    from collections import Counter
    date_counts = Counter([pred.target_date for pred in november_predictions])
    duplicates = {date: count for date, count in date_counts.items() if count > 1}
    
    if duplicates:
        print(f"   ⚠️  DUPLICATE DATES FOUND:")
        for date_dup, count in duplicates.items():
            print(f"      {date_dup}: {count} predictions")
        total_unique_days = len(date_counts)
        print(f"   Unique days: {total_unique_days}")
        print(f"   Total records: {total_predictions}")
    else:
        print(f"   ✓ No duplicate dates found")
        print(f"   Unique prediction days: {total_predictions}")
    
    # Check date range coverage
    prediction_dates = set(pred.target_date for pred in november_predictions)
    expected_dates = set(date(year, month, day) for day in range(1, days_in_month + 1))
    
    missing_dates = expected_dates - prediction_dates
    extra_dates = prediction_dates - expected_dates
    
    if missing_dates:
        print(f"   ✗ Missing dates: {sorted(missing_dates)}")
    else:
        print(f"   ✓ All expected dates covered")
        
    if extra_dates:
        print(f"   ⚠️  Extra dates (outside November): {sorted(extra_dates)}")
    
    # Check processing status
    status_counts = {}
    for pred in november_predictions:
        status = pred.processing_status
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print(f"\n📈 Processing Status Breakdown:")
    for status, count in status_counts.items():
        print(f"   {status}: {count} predictions")
    
    # Check energy calculations
    energy_stats = {
        'with_energy': 0,
        'without_energy': 0,
        'total_energy': 0
    }
    
    for pred in november_predictions:
        if pred.predicted_energy is not None:
            energy_stats['with_energy'] += 1
            energy_stats['total_energy'] += pred.predicted_energy
        else:
            energy_stats['without_energy'] += 1
    
    print(f"\n⚡ Energy Data Analysis:")
    print(f"   Predictions with energy: {energy_stats['with_energy']}")
    print(f"   Predictions without energy: {energy_stats['without_energy']}")
    if energy_stats['with_energy'] > 0:
        avg_energy = energy_stats['total_energy'] / energy_stats['with_energy']
        print(f"   Average daily energy: {avg_energy:.2f} MWh")
    
    # Check monthly forecast record
    monthly_forecast = MonthlyForecast.objects.filter(
        station=station,
        target_year=year,
        target_month=month
    ).first()
    
    print(f"\n📋 Monthly Forecast Record:")
    if monthly_forecast:
        print(f"   Status: {monthly_forecast.processing_status}")
        print(f"   Total daily forecasts: {monthly_forecast.total_daily_forecasts}")
        print(f"   Mean discharge: {monthly_forecast.mean_discharge}")
        print(f"   Total energy: {monthly_forecast.total_energy_mwh}")
        print(f"   Created: {monthly_forecast.created_at}")
        print(f"   Updated: {monthly_forecast.updated_at}")
    else:
        print("   ✗ No monthly forecast record found!")
    
    # Diagnosis
    print(f"\n🔍 DIAGNOSIS:")
    
    if total_predictions == 0:
        print("   CAUSE: No daily predictions available for November 2025")
        print("   SOLUTION: Generate daily predictions for November 2025 first")
    elif duplicates:
        print("   CAUSE: Duplicate predictions for same dates")
        print(f"   DETAILS: {total_predictions} total records for {days_in_month}-day month")
        print("   SOLUTION: Remove duplicate predictions or fix data quality")
    elif missing_dates:
        print("   CAUSE: Incomplete month data - missing some days")
        print("   SOLUTION: Generate predictions for missing dates")
    elif total_predictions != days_in_month:
        print(f"   CAUSE: Data count mismatch - {total_predictions} predictions vs {days_in_month} expected days")
        print("   SOLUTION: Ensure exactly one prediction per day")
    else:
        print("   CAUSE: Unknown - data appears complete but monthly forecast still failed")
        print("   SOLUTION: Try re-running monthly aggregation")
    
    # Show sample predictions
    print(f"\n📝 Sample Predictions (first 5):")
    for i, pred in enumerate(november_predictions[:5]):
        print(f"   {pred.target_date}: {pred.predicted_discharge:.2f} m³/s, "
              f"Energy: {pred.predicted_energy or 'None'}, Status: {pred.processing_status}")
    
    if total_predictions > 5:
        print(f"   ... and {total_predictions - 5} more")

def check_data_quality():
    """Check overall data quality for September-November 2025"""
    
    print("\n" + "=" * 60)
    print("OVERALL DATA QUALITY CHECK (Sep-Nov 2025)")
    print("=" * 60)
    
    station = DischargeStation.objects.get(name__icontains="Lower Ilkhu")
    
    # Check predictions by month
    months = [(2025, 9, "September"), (2025, 10, "October"), (2025, 11, "November")]
    
    for year, month, month_name in months:
        first_day = date(year, month, 1)
        days_in_month = monthrange(year, month)[1]
        last_day = date(year, month, days_in_month)
        
        predictions = DischargePrediction.objects.filter(
            station=station,
            target_date__range=[first_day, last_day]
        )
        
        total_count = predictions.count()
        unique_dates = len(set(pred.target_date for pred in predictions))
        
        print(f"\n📅 {month_name} {year}:")
        print(f"   Expected days: {days_in_month}")
        print(f"   Total predictions: {total_count}")
        print(f"   Unique dates: {unique_dates}")
        
        if total_count == days_in_month == unique_dates:
            print(f"   ✓ Perfect data quality")
        elif total_count > days_in_month:
            print(f"   ⚠️  Duplicate data detected")
        elif total_count < days_in_month:
            print(f"   ✗ Incomplete data")
        else:
            print(f"   ❓ Unusual data pattern")

if __name__ == "__main__":
    debug_november_2025()
    check_data_quality()