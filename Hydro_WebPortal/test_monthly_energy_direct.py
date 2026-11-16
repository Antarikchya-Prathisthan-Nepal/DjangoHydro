#!/usr/bin/env python3
"""
Direct test of monthly energy aggregation functionality
This bypasses the prediction engine and tests the energy calculation logic directly
"""
import os
import sys
import django
from datetime import datetime, date, timedelta
import random

# Setup Django environment  
sys.path.append(r'c:\Users\antar\OneDrive\Desktop\DjangoHydro\Hydro_WebPortal')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, MonthlyForecast, DischargePrediction

def create_test_daily_predictions(station, year, month, num_days):
    """Create test daily predictions with energy data"""
    daily_predictions = []
    
    for day in range(1, num_days + 1):
        target_date = date(year, month, day)
        
        # Generate random discharge between 5-25 m³/s
        discharge = random.uniform(5.0, 25.0)
        
        # Calculate energy using the station's parameters
        # Energy (MWh) = η × ρ × g × Q × H × 24 / 10^6
        # Where: η=efficiency, ρ=water_density(1000), g=gravity(9.81), Q=discharge, H=net_head
        
        efficiency = station.efficiency or 0.8827
        net_head = station.net_head or 115.5
        max_discharge = station.max_discharge_for_energy or 29.75
        
        # Cap discharge for energy calculation
        discharge_for_energy = min(discharge, max_discharge)
        
        # Calculate daily energy (MWh)
        power_mw = (efficiency * 1000 * 9.81 * discharge_for_energy * net_head) / 1e6
        daily_energy_mwh = power_mw * 24
        
        # Create the daily prediction record
        prediction = DischargePrediction.objects.create(
            station=station,
            target_date=target_date,
            predicted_discharge=discharge,
            predicted_energy=daily_energy_mwh,  # Note: field is predicted_energy, not predicted_energy_mwh
            model_name="test_model",
            forecast_type="monthly",
            processing_status="completed"
        )
        
        daily_predictions.append(prediction)
        print(f"Created prediction for {target_date}: {discharge:.2f} m³/s → {daily_energy_mwh:.2f} MWh")
    
    return daily_predictions

def test_monthly_energy_aggregation():
    """Test the monthly energy aggregation functionality"""
    print("Testing Monthly Energy Aggregation...")
    
    # Get a station for testing
    station = DischargeStation.objects.first()
    if not station:
        print("No stations found in database")
        return
        
    print(f"Testing with station: {station.name}")
    print(f"Station parameters:")
    print(f"  - Efficiency: {station.efficiency}")
    print(f"  - Net Head: {station.net_head} m")
    print(f"  - Max Discharge: {station.max_discharge_for_energy} m³/s")
    
    # Clean up any existing data for March 2024
    DischargePrediction.objects.filter(
        station=station,
        target_date__year=2024,
        target_date__month=3
    ).delete()
    
    MonthlyForecast.objects.filter(
        station=station,
        target_year=2024,
        target_month=3
    ).delete()
    
    # Create test daily predictions for March 2024 (31 days)
    print(f"\nCreating test daily predictions for March 2024...")
    daily_predictions = create_test_daily_predictions(station, 2024, 3, 31)
    
    # Create monthly forecast and aggregate the daily predictions
    print(f"\nCreating monthly forecast...")
    monthly_forecast = MonthlyForecast.objects.create(
        station=station,
        target_year=2024,
        target_month=3,
        processing_status="in_progress"
    )
    
    # Call the aggregation method
    print(f"Aggregating daily predictions...")
    monthly_forecast.aggregate_daily_predictions()
    
    # Refresh from database
    monthly_forecast.refresh_from_db()
    
    # Display results
    print(f"\n=== MONTHLY ENERGY RESULTS ===")
    print(f"Station: {station.name}")
    print(f"Period: March 2024")
    print(f"Processing Status: {monthly_forecast.processing_status}")
    print(f"Total Energy: {monthly_forecast.total_energy_mwh:.2f} MWh")
    print(f"Mean Energy: {monthly_forecast.mean_energy_mwh:.2f} MWh/day")
    print(f"Min Energy: {monthly_forecast.min_energy_mwh:.2f} MWh/day")
    print(f"Max Energy: {monthly_forecast.max_energy_mwh:.2f} MWh/day")
    print(f"Std Energy: {monthly_forecast.std_energy_mwh:.2f} MWh/day")
    print(f"Created: {monthly_forecast.created_at}")
    
    # Verify calculations
    total_calculated = sum(pred.predicted_energy for pred in daily_predictions)
    print(f"\nVerification:")
    print(f"Sum from daily predictions: {total_calculated:.2f} MWh")
    print(f"Total from monthly forecast: {monthly_forecast.total_energy_mwh:.2f} MWh")
    print(f"Match: {'✓' if abs(total_calculated - monthly_forecast.total_energy_mwh) < 0.01 else '✗'}")
    
    return monthly_forecast

if __name__ == "__main__":
    try:
        result = test_monthly_energy_aggregation()
        print(f"\n✓ Monthly energy aggregation test completed successfully!")
        
    except Exception as e:
        print(f"\n✗ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()