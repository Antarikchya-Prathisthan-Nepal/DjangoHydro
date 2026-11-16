#!/usr/bin/env python3
"""
Debug test for monthly energy aggregation 
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
from django.db.models import Avg, Min, Max, StdDev, Count, Sum

def debug_aggregation():
    """Debug the aggregation to see what's going wrong"""
    station = DischargeStation.objects.first()
    
    # Check if we have daily predictions
    daily_predictions = DischargePrediction.objects.filter(
        station=station,
        target_date__year=2024,
        target_date__month=3,
        forecast_type='daily'
    )
    
    print(f"Found {daily_predictions.count()} daily predictions")
    
    # Check the first few to see their values
    for pred in daily_predictions[:5]:
        print(f"{pred.target_date}: discharge={pred.predicted_discharge}, energy={pred.predicted_energy}")
    
    # Test the aggregation manually
    aggregation_result = daily_predictions.aggregate(
        mean_discharge=Avg('predicted_discharge'),
        min_discharge=Min('predicted_discharge'),
        max_discharge=Max('predicted_discharge'),
        std_discharge=StdDev('predicted_discharge'),
        count=Count('id'),
        avg_confidence=Avg('prediction_confidence'),
        # Energy aggregations
        total_energy=Sum('predicted_energy'),
        mean_energy=Avg('predicted_energy'),
        min_energy=Min('predicted_energy'),
        max_energy=Max('predicted_energy'),
        std_energy=StdDev('predicted_energy')
    )
    
    print("\nAggregation results:")
    for key, value in aggregation_result.items():
        print(f"  {key}: {value}")
    
    # Check the monthly forecast
    monthly_forecast = MonthlyForecast.objects.filter(
        station=station,
        target_year=2024,
        target_month=3
    ).first()
    
    if monthly_forecast:
        print(f"\nMonthly forecast before aggregation:")
        print(f"  total_energy_mwh: {monthly_forecast.total_energy_mwh}")
        print(f"  mean_energy_mwh: {monthly_forecast.mean_energy_mwh}")
        
        # Call the aggregation method
        monthly_forecast.aggregate_daily_predictions()
        
        print(f"\nMonthly forecast after aggregation:")
        print(f"  total_energy_mwh: {monthly_forecast.total_energy_mwh}")
        print(f"  mean_energy_mwh: {monthly_forecast.mean_energy_mwh}")
        
if __name__ == "__main__":
    debug_aggregation()