#!/usr/bin/env python
"""
Fix November 2025 duplicate predictions by removing erroneous high discharge values
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

def analyze_duplicates():
    """Analyze the duplicate predictions to understand which ones to remove"""
    
    print("=" * 60)
    print("ANALYZING NOVEMBER 2025 DUPLICATE PREDICTIONS")
    print("=" * 60)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Get November 2025 predictions
    november_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11
    ).order_by('target_date', 'predicted_discharge')
    
    # Group by date
    from collections import defaultdict
    by_date = defaultdict(list)
    
    for pred in november_predictions:
        by_date[pred.target_date].append(pred)
    
    print("Duplicate analysis (showing first 5 dates):")
    print("Format: Date | Discharge 1 vs Discharge 2 | Recommendation")
    print("-" * 70)
    
    normal_count = 0
    high_count = 0
    
    for i, (date_key, predictions) in enumerate(sorted(by_date.items())[:5]):
        if len(predictions) == 2:
            pred1, pred2 = predictions
            discharge1, discharge2 = pred1.predicted_discharge, pred2.predicted_discharge
            
            print(f"{date_key} | {discharge1:.2f} vs {discharge2:.2f} m³/s", end="")
            
            # Identify which one looks erroneous
            if discharge1 > 1000:  # Abnormally high
                print(f" | Keep {discharge2:.2f}, Remove {discharge1:.2f} (too high)")
                high_count += 1
            elif discharge2 > 1000:  # Abnormally high
                print(f" | Keep {discharge1:.2f}, Remove {discharge2:.2f} (too high)")
                high_count += 1
            else:
                print(f" | Both seem normal - manual review needed")
                normal_count += 1
    
    print(f"\nSummary:")
    print(f"- Dates with high discharge duplicates: {high_count}")
    print(f"- Dates with normal discharge duplicates: {normal_count}")
    
    # Count total erroneous predictions
    erroneous_predictions = november_predictions.filter(predicted_discharge__gt=1000)
    normal_predictions = november_predictions.filter(predicted_discharge__lte=1000)
    
    print(f"\nTotal predictions analysis:")
    print(f"- Normal discharge predictions (≤1000 m³/s): {normal_predictions.count()}")
    print(f"- Erroneous high discharge predictions (>1000 m³/s): {erroneous_predictions.count()}")
    
    return erroneous_predictions, normal_predictions

def fix_duplicates_option1():
    """Option 1: Remove all predictions with discharge > 1000 m³/s (automatic)"""
    
    print("\n" + "=" * 60)
    print("OPTION 1: AUTOMATIC CLEANUP (Remove discharge > 1000 m³/s)")
    print("=" * 60)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Find erroneous predictions
    erroneous_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11,
        predicted_discharge__gt=1000  # Remove abnormally high values
    )
    
    erroneous_count = erroneous_predictions.count()
    print(f"Found {erroneous_count} erroneous predictions (discharge > 1000 m³/s)")
    
    if erroneous_count > 0:
        print("\nSample erroneous predictions to be removed:")
        for pred in erroneous_predictions[:5]:
            print(f"   {pred.target_date}: {pred.predicted_discharge:.2f} m³/s (ID: {pred.id})")
        
        # Show what will remain
        normal_predictions = DischargePrediction.objects.filter(
            station=station,
            target_date__year=2025,
            target_date__month=11,
            predicted_discharge__lte=1000
        )
        
        remaining_count = normal_predictions.count()
        print(f"\nAfter cleanup, {remaining_count} normal predictions will remain")
        
        # Verify this gives us exactly 30 predictions
        if remaining_count == 30:
            print("✅ Perfect! This will give us exactly 30 predictions for November")
            
            print("\nExecute cleanup? (y/n):", end=" ")
            response = input().strip().lower()
            
            if response == 'y':
                deleted_count, _ = erroneous_predictions.delete()
                print(f"✅ Deleted {deleted_count} erroneous predictions")
                
                # Verify the fix
                final_count = DischargePrediction.objects.filter(
                    station=station,
                    target_date__year=2025,
                    target_date__month=11
                ).count()
                
                print(f"✅ November 2025 now has {final_count} predictions")
                
                if final_count == 30:
                    print("✅ Perfect! Now try re-running monthly aggregation")
                    return True
            else:
                print("❌ Cleanup cancelled")
        else:
            print(f"⚠️  This would leave {remaining_count} predictions, not the expected 30")
            print("Manual review may be needed")
    
    return False

def rerun_monthly_aggregation():
    """Re-run monthly aggregation for November 2025 after cleanup"""
    
    print("\n" + "=" * 60)
    print("RE-RUNNING NOVEMBER 2025 MONTHLY AGGREGATION")
    print("=" * 60)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Get or create monthly forecast
    monthly_forecast, created = MonthlyForecast.objects.get_or_create(
        station=station,
        target_year=2025,
        target_month=11,
        defaults={'processing_status': 'pending'}
    )
    
    print(f"Monthly forecast record: {'Created' if created else 'Found existing'}")
    print(f"Current status: {monthly_forecast.processing_status}")
    
    # Run aggregation
    try:
        print("\nRunning aggregation...")
        monthly_forecast.aggregate_daily_predictions()
        
        print(f"✅ Aggregation completed!")
        print(f"Status: {monthly_forecast.processing_status}")
        print(f"Daily forecasts: {monthly_forecast.total_daily_forecasts}")
        print(f"Mean discharge: {monthly_forecast.mean_discharge:.2f} m³/s")
        print(f"Total energy: {monthly_forecast.total_energy_mwh:.2f} MWh")
        
        return True
        
    except Exception as e:
        print(f"❌ Aggregation failed: {e}")
        return False

def show_final_results():
    """Show final November 2025 results"""
    
    print("\n" + "=" * 60)
    print("FINAL NOVEMBER 2025 RESULTS")
    print("=" * 60)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    monthly_forecast = MonthlyForecast.objects.get(
        station=station,
        target_year=2025,
        target_month=11
    )
    
    print(f"Station: {station.name}")
    print(f"Period: November 2025")
    print(f"Status: {monthly_forecast.processing_status}")
    print(f"Daily forecasts: {monthly_forecast.total_daily_forecasts}")
    print(f"Mean discharge: {monthly_forecast.mean_discharge:.2f} m³/s")
    print(f"Total monthly energy: {monthly_forecast.total_energy_mwh:.2f} MWh")
    print(f"Daily energy from avg discharge: {monthly_forecast.mean_energy_mwh:.2f} MWh/day")

if __name__ == "__main__":
    # Step 1: Analyze the duplicates
    erroneous, normal = analyze_duplicates()
    
    # Step 2: Offer automatic cleanup
    if fix_duplicates_option1():
        # Step 3: Re-run aggregation
        if rerun_monthly_aggregation():
            # Step 4: Show results
            show_final_results()
        else:
            print("❌ Failed to re-run aggregation")
    else:
        print("❌ Cleanup not completed")