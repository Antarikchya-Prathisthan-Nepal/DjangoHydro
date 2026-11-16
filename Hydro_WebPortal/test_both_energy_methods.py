#!/usr/bin/env python3
"""
Test both energy calculation approaches:
1. Sum of daily energies (existing)
2. Average monthly discharge approach (new)
"""
import os
import sys
import django

# Setup Django environment  
sys.path.append(r'c:\Users\antar\OneDrive\Desktop\DjangoHydro\Hydro_WebPortal')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, MonthlyForecast
import json

def test_both_energy_calculation_methods():
    """Test and compare both energy calculation approaches"""
    
    station = DischargeStation.objects.first()
    print(f"Testing Energy Calculation Methods")
    print(f"Station: {station.name}")
    print(f"Station Parameters:")
    print(f"  - Efficiency: {station.efficiency}")
    print(f"  - Net Head: {station.net_head} m")
    print(f"  - Max Discharge for Energy: {station.max_discharge_for_energy} m³/s")
    
    # Test March 2024 (has complete data)
    march_forecast = MonthlyForecast.objects.filter(
        station=station,
        target_year=2024,
        target_month=3
    ).first()
    
    if march_forecast:
        print(f"\n" + "="*60)
        print(f"MARCH 2024 ENERGY CALCULATION COMPARISON")
        print(f"="*60)
        
        # Make sure we have the latest aggregation
        march_forecast.aggregate_daily_predictions()
        march_forecast.refresh_from_db()
        
        # Test the new average discharge method
        avg_discharge_result = march_forecast.calculate_monthly_energy_from_average_discharge()
        
        print(f"\nMETHOD 1: Sum of Daily Energies")
        print(f"  Total Monthly Energy: {march_forecast.total_energy_mwh:.2f} MWh")
        print(f"  Average Daily Energy: {march_forecast.mean_energy_mwh:.2f} MWh/day")
        print(f"  Min Daily Energy: {march_forecast.min_energy_mwh:.2f} MWh/day")
        print(f"  Max Daily Energy: {march_forecast.max_energy_mwh:.2f} MWh/day")
        
        print(f"\nMETHOD 2: Average Monthly Discharge × 24 hours × days")
        if avg_discharge_result.get('total_monthly_energy_mwh'):
            print(f"  Average Monthly Discharge: {avg_discharge_result['average_monthly_discharge_m3s']:.2f} m³/s")
            print(f"  Discharge Used (capped): {avg_discharge_result['discharge_used_for_energy']:.2f} m³/s")
            print(f"  Monthly Power: {avg_discharge_result['monthly_power_mw']:.2f} MW")
            print(f"  Daily Energy: {avg_discharge_result['daily_energy_mwh']:.2f} MWh/day")
            print(f"  Total Monthly Energy: {avg_discharge_result['total_monthly_energy_mwh']:.2f} MWh")
            print(f"  Days in Month: {avg_discharge_result['days_in_month']}")
        else:
            print(f"  Error: {avg_discharge_result.get('error')}")
        
        # Compare both methods
        comparison = march_forecast.compare_energy_calculation_methods()
        
        print(f"\nCOMPARISON RESULTS:")
        print(f"  Method 1 Total: {comparison['method1_daily_sum']['total_monthly_energy_mwh']:.2f} MWh")
        print(f"  Method 2 Total: {comparison['method2_avg_discharge']['total_monthly_energy_mwh']:.2f} MWh")
        
        if comparison['comparison']['both_methods_available']:
            print(f"  Difference: {comparison['comparison']['difference_mwh']:.2f} MWh")
            print(f"  Percentage Diff: {comparison['comparison']['percentage_difference']:.1f}%")
            print(f"  Similar Results: {'✓ Yes' if comparison['comparison']['similar_results'] else '✗ No'}")
        
        print(f"\n" + "="*60)
        print(f"INTERPRETATION:")
        print(f"="*60)
        print(f"Method 1 (Daily Sum): Sums individual daily energy calculations")
        print(f"  - Accounts for daily discharge variations")
        print(f"  - More granular and potentially more accurate")
        
        print(f"\nMethod 2 (Monthly Average): Uses average discharge for entire month")
        print(f"  - Simpler calculation, good for planning")
        print(f"  - Smooths out daily variations")
        print(f"  - Your requested approach!")
        
        if comparison['comparison']['both_methods_available']:
            diff_pct = comparison['comparison']['percentage_difference']
            if diff_pct < 1:
                print(f"\n✓ Both methods give very similar results ({diff_pct:.1f}% difference)")
            elif diff_pct < 5:
                print(f"\n✓ Both methods give reasonably similar results ({diff_pct:.1f}% difference)")
            else:
                print(f"\n⚠ Methods show significant difference ({diff_pct:.1f}%) - investigate data")
    
    else:
        print(f"No March 2024 forecast found")

if __name__ == "__main__":
    test_both_energy_calculation_methods()