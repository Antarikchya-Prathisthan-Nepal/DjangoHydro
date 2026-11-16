#!/usr/bin/env python
"""
Test script to verify SensorReading model functionality
Run this script to test the new SensorReading model integration
"""

import os
import sys
import django
from datetime import datetime, timedelta
from django.utils import timezone

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
django.setup()

from discharge_prediction.models import DischargeStation, SensorReading

def test_sensor_reading_model():
    """Test the SensorReading model functionality"""
    
    print("🔧 Testing SensorReading Model...")
    print("=" * 50)
    
    # 1. Get an existing station
    try:
        station = DischargeStation.objects.first()
        if not station:
            print("❌ No discharge stations found. Please create a station first.")
            return False
        
        print(f"✅ Using station: {station.name} ({station.station_id})")
        
    except Exception as e:
        print(f"❌ Error getting station: {e}")
        return False
    
    # 2. Create a test sensor reading (simulating your database data)
    try:
        test_reading = SensorReading.objects.create(
            station=station,
            timestamp=timezone.now(),
            record_id="test_001",
            device_username="apn_sajan_123",
            device_id="1",
            temperature=20.6,  # Based on your screenshot data
            humidity=54.3,
            pressure=871.0,
            air_quality=86,
            water_depth=85.0,
            wifi_strength=-78,
            device_status=1,
            latitude=27.6992,  # From your screenshot
            longitude=85.3567,
            data_quality='good',
            processing_status='raw'
        )
        
        print(f"✅ Created test sensor reading: ID {test_reading.id}")
        print(f"   📍 Location: {test_reading.coordinates}")
        print(f"   🌡️ Temperature: {test_reading.temperature}°C")
        print(f"   💧 Humidity: {test_reading.humidity}%")
        print(f"   📊 Water Depth: {test_reading.water_depth}")
        
    except Exception as e:
        print(f"❌ Error creating sensor reading: {e}")
        return False
    
    # 3. Test model methods
    try:
        # Test environmental summary
        env_summary = test_reading.get_environmental_summary()
        print(f"\n📋 Environmental Summary:")
        for key, value in env_summary.items():
            print(f"   {key}: {value}")
        
        # Test ERA5 validation (if ERA5 data exists)
        validation_results = test_reading.validate_against_era5()
        print(f"\n🔍 ERA5 Validation Results:")
        print(f"   Overall Quality: {validation_results.get('overall_quality', 'N/A')}")
        if 'error' in validation_results:
            print(f"   Note: {validation_results['error']}")
        
        # Test discharge correlation
        correlation = test_reading.calculate_discharge_correlation()
        print(f"\n⚡ Discharge Correlation:")
        if correlation and correlation.get('correlation_possible'):
            print(f"   Predicted Discharge: {correlation.get('predicted_discharge', 'N/A')} m³/s")
            print(f"   Sensor Depth: {correlation.get('sensor_depth', 'N/A')}")
        else:
            print("   No discharge prediction data available for correlation")
        
    except Exception as e:
        print(f"❌ Error testing model methods: {e}")
        return False
    
    # 4. Test relationship with DischargeStation
    try:
        # Get sensor readings for this station
        station_readings = station.sensor_readings.all()
        print(f"\n🔗 Station Relationship Test:")
        print(f"   Station: {station.name}")
        print(f"   Total sensor readings: {station_readings.count()}")
        print(f"   Latest reading: {station_readings.first()}")
        
    except Exception as e:
        print(f"❌ Error testing station relationship: {e}")
        return False
    
    # 5. Test class methods
    try:
        # Test recent readings
        recent_readings = SensorReading.get_recent_readings(station, hours=24)
        print(f"\n⏰ Recent Readings (24h): {recent_readings.count()}")
        
        # Test data summary
        summary = SensorReading.get_data_summary_for_station(station, days=7)
        print(f"\n📊 7-day Data Summary:")
        if 'error' not in summary:
            print(f"   Count: {summary.get('count', 0)} readings")
            print(f"   Avg Temperature: {summary.get('avg_temperature', 'N/A')}°C")
            print(f"   Avg Humidity: {summary.get('avg_humidity', 'N/A')}%")
            print(f"   Latest: {summary.get('latest_reading', 'N/A')}")
        else:
            print(f"   {summary['error']}")
            
    except Exception as e:
        print(f"❌ Error testing class methods: {e}")
        return False
    
    # 6. Clean up test data
    try:
        test_reading.delete()
        print(f"\n🧹 Cleaned up test data")
        
    except Exception as e:
        print(f"⚠️ Warning: Could not clean up test data: {e}")
    
    print(f"\n✅ SensorReading model test completed successfully!")
    print(f"🎉 The model is ready for production use!")
    
    return True

def display_integration_info():
    """Display information about integrating with existing sensor data"""
    
    print("\n" + "=" * 60)
    print("📡 SENSOR DATA INTEGRATION GUIDE")
    print("=" * 60)
    
    print("""
🔄 NEXT STEPS TO IMPORT YOUR SENSOR DATA:

1. 📥 Data Import Options:
   
   A) CSV Import (Recommended):
   ```python
   # Create a management command to import your CSV data
   python manage.py import_sensor_data --file sensor_data.csv --station lower_likhu
   ```
   
   B) Direct Database Connection:
   ```python
   # Connect to your sensor database and migrate data
   # Use Django ORM to bulk_create SensorReading objects
   ```
   
   C) API Integration:
   ```python
   # Create API endpoint to receive real-time sensor data
   # POST /api/sensor-readings/ with JSON payload
   ```

2. 📋 Data Mapping (based on your screenshot):
   
   Your Database Fields → Django SensorReading Fields:
   - Username → device_username
   - ID → device_id  
   - Latitude → latitude
   - Longitude → longitude
   - Date/Time → timestamp
   - WiFi_Strength → wifi_strength
   - IP_Address → ip_address
   - Temperature → temperature
   - Pressure → pressure
   - Humidity → humidity
   - Depth → water_depth
   - Air_Quality → air_quality

3. 🔧 Admin Interface:
   
   Access Django Admin at: http://127.0.0.1:8000/admin/
   - View/edit sensor readings
   - Export data to CSV
   - Validate against ERA5 data
   - Monitor data quality

4. 🔄 Automated Processing:
   
   - Real-time validation against ERA5 weather data
   - Correlation with discharge predictions
   - Data quality assessment
   - Anomaly detection

5. 📊 Integration with Existing System:
   
   - Sensor data validates your ML predictions
   - Improves model accuracy over time
   - Provides real-time operational monitoring
   - Enables hybrid forecasting (ML + sensors)
""")

if __name__ == "__main__":
    success = test_sensor_reading_model()
    
    if success:
        display_integration_info()
    else:
        print("❌ Model test failed. Please check the errors above.")
        sys.exit(1)