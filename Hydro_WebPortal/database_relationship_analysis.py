#!/usr/bin/env python
"""
Comprehensive review of all database tables and their relationships
in the Django Hydro Portal system
"""
import os
import sys
import django
from datetime import date, datetime

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from django.db import models
from discharge_prediction.models import (
    DischargeStation, DischargePrediction, MonthlyForecast, 
    ERA5Data, DischargeRecord, ForecastSequence, 
    PredictionModel, PipelineRun
)

def analyze_discharge_stations():
    """Analyze DischargeStation table - The central hub"""
    
    print("=" * 80)
    print("1. DISCHARGE STATIONS (Central Hub)")
    print("=" * 80)
    
    stations = DischargeStation.objects.all()
    print(f"📍 Total Stations: {stations.count()}")
    
    for i, station in enumerate(stations, 1):
        print(f"\n🏭 Station {i}: {station.name}")
        print(f"   ID: {station.station_id}")
        print(f"   Location: {station.latitude}°N, {station.longitude}°E")
        print(f"   Active: {station.is_active}")
        print(f"   Model Ready: {station.is_model_ready}")
        
        # Hydropower parameters
        print(f"   ⚡ Hydropower Parameters:")
        print(f"      Net Head: {station.net_head} m")
        print(f"      Efficiency: {station.efficiency}")
        print(f"      Max Discharge: {station.max_discharge_for_energy} m³/s")
        
        # Related data counts
        predictions_count = station.predictions.count()
        era5_count = station.era5_data.count()
        records_count = station.discharge_records.count()
        monthly_forecasts_count = MonthlyForecast.objects.filter(station=station).count()
        
        print(f"   📊 Related Data:")
        print(f"      Daily Predictions: {predictions_count}")
        print(f"      ERA5 Records: {era5_count}")
        print(f"      Historical Records: {records_count}")
        print(f"      Monthly Forecasts: {monthly_forecasts_count}")

def analyze_era5_data():
    """Analyze ERA5Data table - Weather input data"""
    
    print("\n" + "=" * 80)
    print("2. ERA5 DATA (Weather Input)")
    print("=" * 80)
    
    total_era5 = ERA5Data.objects.count()
    complete_era5 = ERA5Data.objects.filter(is_complete=True).count()
    
    print(f"🌤️  Total ERA5 Records: {total_era5}")
    print(f"✅ Complete Records: {complete_era5}")
    print(f"📈 Completion Rate: {(complete_era5/total_era5)*100:.1f}%" if total_era5 > 0 else "No data")
    
    # Check by station
    stations = DischargeStation.objects.all()
    for station in stations:
        station_era5 = station.era5_data.count()
        station_complete = station.era5_data.filter(is_complete=True).count()
        
        if station_era5 > 0:
            latest_era5 = station.era5_data.first()
            oldest_era5 = station.era5_data.last()
            
            print(f"\n📍 {station.name}:")
            print(f"   Total ERA5 records: {station_era5}")
            print(f"   Complete records: {station_complete}")
            print(f"   Date range: {oldest_era5.date} to {latest_era5.date}")
            
            # Show sample data structure
            if latest_era5:
                print(f"   📝 Latest ERA5 Features:")
                print(f"      Temperature: {latest_era5.temperature_2m}°C")
                print(f"      Precipitation: {latest_era5.total_precipitation} mm")
                print(f"      U-Wind: {latest_era5.u_component_10m} m/s")
                print(f"      V-Wind: {latest_era5.v_component_10m} m/s")
                print(f"      Humidity: {latest_era5.specific_humidity} kg/kg")

