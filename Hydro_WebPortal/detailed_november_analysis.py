#!/usr/bin/env python
"""
Detailed analysis of November 2025 prediction data
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

def detailed_november_analysis():
    """Detailed analysis of all November 2025 predictions"""
    
    print("=" * 80)
    print("DETAILED NOVEMBER 2025 PREDICTION ANALYSIS")
    print("=" * 80)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Get all November 2025 predictions
    november_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11
    ).order_by('target_date', 'predicted_discharge')
    
    print(f"Total predictions: {november_predictions.count()}")
    
    # Group by date
    from collections import defaultdict
    by_date = defaultdict(list)
    
    for pred in november_predictions:
        by_date[pred.target_date].append(pred)
    
    print(f"Unique dates: {len(by_date)}")
    print(f"Expected dates in November: 30")
    
    print("\nAll predictions by date:")
    print("Date       | Count | Discharge Values")
    print("-" * 50)
    
    normal_dates = []
    duplicate_dates = []
    missing_dates = []
    
    # Check all dates 1-30
    for day in range(1, 31):
        target_date = date(2025, 11, day)
        predictions = by_date.get(target_date, [])
        
        if len(predictions) == 0:
            missing_dates.append(target_date)
            print(f"{target_date} |   0   | MISSING")
        elif len(predictions) == 1:
            normal_dates.append(target_date)
            discharge = predictions[0].predicted_discharge
            print(f"{target_date} |   1   | {discharge:.2f} m³/s")
        else:
            duplicate_dates.append(target_date)
            discharges = [p.predicted_discharge for p in predictions]
            discharge_str = ", ".join([f"{d:.2f}" for d in discharges])
            print(f"{target_date} |   {len(predictions)}   | {discharge_str} m³/s")
    
    print(f"\n📊 Summary:")
    print(f"✅ Normal dates (1 prediction): {len(normal_dates)}")
    print(f"⚠️  Duplicate dates (2+ predictions): {len(duplicate_dates)}")
    print(f"❌ Missing dates (0 predictions): {len(missing_dates)}")
    
    if missing_dates:
        print(f"\nMissing dates: {[d.strftime('%Y-%m-%d') for d in missing_dates]}")
    
    # Analyze discharge patterns
    all_discharges = [p.predicted_discharge for p in november_predictions]
    normal_discharges = [d for d in all_discharges if d <= 1000]
    high_discharges = [d for d in all_discharges if d > 1000]
    
    print(f"\n⚡ Discharge Analysis:")
    print(f"Normal discharge values (≤1000): {len(normal_discharges)}")
    print(f"High discharge values (>1000): {len(high_discharges)}")
    
    if normal_discharges:
        print(f"Normal discharge range: {min(normal_discharges):.2f} - {max(normal_discharges):.2f} m³/s")
    
    if high_discharges:
        unique_high = set(high_discharges)
        print(f"High discharge values: {unique_high}")
    
    return normal_dates, duplicate_dates, missing_dates

def recommend_fix_strategy():
    """Recommend the best fix strategy"""
    
    print("\n" + "=" * 80)
    print("RECOMMENDED FIX STRATEGY")
    print("=" * 80)
    
    normal_dates, duplicate_dates, missing_dates = detailed_november_analysis()
    
    if len(missing_dates) > 0:
        print(f"❌ PROBLEM: Missing {len(missing_dates)} dates in November")
        print("This means you don't have complete data for the month yet.")
        print("Monthly energy calculation requires all 30 days.")
        
        print(f"\nMissing dates that need predictions:")
        for missing_date in missing_dates:
            print(f"   - {missing_date}")
        
        print(f"\n🔧 SOLUTION OPTIONS:")
        print(f"1. Generate predictions for missing dates first")
        print(f"2. Or accept that November 2025 is incomplete and wait for more data")
        
        return "incomplete_data"
    
    elif len(duplicate_dates) > 0:
        print(f"⚠️  PROBLEM: Duplicate predictions for {len(duplicate_dates)} dates")
        print("Each date should have exactly 1 prediction.")
        
        print(f"\n🔧 SOLUTION:")
        print(f"Remove duplicate predictions (keep normal discharge values, remove high values)")
        
        return "remove_duplicates"
    
    else:
        print(f"✅ DATA LOOKS GOOD: {len(normal_dates)} dates with single predictions")
        return "data_ok"

def execute_duplicate_cleanup():
    """Execute the duplicate cleanup"""
    
    print("\n" + "=" * 80)
    print("EXECUTING DUPLICATE CLEANUP")
    print("=" * 80)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Strategy: For each date with duplicates, keep the normal discharge and remove high discharge
    november_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11
    ).order_by('target_date')
    
    # Group by date
    from collections import defaultdict
    by_date = defaultdict(list)
    
    for pred in november_predictions:
        by_date[pred.target_date].append(pred)
    
    predictions_to_delete = []
    
    for target_date, predictions in by_date.items():
        if len(predictions) > 1:
            # Find the prediction with normal discharge (≤1000) and high discharge (>1000)
            normal_preds = [p for p in predictions if p.predicted_discharge <= 1000]
            high_preds = [p for p in predictions if p.predicted_discharge > 1000]
            
            if len(normal_preds) == 1 and len(high_preds) >= 1:
                # Keep the normal prediction, delete the high ones
                predictions_to_delete.extend(high_preds)
                print(f"{target_date}: Keep {normal_preds[0].predicted_discharge:.2f} m³/s, Remove {len(high_preds)} high values")
            else:
                print(f"{target_date}: Complex case - {len(normal_preds)} normal, {len(high_preds)} high predictions")
    
    print(f"\nTotal predictions to delete: {len(predictions_to_delete)}")
    
    if len(predictions_to_delete) > 0:
        print(f"\nExecute deletion? (y/n): ", end="")
        response = input().strip().lower()
        
        if response == 'y':
            # Delete the predictions
            for pred in predictions_to_delete:
                pred.delete()
            
            print(f"✅ Deleted {len(predictions_to_delete)} duplicate predictions")
            
            # Verify final count
            final_count = DischargePrediction.objects.filter(
                station=station,
                target_date__year=2025,
                target_date__month=11
            ).count()
            
            print(f"✅ November 2025 now has {final_count} predictions")
            
            if final_count == 30:
                print("🎉 Perfect! Now try re-running monthly aggregation")
                return True
            else:
                print(f"⚠️  Expected 30 predictions, got {final_count}")
        else:
            print("❌ Cleanup cancelled")
    
    return False

if __name__ == "__main__":
    strategy = recommend_fix_strategy()
    
    if strategy == "remove_duplicates":
        if execute_duplicate_cleanup():
            print("\n🔄 Ready to re-run monthly aggregation for November 2025!")
    elif strategy == "incomplete_data":
        print("\n📝 You need to generate more predictions before calculating monthly energy")
    else:
        print("\n✅ Data is ready for monthly aggregation")