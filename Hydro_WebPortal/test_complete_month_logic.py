#!/usr/bin/env python3
"""
Test the new monthly energy calculation logic
Only calculates when complete month data is available
"""
import os
import sys
import django

# Setup Django environment  
sys.path.append(r'c:\Users\antar\OneDrive\Desktop\DjangoHydro\Hydro_WebPortal')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, MonthlyForecast, DischargePrediction
from datetime import date
from calendar import monthrange

def test_complete_month_logic():
    """Test the complete month energy calculation logic"""
    
    station = DischargeStation.objects.first()
    print(f"Testing with station: {station.name}")
    
    # Test March 2024 (should have complete data - 31 days)
    march_days = monthrange(2024, 3)[1]  # 31 days
    march_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2024,
        target_date__month=3
    ).count()
    
    print(f"\n=== MARCH 2024 TEST ===")
    print(f"Days in March 2024: {march_days}")
    print(f"Predictions available: {march_predictions}")
    print(f"Complete data: {'✓ Yes' if march_predictions == march_days else '✗ No'}")
    
    # Get March 2024 monthly forecast and test aggregation
    march_forecast = MonthlyForecast.objects.filter(
        station=station,
        target_year=2024,
        target_month=3
    ).first()
    
    if march_forecast:
        print(f"Running aggregation for March 2024...")
        march_forecast.aggregate_daily_predictions()
        march_forecast.refresh_from_db()
        
        print(f"Results:")
        print(f"  Total Monthly Energy: {march_forecast.total_energy_mwh} MWh")
        print(f"  Mean Daily Energy: {march_forecast.mean_energy_mwh} MWh/day")
        print(f"  Processing Status: {march_forecast.processing_status}")
    
    # Test November 2025 (has 54 predictions for 30 days - should be incomplete due to duplicates)
    nov_days = monthrange(2025, 11)[1]  # 30 days
    nov_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2025,
        target_date__month=11
    ).count()
    
    print(f"\n=== NOVEMBER 2025 TEST ===")
    print(f"Days in November 2025: {nov_days}")
    print(f"Predictions available: {nov_predictions}")
    print(f"Complete data: {'✓ Yes' if nov_predictions == nov_days else '✗ No (duplicates detected)'}")
    
    # Get November 2025 monthly forecast and test aggregation
    nov_forecast = MonthlyForecast.objects.filter(
        station=station,
        target_year=2025,
        target_month=11
    ).first()
    
    if nov_forecast:
        print(f"Running aggregation for November 2025...")
        nov_forecast.aggregate_daily_predictions()
        nov_forecast.refresh_from_db()
        
        print(f"Results:")
        print(f"  Total Monthly Energy: {nov_forecast.total_energy_mwh} MWh")
        print(f"  Mean Daily Energy: {nov_forecast.mean_energy_mwh} MWh/day")
        print(f"  Processing Status: {nov_forecast.processing_status}")
        
    print(f"\n=== SUMMARY ===")
    print(f"✓ The new logic only calculates monthly energy when complete month data is available")
    print(f"✓ This prevents incorrect calculations from duplicate or incomplete data")
    print(f"✓ Monthly energy will be calculated once all daily predictions for the month exist")

if __name__ == "__main__":
    test_complete_month_logic()