def analyze_discharge_predictions():
    """Analyze DischargePrediction table - Daily predictions"""
    
    print("\n" + "=" * 80)
    print("3. DISCHARGE PREDICTIONS (Daily Predictions)")
    print("=" * 80)
    
    total_predictions = DischargePrediction.objects.count()
    completed_predictions = DischargePrediction.objects.filter(processing_status='completed').count()
    
    print(f"🔮 Total Predictions: {total_predictions}")
    print(f"✅ Completed Predictions: {completed_predictions}")
    
    # Check by station
    stations = DischargeStation.objects.all()
    for station in stations:
        station_predictions = station.predictions.count()
        
        if station_predictions > 0:
            latest_pred = station.predictions.first()
            oldest_pred = station.predictions.last()
            
            # Check date range
            print(f"\n📍 {station.name}:")
            print(f"   Total predictions: {station_predictions}")
            print(f"   Date range: {oldest_pred.target_date} to {latest_pred.target_date}")
            
            # Check energy calculations
            with_energy = station.predictions.exclude(predicted_energy__isnull=True).count()
            print(f"   With energy calculations: {with_energy}/{station_predictions}")
            
            # Show sample prediction
            if latest_pred:
                print(f"   📝 Latest Prediction:")
                print(f"      Date: {latest_pred.target_date}")
                print(f"      Discharge: {latest_pred.predicted_discharge:.2f} m³/s")
                print(f"      Energy: {latest_pred.predicted_energy or 'None'} MWh")
                print(f"      Model: {latest_pred.model_name}")
                print(f"      Status: {latest_pred.processing_status}")

def analyze_monthly_forecasts():
    """Analyze MonthlyForecast table - Monthly aggregations"""
    
    print("\n" + "=" * 80)
    print("4. MONTHLY FORECASTS (Monthly Aggregations)")
    print("=" * 80)
    
    total_monthly = MonthlyForecast.objects.count()
    completed_monthly = MonthlyForecast.objects.filter(processing_status='completed').count()
    
    print(f"📅 Total Monthly Forecasts: {total_monthly}")
    print(f"✅ Completed Monthly Forecasts: {completed_monthly}")
    
    # Show all monthly forecasts
    monthly_forecasts = MonthlyForecast.objects.all().order_by('-target_year', '-target_month')
    
    for forecast in monthly_forecasts:
        month_name = date(forecast.target_year, forecast.target_month, 1).strftime('%B')
        status_icon = "✅" if forecast.processing_status == 'completed' else "❌"
        
        print(f"\n{status_icon} {forecast.station.name} - {month_name} {forecast.target_year}")
        print(f"   Status: {forecast.processing_status}")
        print(f"   Daily forecasts: {forecast.total_daily_forecasts}")
        
        if forecast.processing_status == 'completed':
            print(f"   Mean discharge: {forecast.mean_discharge:.2f} m³/s")
            print(f"   Total energy: {forecast.total_energy_mwh:.2f} MWh")
            print(f"   Daily energy: {forecast.mean_energy_mwh:.2f} MWh/day")
        
        print(f"   Created: {forecast.created_at.strftime('%Y-%m-%d %H:%M')}")

def analyze_relationships():
    """Analyze the relationships between all tables"""
    
    print("\n" + "=" * 80)
    print("5. TABLE RELATIONSHIPS & DATA FLOW")
    print("=" * 80)
    
    print("🔗 Database Relationship Structure:")
    print("""
    DischargeStation (Central Hub)
    │
    ├── ERA5Data (1:Many)
    │   └── Weather input for predictions
    │
    ├── DischargePrediction (1:Many)
    │   ├── Daily discharge predictions
    │   └── Daily energy calculations
    │
    ├── MonthlyForecast (1:Many)
    │   ├── Aggregates DischargePrediction
    │   └── Monthly energy statistics
    │
    ├── DischargeRecord (1:Many)
    │   └── Historical observations
    │
    ├── ForecastSequence (1:Many)
    │   └── Manages prediction sequences
    │
    └── PipelineRun (1:Many)
        └── Tracks processing jobs
    """)
    
    print("\n⚡ Energy Calculation Flow:")
    print("""
    1. ERA5Data → Features for model input
    2. DischargePrediction → Daily discharge + energy
    3. MonthlyForecast → Aggregates using average discharge method
       Formula: Power = η × ρ × g × Q_avg × H / 10^6
                Energy = Power × 24 hours × days_in_month
    """)

