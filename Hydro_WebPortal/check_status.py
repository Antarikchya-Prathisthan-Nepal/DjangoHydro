#!/usr/bin/env python3
"""
Monthly Forecast Status Check
============================

Quick verification script to ensure all data is properly stored.
"""

import os
import sys
import django

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, DischargePrediction, MonthlyForecast
from django.db.models import Count, Min, Max

def check_database_status():
    """Quick database status check"""
    
    print("🔍 DATABASE STATUS CHECK")
    print("=" * 50)
    
    # Check stations
    stations = DischargeStation.objects.filter(is_active=True)
    print(f"🏭 Active stations: {stations.count()}")
    for station in stations:
        print(f"   - {station.name} ({station.station_id})")
    
    print()
    
    # Check daily predictions
    prediction_stats = DischargePrediction.objects.aggregate(
        total=Count('id'),
        min_date=Min('target_date'),
        max_date=Max('target_date')
    )
    
    print(f"📊 Daily Predictions:")
    print(f"   Total: {prediction_stats['total']}")
    print(f"   Date range: {prediction_stats['min_date']} to {prediction_stats['max_date']}")
    
    # Check predictions by station
    for station in stations:
        count = DischargePrediction.objects.filter(station=station).count()
        print(f"   - {station.name}: {count} predictions")
    
    print()
    
    # Check monthly forecasts
    forecast_stats = MonthlyForecast.objects.aggregate(
        total=Count('id'),
        completed=Count('id', filter=django.db.models.Q(processing_status='completed'))
    )
    
    print(f"📅 Monthly Forecasts:")
    print(f"   Total: {forecast_stats['total']}")
    print(f"   Completed: {forecast_stats['completed']}")
    
    # Check forecasts by station
    for station in stations:
        completed_count = MonthlyForecast.objects.filter(
            station=station, 
            processing_status='completed'
        ).count()
        total_count = MonthlyForecast.objects.filter(station=station).count()
        print(f"   - {station.name}: {completed_count}/{total_count} completed")
    
    print()
    
    # Check November 2025 status (the problematic month)
    print(f"🔍 November 2025 Status:")
    for station in stations:
        nov_predictions = DischargePrediction.objects.filter(
            station=station,
            target_date__year=2025,
            target_date__month=11
        ).count()
        
        nov_forecast = MonthlyForecast.objects.filter(
            station=station,
            target_year=2025,
            target_month=11
        ).first()
        
        forecast_status = nov_forecast.processing_status if nov_forecast else "Not created"
        
        print(f"   - {station.name}: {nov_predictions} predictions, forecast: {forecast_status}")
    
    print()
    print("✅ Status check completed!")

if __name__ == "__main__":
    check_database_status()