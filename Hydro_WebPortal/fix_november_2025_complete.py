#!/usr/bin/env python
"""
Comprehensive fix for November 2025 duplicate predictions
This script will clean the data and re-run monthly aggregation
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

def analyze_problem():
    """Step 1: Analyze the exact problem"""
    
    print("=" * 70)
    print("STEP 1: ANALYZING THE PROBLEM")
    print("=" * 70)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Get November 2025 predictions
    november_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11
    ).order_by('target_date', 'predicted_discharge')
    
    total_count = november_predictions.count()
    expected_days = 30  # November has 30 days
    
    print(f"📊 Current State:")
    print(f"   Expected predictions: {expected_days} (30 days in November)")
    print(f"   Actual predictions: {total_count}")
    print(f"   Problem: {total_count - expected_days} extra predictions")
    
    # Analyze discharge patterns
    normal_predictions = november_predictions.filter(predicted_discharge__lte=1000)
    high_predictions = november_predictions.filter(predicted_discharge__gt=1000)
    
    print(f"\n⚡ Discharge Analysis:")
    print(f"   Normal discharge predictions (≤1000 m³/s): {normal_predictions.count()}")
    print(f"   Erroneous high predictions (>1000 m³/s): {high_predictions.count()}")
    
    # Show samples
    print(f"\n📝 Sample Normal Predictions:")
    for pred in normal_predictions[:3]:
        print(f"   {pred.target_date}: {pred.predicted_discharge:.2f} m³/s")
    
    print(f"\n⚠️  Sample Erroneous Predictions:")
    for pred in high_predictions[:3]:
        print(f"   {pred.target_date}: {pred.predicted_discharge:.2f} m³/s (ABNORMAL)")
    
    # Check if removing high predictions gives us exactly 30
    if normal_predictions.count() == expected_days:
        print(f"\n✅ SOLUTION IDENTIFIED:")
        print(f"   Removing {high_predictions.count()} erroneous predictions")
        print(f"   Will leave exactly {normal_predictions.count()} normal predictions")
        return True
    else:
        print(f"\n❌ COMPLEX ISSUE:")
        print(f"   Removing high predictions would leave {normal_predictions.count()} predictions")
        print(f"   This doesn't match the expected {expected_days} days")
        return False

def fix_duplicate_data():
    """Step 2: Remove erroneous high discharge predictions"""
    
    print("\n" + "=" * 70)
    print("STEP 2: FIXING DUPLICATE DATA")
    print("=" * 70)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Find erroneous predictions (discharge > 1000 m³/s)
    erroneous_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11,
        predicted_discharge__gt=1000
    )
    
    erroneous_count = erroneous_predictions.count()
    
    if erroneous_count == 0:
        print("✅ No erroneous predictions found to remove")
        return True
    
    print(f"🗑️  Found {erroneous_count} erroneous predictions to remove:")
    
    # Show what will be deleted
    for pred in erroneous_predictions[:5]:
        print(f"   DELETE: {pred.target_date} | {pred.predicted_discharge:.2f} m³/s | ID: {str(pred.id)[:8]}")
    
    if erroneous_count > 5:
        print(f"   ... and {erroneous_count - 5} more")
    
    # Confirm deletion
    print(f"\n🔄 Ready to delete {erroneous_count} erroneous predictions.")
    response = input("Proceed with deletion? (y/n): ").strip().lower()
    
    if response != 'y':
        print("❌ Deletion cancelled by user")
        return False
    
    # Delete the erroneous predictions
    deleted_count, _ = erroneous_predictions.delete()
    print(f"✅ Successfully deleted {deleted_count} erroneous predictions")
    
    # Verify the fix
    remaining_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11
    )
    
    final_count = remaining_predictions.count()
    print(f"✅ November 2025 now has {final_count} predictions")
    
    if final_count == 30:
        print("🎉 Perfect! Exactly 30 predictions (1 per day)")
        return True
    else:
        print(f"⚠️  Expected 30, got {final_count}. May need further investigation.")
        return False

def rerun_monthly_aggregation():
    """Step 3: Re-run monthly aggregation for November 2025"""
    
    print("\n" + "=" * 70)
    print("STEP 3: RE-RUNNING MONTHLY AGGREGATION")
    print("=" * 70)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Get the monthly forecast record
    try:
        monthly_forecast = MonthlyForecast.objects.get(
            station=station,
            target_year=2025,
            target_month=11
        )
        print(f"📋 Found existing monthly forecast record")
        print(f"   Current status: {monthly_forecast.processing_status}")
    except MonthlyForecast.DoesNotExist:
        # Create new record if it doesn't exist
        monthly_forecast = MonthlyForecast.objects.create(
            station=station,
            target_year=2025,
            target_month=11,
            processing_status='pending'
        )
        print(f"📋 Created new monthly forecast record")
    
    # Reset status to pending
    monthly_forecast.processing_status = 'pending'
    monthly_forecast.save()
    
    try:
        print(f"\n🔄 Running aggregation...")
        monthly_forecast.aggregate_daily_predictions()
        
        print(f"✅ Aggregation completed successfully!")
        print(f"   Status: {monthly_forecast.processing_status}")
        print(f"   Daily forecasts: {monthly_forecast.total_daily_forecasts}")
        
        if monthly_forecast.mean_discharge:
            print(f"   Mean discharge: {monthly_forecast.mean_discharge:.2f} m³/s")
        
        if monthly_forecast.total_energy_mwh:
            print(f"   Total monthly energy: {monthly_forecast.total_energy_mwh:.2f} MWh")
            print(f"   Daily energy (avg method): {monthly_forecast.mean_energy_mwh:.2f} MWh/day")
        
        return True
        
    except Exception as e:
        print(f"❌ Aggregation failed with error: {e}")
        return False

def verify_solution():
    """Step 4: Verify the complete solution"""
    
    print("\n" + "=" * 70)
    print("STEP 4: VERIFYING COMPLETE SOLUTION")
    print("=" * 70)
    
    station = DischargeStation.objects.get(name="Lower likhu")
    
    # Check daily predictions
    november_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11
    ).order_by('target_date')
    
    prediction_count = november_predictions.count()
    print(f"📊 Daily Predictions Check:")
    print(f"   Total predictions: {prediction_count}")
    print(f"   Expected: 30 (November has 30 days)")
    print(f"   Status: {'✅ CORRECT' if prediction_count == 30 else '❌ INCORRECT'}")
    
    # Check monthly forecast
    try:
        monthly_forecast = MonthlyForecast.objects.get(
            station=station,
            target_year=2025,
            target_month=11
        )
        
        print(f"\n📋 Monthly Forecast Check:")
        print(f"   Processing status: {monthly_forecast.processing_status}")
        print(f"   Daily forecasts aggregated: {monthly_forecast.total_daily_forecasts}")
        
        if monthly_forecast.processing_status == 'completed':
            print(f"   ✅ MONTHLY FORECAST: SUCCESSFUL")
            print(f"   Mean discharge: {monthly_forecast.mean_discharge:.2f} m³/s")
            print(f"   Total energy: {monthly_forecast.total_energy_mwh:.2f} MWh")
            print(f"   Daily energy: {monthly_forecast.mean_energy_mwh:.2f} MWh/day")
        else:
            print(f"   ❌ MONTHLY FORECAST: {monthly_forecast.processing_status}")
            
    except MonthlyForecast.DoesNotExist:
        print(f"\n❌ Monthly forecast record not found!")
    
    # Show sample daily predictions
    print(f"\n📝 Sample Daily Predictions (first 5):")
    for pred in november_predictions[:5]:
        energy_str = f"{pred.predicted_energy:.2f} MWh" if pred.predicted_energy else "None"
        print(f"   {pred.target_date}: {pred.predicted_discharge:.2f} m³/s, Energy: {energy_str}")
    
    print(f"\n🎉 SOLUTION SUMMARY:")
    if prediction_count == 30 and monthly_forecast.processing_status == 'completed':
        print("   ✅ Problem FULLY RESOLVED!")
        print("   ✅ November 2025 monthly energy calculation working correctly")
        print("   ✅ Using average monthly discharge method as preferred")
    else:
        print("   ⚠️  Issue may need further investigation")

def main():
    """Main execution function"""
    
    print("🔧 NOVEMBER 2025 DUPLICATE PREDICTIONS FIX")
    print("This script will clean your data and restore monthly energy calculations")
    print("")
    
    try:
        # Step 1: Analyze the problem
        can_fix = analyze_problem()
        
        if not can_fix:
            print("\n❌ Cannot automatically fix this issue. Manual investigation needed.")
            return
        
        # Step 2: Fix duplicate data
        if not fix_duplicate_data():
            print("\n❌ Data cleanup failed or was cancelled")
            return
        
        # Step 3: Re-run monthly aggregation
        if not rerun_monthly_aggregation():
            print("\n❌ Monthly aggregation failed")
            return
        
        # Step 4: Verify the solution
        verify_solution()
        
        print("\n" + "=" * 70)
        print("🎉 NOVEMBER 2025 FIX COMPLETED SUCCESSFULLY!")
        print("   You can now view results in Django admin or run view_results.py")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()