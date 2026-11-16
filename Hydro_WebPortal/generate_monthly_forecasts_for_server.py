#!/usr/bin/env python3
"""
Generate Monthly Forecasts for Server Deployment
===============================================

This script will generate monthly forecast data for your server after deployment.
Run this AFTER uploading the updated code and running migrations.

Usage on server:
    python manage.py shell < generate_monthly_forecasts_for_server.py
"""
import os
import django
from datetime import date, datetime
from calendar import monthrange

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, MonthlyForecast, DischargePrediction

def generate_monthly_forecasts_from_existing_data():
    """Generate MonthlyForecast records from existing daily predictions"""
    
    print("=" * 70)
    print("🚀 GENERATING MONTHLY FORECASTS FOR SERVER")
    print("=" * 70)
    
    # Get all stations
    stations = DischargeStation.objects.all()
    if not stations.exists():
        print("❌ No stations found! Please create stations first.")
        return
    
    print(f"✅ Found {stations.count()} stations")
    
    # Get all months that have daily predictions
    existing_predictions = DischargePrediction.objects.values(
        'station', 'target_date__year', 'target_date__month'
    ).distinct().order_by('target_date__year', 'target_date__month')
    
    if not existing_predictions:
        print("❌ No daily predictions found! Generate daily predictions first.")
        return
    
    print(f"✅ Found daily predictions for {len(existing_predictions)} station-month combinations")
    
    monthly_forecasts_created = 0
    monthly_forecasts_updated = 0
    
    for pred_data in existing_predictions:
        try:
            station = DischargeStation.objects.get(id=pred_data['station'])
            year = pred_data['target_date__year']
            month = pred_data['target_date__month']
            
            print(f"\n📊 Processing {station.name} - {year}-{month:02d}")
            
            # Check if monthly forecast already exists
            monthly_forecast, created = MonthlyForecast.objects.get_or_create(
                station=station,
                target_year=year,
                target_month=month,
                defaults={
                    'processing_status': 'pending'
                }
            )
            
            if created:
                print(f"   ✅ Created new MonthlyForecast record")
                monthly_forecasts_created += 1
            else:
                print(f"   📋 Found existing MonthlyForecast record")
                monthly_forecasts_updated += 1
            
            # Run aggregation to calculate energy values
            print(f"   🔄 Running energy calculations...")
            monthly_forecast.aggregate_daily_predictions()
            
            # Check results
            if monthly_forecast.processing_status == 'completed':
                print(f"   ✅ Energy calculation successful!")
                print(f"      Total Energy: {monthly_forecast.total_energy_mwh:.2f} MWh")
                print(f"      Daily Energy: {monthly_forecast.mean_energy_mwh:.2f} MWh/day")
                print(f"      Average Discharge: {monthly_forecast.mean_discharge:.2f} m³/s")
            else:
                print(f"   ⚠️  Energy calculation status: {monthly_forecast.processing_status}")
            
        except Exception as e:
            print(f"   ❌ Error processing {station.name} - {year}-{month:02d}: {str(e)}")
            continue
    
    print("\n" + "=" * 70)
    print("📊 MONTHLY FORECAST GENERATION COMPLETE")
    print("=" * 70)
    print(f"✅ Monthly forecasts created: {monthly_forecasts_created}")
    print(f"📋 Monthly forecasts updated: {monthly_forecasts_updated}")
    
    # Show final summary
    total_monthly_forecasts = MonthlyForecast.objects.count()
    completed_monthly_forecasts = MonthlyForecast.objects.filter(processing_status='completed').count()
    
    print(f"\n📈 FINAL DATABASE STATUS:")
    print(f"   Total MonthlyForecast records: {total_monthly_forecasts}")
    print(f"   Completed records: {completed_monthly_forecasts}")
    print(f"   Success rate: {(completed_monthly_forecasts/total_monthly_forecasts*100):.1f}%" if total_monthly_forecasts > 0 else "   Success rate: 0%")
    
    if completed_monthly_forecasts > 0:
        print(f"\n🎉 SUCCESS! Your Monthly Energy Forecast table should now show data!")
        print(f"   Go to: /admin/discharge_prediction/monthlyforecast/ to view records")
        print(f"   Check dashboard: Monthly Energy Forecast table should populate")
    else:
        print(f"\n⚠️  No completed monthly forecasts. Check if daily predictions have energy data.")

def show_sample_results():
    """Show sample monthly forecast results"""
    
    print(f"\n" + "=" * 50)
    print("🔍 SAMPLE MONTHLY FORECAST RESULTS")
    print("=" * 50)
    
    sample_forecasts = MonthlyForecast.objects.filter(
        processing_status='completed'
    ).order_by('-target_year', '-target_month')[:3]
    
    if not sample_forecasts:
        print("❌ No completed monthly forecasts found")
        return
    
    for forecast in sample_forecasts:
        month_name = date(forecast.target_year, forecast.target_month, 1).strftime('%B')
        total_e = f"{forecast.total_energy_mwh:.2f}" if forecast.total_energy_mwh is not None else "N/A"
        daily_e = f"{forecast.mean_energy_mwh:.2f}" if forecast.mean_energy_mwh is not None else "N/A"
        avg_q = f"{forecast.mean_discharge:.2f}" if forecast.mean_discharge is not None else "N/A"
        print(f"\n📊 {forecast.station.name} - {month_name} {forecast.target_year}")
        print(f"   Total Energy: {total_e} MWh")
        print(f"   Daily Energy: {daily_e} MWh/day")
        print(f"   Avg Discharge: {avg_q} m³/s")
        print(f"   Daily Forecasts: {forecast.total_daily_forecasts}")

if __name__ == "__main__":
    generate_monthly_forecasts_from_existing_data()
    show_sample_results()
    
    print(f"\n" + "=" * 70)
    print("🚀 NEXT STEPS:")
    print("1. Check Django Admin: /admin/discharge_prediction/monthlyforecast/")
    print("2. Test Dashboard: Monthly Energy Forecast table should show data")
    print("3. Test Export CSV: Should include energy columns")
    print("=" * 70)