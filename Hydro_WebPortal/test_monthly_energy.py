#!/usr/bin/env python3
"""
Test script for monthly energy predictions
Run this with: python manage.py shell < test_monthly_energy.py
"""

import os
import django
from datetime import date

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.prediction_utils import DischargePredictionEngine
from discharge_prediction.models import DischargeStation, MonthlyForecast, DischargePrediction

def test_monthly_energy_predictions():
    """Test monthly energy prediction functionality"""
    
    print("="*60)
    print("TESTING MONTHLY ENERGY PREDICTIONS")
    print("="*60)
    
    # Get first station for testing
    station = DischargeStation.objects.first()
    if not station:
        print("❌ No stations found in database. Please create a station first.")
        return
    
    print(f"✅ Testing with station: {station.name}")
    print(f"   Station ID: {station.station_id}")
    
    # Initialize prediction engine in demo mode
    print("\n📊 Initializing prediction engine (demo mode)...")
    engine = DischargePredictionEngine(simulate_mode=True)
    
    # Test monthly prediction for November 2025
    test_month = date(2025, 11, 1)
    print(f"\n🚀 Generating monthly forecast for {test_month.strftime('%B %Y')}...")
    
    try:
        # Generate monthly forecast
        monthly_forecast = engine.predict_monthly_discharge(station, test_month)
        
        print(f"✅ Monthly forecast completed!")
        print(f"   Status: {monthly_forecast.status}")
        print(f"   Processing Status: {monthly_forecast.processing_status}")
        
        # Check daily predictions created
        daily_count = DischargePrediction.objects.filter(
            station=station,
            target_date__year=2025,
            target_date__month=11
        ).count()
        print(f"   Daily predictions created: {daily_count}")
        
        # Get energy summary
        print(f"\n📈 Retrieving energy summary...")
        energy_summary = engine.get_monthly_energy_summary(station, 2025, 11)
        
        print(f"\n🔋 MONTHLY ENERGY RESULTS:")
        print(f"   📅 Month: {energy_summary['month_name']} {energy_summary['year']}")
        print(f"   ⚡ Total Monthly Energy: {energy_summary['total_monthly_energy_mwh']:.2f} MWh")
        print(f"   📊 Average Daily Energy: {energy_summary['average_daily_energy_mwh']:.2f} MWh/day")
        print(f"   📈 Max Daily Energy: {energy_summary['max_daily_energy_mwh']:.2f} MWh")
        print(f"   📉 Min Daily Energy: {energy_summary['min_daily_energy_mwh']:.2f} MWh")
        print(f"   🔢 Total Predictions: {energy_summary['total_predictions']}")
        
        # Check database record
        print(f"\n💾 DATABASE VERIFICATION:")
        monthly_record = MonthlyForecast.objects.filter(
            station=station,
            target_year=2025,
            target_month=11
        ).first()
        
        if monthly_record:
            print(f"   ✅ MonthlyForecast record found in database")
            print(f"   📊 DB Total Energy: {monthly_record.total_energy_mwh:.2f} MWh")
            print(f"   📊 DB Mean Energy: {monthly_record.mean_energy_mwh:.2f} MWh/day")
            print(f"   📊 DB Processing Status: {monthly_record.processing_status}")
        else:
            print(f"   ❌ No MonthlyForecast record found in database")
        
        print(f"\n🎉 Monthly energy prediction test completed successfully!")
        
        # Sample daily predictions
        print(f"\n📋 SAMPLE DAILY PREDICTIONS:")
        sample_predictions = DischargePrediction.objects.filter(
            station=station,
            target_date__year=2025,
            target_date__month=11
        ).order_by('target_date')[:5]
        
        for pred in sample_predictions:
            print(f"   {pred.target_date}: {pred.predicted_discharge:.1f} m³/s → {pred.predicted_energy:.1f} MWh")
            
    except Exception as e:
        print(f"❌ Error during monthly prediction: {str(e)}")
        import traceback
        traceback.print_exc()

def show_existing_monthly_forecasts():
    """Show existing monthly forecasts with energy data"""
    print(f"\n📋 EXISTING MONTHLY FORECASTS:")
    
    forecasts = MonthlyForecast.objects.all().order_by('-target_year', '-target_month')
    
    if not forecasts.exists():
        print("   No monthly forecasts found in database")
        return
    
    for forecast in forecasts:
        print(f"   {forecast.station.name} - {forecast.target_year}-{forecast.target_month:02d}")
        print(f"     Status: {forecast.processing_status}")
        if forecast.total_energy_mwh:
            print(f"     Energy: {forecast.total_energy_mwh:.1f} MWh total, {forecast.mean_energy_mwh:.1f} MWh/day avg")
        if forecast.mean_discharge:
            print(f"     Discharge: {forecast.mean_discharge:.1f} m³/s avg")
        print()

if __name__ == "__main__":
    # Show existing forecasts first
    show_existing_monthly_forecasts()
    
    # Run the test
    test_monthly_energy_predictions()
    
    print("\n" + "="*60)
    print("TEST COMPLETED - Check Django Admin for detailed view!")
    print("Go to: /admin/discharge_prediction/monthlyforecast/")
    print("="*60)