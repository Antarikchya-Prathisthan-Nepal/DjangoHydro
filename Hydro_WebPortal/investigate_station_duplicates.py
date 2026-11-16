#!/usr/bin/env python
"""
Investigate if November 2025 "duplicates" are actually from different stations
"""
import os
import sys
import django
from datetime import date

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, DischargePrediction, MonthlyForecast

def investigate_november_stations():
    """Check if November 2025 predictions are from different stations"""
    
    print("=" * 80)
    print("INVESTIGATING NOVEMBER 2025 - MULTI-STATION ANALYSIS")
    print("=" * 80)
    
    # Get all November 2025 predictions
    november_predictions = DischargePrediction.objects.filter(
        target_date__year=2025,
        target_date__month=11
    ).order_by('target_date', 'station__name')
    
    total_predictions = november_predictions.count()
    print(f"📊 Total November 2025 predictions: {total_predictions}")
    
    # Group by station
    stations = {}
    for pred in november_predictions:
        station_name = pred.station.name
        if station_name not in stations:
            stations[station_name] = []
        stations[station_name].append(pred)
    
    print(f"🏭 Number of stations with November 2025 predictions: {len(stations)}")
    
    # Analyze each station
    for station_name, predictions in stations.items():
        print(f"\n📍 {station_name}:")
        print(f"   Total predictions: {len(predictions)}")
        
        # Check date coverage
        dates = [pred.target_date for pred in predictions]
        unique_dates = set(dates)
        print(f"   Unique dates: {len(unique_dates)}")
        print(f"   Expected for November: 30 days")
        
        # Check for actual duplicates within this station
        from collections import Counter
        date_counts = Counter(dates)
        duplicates = {date: count for date, count in date_counts.items() if count > 1}
        
        if duplicates:
            print(f"   ⚠️  TRUE DUPLICATES within {station_name}:")
            for dup_date, count in duplicates.items():
                print(f"      {dup_date}: {count} predictions")
        else:
            print(f"   ✅ No duplicates within {station_name}")
        
        # Show sample predictions
        print(f"   📝 Sample predictions:")
        for pred in predictions[:3]:
            print(f"      {pred.target_date}: {pred.predicted_discharge:.2f} m³/s")

def analyze_monthly_forecast_issue():
    """Analyze why monthly forecast failed"""
    
    print("\n" + "=" * 80)
    print("ANALYZING MONTHLY FORECAST FAILURE")
    print("=" * 80)
    
    # Check monthly forecasts for November 2025
    november_forecasts = MonthlyForecast.objects.filter(
        target_year=2025,
        target_month=11
    )
    
    print(f"📅 November 2025 monthly forecasts: {november_forecasts.count()}")
    
    for forecast in november_forecasts:
        print(f"\n🏭 {forecast.station.name}:")
        print(f"   Status: {forecast.processing_status}")
        print(f"   Daily forecasts counted: {forecast.total_daily_forecasts}")
        
        # Check actual predictions for this station
        station_predictions = DischargePrediction.objects.filter(
            station=forecast.station,
            target_date__year=2025,
            target_date__month=11
        )
        
        actual_count = station_predictions.count()
        print(f"   Actual predictions in database: {actual_count}")
        
        if actual_count != 30:
            print(f"   ❌ ISSUE: Expected 30, found {actual_count}")
            
            # Check for duplicates in this specific station
            dates = [pred.target_date for pred in station_predictions]
            from collections import Counter
            date_counts = Counter(dates)
            duplicates = {date: count for date, count in date_counts.items() if count > 1}
            
            if duplicates:
                print(f"   🔍 Duplicates found:")
                for dup_date, count in list(duplicates.items())[:3]:
                    dup_preds = station_predictions.filter(target_date=dup_date)
                    print(f"      {dup_date} ({count} predictions):")
                    for i, pred in enumerate(dup_preds):
                        print(f"         #{i+1}: {pred.predicted_discharge:.2f} m³/s (ID: {str(pred.id)[:8]})")
        else:
            print(f"   ✅ Correct count: {actual_count} predictions")

