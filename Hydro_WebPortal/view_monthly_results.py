#!/usr/bin/env python3
"""
Monthly Forecast Results Viewer
===============================

This script displays the monthly forecast results in a formatted table.

Usage:
    python view_monthly_results.py
"""

import os
import sys
import django
from datetime import date

# Add the project root to Python path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, MonthlyForecast

def display_monthly_forecasts():
    """Display all monthly forecasts in a formatted table"""
    
    print("=" * 100)
    print("🌊 MONTHLY ENERGY FORECAST RESULTS")
    print("=" * 100)
    
    # Get all completed monthly forecasts
    forecasts = MonthlyForecast.objects.filter(
        processing_status='completed'
    ).order_by('station__name', 'target_year', 'target_month')
    
    if not forecasts.exists():
        print("❌ No completed monthly forecasts found")
        return
    
    print(f"📊 Found {forecasts.count()} completed monthly forecasts")
    print()
    
    # Group by station
    current_station = None
    
    for forecast in forecasts:
        if current_station != forecast.station.name:
            if current_station is not None:
                print()  # Add space between stations
            
            current_station = forecast.station.name
            print(f"🏭 STATION: {forecast.station.name}")
            print("-" * 80)
            print(f"{'Month':<15} {'Avg Discharge':<15} {'Daily Energy':<15} {'Monthly Energy':<15} {'Days'}")
            print(f"{'(YYYY-MM)':<15} {'(m³/s)':<15} {'(MWh/day)':<15} {'(MWh)':<15} {'Count'}")
            print("-" * 80)
        
        # Format month name
        month_name = date(forecast.target_year, forecast.target_month, 1).strftime('%Y-%m (%b)')
        
        # Display forecast data
        avg_discharge = forecast.mean_discharge or 0
        daily_energy = forecast.mean_energy_mwh or 0
        monthly_energy = forecast.total_energy_mwh or 0
        days_count = forecast.total_daily_forecasts
        
        print(f"{month_name:<15} {avg_discharge:>11.2f}     {daily_energy:>11.2f}     {monthly_energy:>11.2f}     {days_count:>3}")
    
    print()
    print("=" * 100)
    
    # Summary statistics
    total_energy = sum(f.total_energy_mwh for f in forecasts if f.total_energy_mwh)
    avg_monthly_energy = total_energy / forecasts.count() if forecasts.count() > 0 else 0
    
    print("📊 SUMMARY STATISTICS")
    print("-" * 50)
    print(f"Total forecasts: {forecasts.count()}")
    print(f"Total energy forecasted: {total_energy:,.2f} MWh")
    print(f"Average monthly energy: {avg_monthly_energy:,.2f} MWh")
    
    # Station breakdown
    stations = DischargeStation.objects.filter(is_active=True)
    print(f"\n🏭 STATION BREAKDOWN")
    print("-" * 50)
    
    for station in stations:
        station_forecasts = forecasts.filter(station=station)
        station_total = sum(f.total_energy_mwh for f in station_forecasts if f.total_energy_mwh)
        station_avg = station_total / station_forecasts.count() if station_forecasts.count() > 0 else 0
        
        print(f"{station.name}:")
        print(f"  Months forecasted: {station_forecasts.count()}")
        print(f"  Total energy: {station_total:,.2f} MWh")
        print(f"  Avg monthly: {station_avg:,.2f} MWh")
        print(f"  Hydropower params: η={station.efficiency}, H={station.net_head}m, Qmax={station.max_discharge_for_energy}m³/s")
        print()

def show_calculation_details():
    """Show detailed calculation information for the latest forecast"""
    
    latest_forecast = MonthlyForecast.objects.filter(
        processing_status='completed'
    ).order_by('-target_year', '-target_month').first()
    
    if not latest_forecast:
        print("❌ No completed forecasts found for detailed view")
        return
    
    print("=" * 80)
    print("🔍 DETAILED CALCULATION EXAMPLE")
    print("=" * 80)
    
    summary = latest_forecast.get_monthly_energy_summary()
    
    print(f"Station: {summary['station_name']}")
    print(f"Month: {summary['month_name']} {summary['year']}")
    print(f"Calculation Method: {summary['calculation_method']}")
    print()
    
    print("📊 INPUT DATA:")
    print(f"  Average monthly discharge: {summary['average_monthly_discharge_m3s']:.2f} m³/s")
    print(f"  Station efficiency (η): {summary['hydropower_parameters']['efficiency']}")
    print(f"  Net head (H): {summary['hydropower_parameters']['net_head_m']} m")
    print(f"  Max discharge for energy: {summary['hydropower_parameters']['max_discharge_for_energy_m3s']} m³/s")
    print()
    
    # Manual calculation verification
    efficiency = summary['hydropower_parameters']['efficiency']
    net_head = summary['hydropower_parameters']['net_head_m']
    max_discharge = summary['hydropower_parameters']['max_discharge_for_energy_m3s']
    avg_discharge = summary['average_monthly_discharge_m3s']
    
    # Apply discharge cap
    discharge_for_energy = min(avg_discharge, max_discharge)
    
    # Calculate power: P = η × ρ × g × Q × H / 10^6
    power_mw = (efficiency * 1000 * 9.81 * discharge_for_energy * net_head) / 1e6
    daily_energy = power_mw * 24
    
    print("⚡ CALCULATION STEPS:")
    print(f"  1. Discharge used for energy: min({avg_discharge:.2f}, {max_discharge}) = {discharge_for_energy:.2f} m³/s")
    print(f"  2. Power = η × ρ × g × Q × H / 10^6")
    print(f"     Power = {efficiency} × 1000 × 9.81 × {discharge_for_energy:.2f} × {net_head} / 10^6")
    print(f"     Power = {power_mw:.2f} MW")
    print(f"  3. Daily Energy = Power × 24 hours = {power_mw:.2f} × 24 = {daily_energy:.2f} MWh/day")
    print()
    
    print("📊 RESULTS:")
    print(f"  Daily energy: {summary['daily_energy_from_avg_discharge_mwh']:.2f} MWh/day")
    print(f"  Monthly energy: {summary['total_monthly_energy_mwh']:.2f} MWh")
    print(f"  Daily forecasts used: {summary['total_daily_forecasts']}")

if __name__ == "__main__":
    display_monthly_forecasts()
    print()
    show_calculation_details()