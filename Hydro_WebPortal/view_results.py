#!/usr/bin/env python3
"""
Simple script to view monthly energy results
"""
import os
import sys
import django

# Setup Django environment  
sys.path.append(r'c:\Users\antar\OneDrive\Desktop\DjangoHydro\Hydro_WebPortal')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import MonthlyForecast, DischargeStation

def show_monthly_energy_results():
    """Display monthly energy results in a simple format"""
    
    print("=" * 60)
    print("MONTHLY ENERGY PREDICTION RESULTS")
    print("=" * 60)
    
    # Get all monthly forecasts
    forecasts = MonthlyForecast.objects.all().order_by('-target_year', '-target_month')
    
    if not forecasts:
        print("No monthly forecasts found.")
        return
    
    for forecast in forecasts:
        print(f"\n{forecast.station.name} - {forecast.target_year}-{forecast.target_month:02d}")
        print("-" * 40)
        
        if forecast.total_energy_mwh is not None:
            print(f"✓ Status: {forecast.processing_status}")
            print(f"  Average Monthly Discharge: {forecast.mean_discharge:.2f} m³/s")
            print(f"  Daily Energy (from avg): {forecast.mean_energy_mwh:.2f} MWh/day")
            print(f"  Total Monthly Energy: {forecast.total_energy_mwh:.2f} MWh")
            print(f"  Energy Range: {forecast.min_energy_mwh:.1f} - {forecast.max_energy_mwh:.1f} MWh/day")
            print(f"  Daily Predictions Used: {forecast.total_daily_forecasts}")
        else:
            print(f"✗ Status: {forecast.processing_status}")
            print(f"  Energy calculation: Pending (incomplete data)")
            print(f"  Daily Predictions: {forecast.total_daily_forecasts}")
    
    print("\n" + "=" * 60)
    print("HOW TO ACCESS MORE DETAILS:")
    print("=" * 60)
    print("1. Django Admin: http://127.0.0.1:8000/admin/")
    print("   → Discharge prediction → Monthly forecasts")
    print("2. Run detailed test: python test_updated_average_method.py") 
    print("3. View this summary: python view_results.py")

if __name__ == "__main__":
    show_monthly_energy_results()