def check_station_specific_issues():
    """Check each station individually for November 2025"""
    
    print("\n" + "=" * 80)
    print("STATION-BY-STATION NOVEMBER 2025 ANALYSIS")
    print("=" * 80)
    
    stations = DischargeStation.objects.all()
    
    for station in stations:
        print(f"\n🏭 {station.name} (ID: {station.station_id}):")
        
        # Get November 2025 predictions for this station
        november_preds = DischargePrediction.objects.filter(
            station=station,
            target_date__year=2025,
            target_date__month=11
        ).order_by('target_date')
        
        count = november_preds.count()
        print(f"   November 2025 predictions: {count}")
        
        if count == 0:
            print(f"   ✅ No November 2025 predictions - not the problem")
            continue
        
        # Check for duplicates
        dates = [pred.target_date for pred in november_preds]
        unique_dates = len(set(dates))
        
        print(f"   Unique dates covered: {unique_dates}")
        print(f"   Expected for complete month: 30")
        
        if count > 30:
            print(f"   ⚠️  EXCESS DATA: {count - 30} extra predictions")
            
            # Find duplicates
            from collections import Counter
            date_counts = Counter(dates)
            duplicates = {date: count for date, count in date_counts.items() if count > 1}
            
            if duplicates:
                print(f"   🔍 Duplicate dates ({len(duplicates)} dates affected):")
                for dup_date, dup_count in list(duplicates.items())[:5]:
                    dup_predictions = november_preds.filter(target_date=dup_date)
                    print(f"      {dup_date} ({dup_count} predictions):")
                    for pred in dup_predictions:
                        print(f"         {pred.predicted_discharge:.2f} m³/s | {pred.model_name} | {str(pred.id)[:8]}")
        elif count == 30:
            print(f"   ✅ Perfect count - no issues")
        else:
            print(f"   ⚠️  INCOMPLETE: Missing {30 - count} predictions")

def recommend_solution():
    """Recommend the appropriate solution"""
    
    print("\n" + "=" * 80)
    print("SOLUTION RECOMMENDATION")
    print("=" * 80)
    
    # Check if issue is cross-station confusion or within-station duplicates
    all_stations = DischargeStation.objects.all()
    
    problematic_stations = []
    clean_stations = []
    
    for station in all_stations:
        november_count = DischargePrediction.objects.filter(
            station=station,
            target_date__year=2025,
            target_date__month=11
        ).count()
        
        if november_count == 30:
            clean_stations.append(station.name)
        elif november_count > 30:
            problematic_stations.append((station.name, november_count))
        # november_count < 30 or == 0 is not a problem for monthly aggregation
    
    print(f"📊 Analysis Summary:")
    print(f"   Clean stations (30 predictions): {clean_stations}")
    print(f"   Problematic stations (>30 predictions): {problematic_stations}")
    
    if len(problematic_stations) == 1 and problematic_stations[0][1] == 54:
        print(f"\n🎯 ROOT CAUSE IDENTIFIED:")
        print(f"   Station '{problematic_stations[0][0]}' has 54 predictions (should be 30)")
        print(f"   This is TRUE DUPLICATES within a single station, not cross-station confusion")
        
        print(f"\n🔧 RECOMMENDED SOLUTION:")
        print(f"   1. Remove duplicate predictions for '{problematic_stations[0][0]}'")
        print(f"   2. Keep realistic discharge values, remove erroneous high values")
        print(f"   3. Re-run monthly aggregation for this station")
        
        return problematic_stations[0][0]
    else:
        print(f"\n🔍 COMPLEX ISSUE:")
        print(f"   Multiple stations affected or unexpected pattern")
        print(f"   Manual investigation required")
        
        return None

if __name__ == "__main__":
    print("🔍 NOVEMBER 2025 MULTI-STATION DUPLICATE INVESTIGATION")
    print("Checking if 'duplicates' are actually from different stations")
    print("")
    
    try:
        investigate_november_stations()
        analyze_monthly_forecast_issue()
        check_station_specific_issues()
        problematic_station = recommend_solution()
        
        if problematic_station:
            print(f"\n✅ SOLUTION IDENTIFIED:")
            print(f"Fix duplicate predictions in '{problematic_station}' station")
        else:
            print(f"\n⚠️  COMPLEX ISSUE:")
            print(f"Manual investigation needed")
        
    except Exception as e:
        print(f"❌ Error during investigation: {e}")
        import traceback
        traceback.print_exc()