def check_data_consistency():
    """Check data consistency across tables"""
    
    print("\n" + "=" * 80)
    print("6. DATA CONSISTENCY CHECK")
    print("=" * 80)
    
    stations = DischargeStation.objects.all()
    
    for station in stations:
        print(f"\n🔍 {station.name} Data Consistency:")
        
        # Check prediction coverage
        predictions = station.predictions.all()
        if predictions:
            date_range = predictions.aggregate(
                min_date=models.Min('target_date'),
                max_date=models.Max('target_date')
            )
            print(f"   Prediction range: {date_range['min_date']} to {date_range['max_date']}")
        
        # Check ERA5 coverage
        era5_data = station.era5_data.filter(is_complete=True)
        if era5_data:
            era5_range = era5_data.aggregate(
                min_date=models.Min('date'),
                max_date=models.Max('date')
            )
            print(f"   ERA5 range: {era5_range['min_date']} to {era5_range['max_date']}")
        
        # Check for data gaps
        monthly_forecasts = MonthlyForecast.objects.filter(station=station)
        completed_months = monthly_forecasts.filter(processing_status='completed').count()
        failed_months = monthly_forecasts.filter(processing_status='failed').count()
        
        print(f"   Monthly forecasts: {completed_months} completed, {failed_months} failed")

def summary_report():
    """Generate summary report"""
    
    print("\n" + "=" * 80)
    print("7. SYSTEM SUMMARY REPORT")
    print("=" * 80)
    
    # Overall statistics
    stations_count = DischargeStation.objects.count()
    predictions_count = DischargePrediction.objects.count()
    era5_count = ERA5Data.objects.filter(is_complete=True).count()
    monthly_count = MonthlyForecast.objects.filter(processing_status='completed').count()
    
    print(f"📊 System Overview:")
    print(f"   Monitoring Stations: {stations_count}")
    print(f"   Daily Predictions: {predictions_count}")
    print(f"   ERA5 Weather Records: {era5_count}")
    print(f"   Completed Monthly Forecasts: {monthly_count}")
    
    print(f"\n⚡ Energy Calculation Status:")
    predictions_with_energy = DischargePrediction.objects.exclude(predicted_energy__isnull=True).count()
    energy_coverage = (predictions_with_energy / predictions_count * 100) if predictions_count > 0 else 0
    print(f"   Daily predictions with energy: {predictions_with_energy}/{predictions_count} ({energy_coverage:.1f}%)")
    
    monthly_with_energy = MonthlyForecast.objects.exclude(total_energy_mwh__isnull=True).count()
    print(f"   Monthly forecasts with energy: {monthly_with_energy}")
    
    print(f"\n🎯 Data Quality:")
    # Check for recent data
    from datetime import timedelta
    recent_threshold = datetime.now().date() - timedelta(days=7)
    recent_predictions = DischargePrediction.objects.filter(target_date__gte=recent_threshold).count()
    print(f"   Recent predictions (last 7 days): {recent_predictions}")
    
    # Check for duplicates or issues
    total_monthly = MonthlyForecast.objects.count()
    failed_monthly = MonthlyForecast.objects.filter(processing_status='failed').count()
    print(f"   Failed monthly forecasts: {failed_monthly}/{total_monthly}")

if __name__ == "__main__":
    print("🔍 DJANGO HYDRO PORTAL - DATABASE RELATIONSHIP ANALYSIS")
    print("This comprehensive review shows all tables and their connections")
    print("")
    
    try:
        analyze_discharge_stations()
        analyze_era5_data()
        analyze_discharge_predictions()
        analyze_monthly_forecasts()
        analyze_relationships()
        check_data_consistency()
        summary_report()
        
        print("\n" + "=" * 80)
        print("✅ DATABASE ANALYSIS COMPLETED")
        print("Your system has a well-structured relational database with clear data flow")
        print("from weather inputs (ERA5) through daily predictions to monthly energy forecasts.")
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()