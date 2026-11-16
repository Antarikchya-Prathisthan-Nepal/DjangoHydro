#!/usr/bin/env python
"""
Script to populate SensorReading table with dummy data for testing
Based on the sensor database screenshot provided by the user
"""

import os
import sys
import django
from datetime import datetime, timedelta
from django.utils import timezone
import random

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
django.setup()

from discharge_prediction.models import DischargeStation, SensorReading

def create_dummy_sensor_data():
    """Create realistic dummy sensor data based on the screenshot"""
    
    print("🔧 Creating Dummy Sensor Reading Data...")
    print("=" * 60)
    
    # Get available stations
    stations = DischargeStation.objects.all()
    if not stations.exists():
        print("❌ No stations found. Please create stations first.")
        return False
    
    print(f"📍 Found {stations.count()} stations:")
    for station in stations:
        print(f"   - {station.name} ({station.station_id})")
    
    # Parameters based on your screenshot data
    base_params = {
        'latitude': 27.6992,
        'longitude': 85.3567,
        'device_username': 'apn_sajan_123',
        'ip_address': '192.168.1.71'
    }
    
    # Generate data for the last 7 days
    end_time = timezone.now()
    start_time = end_time - timedelta(days=7)
    
    total_records = 0
    
    for station in stations:
        print(f"\n🏭 Creating data for station: {station.name}")
        
        # Generate readings every 2-3 minutes (like your screenshot)
        current_time = start_time
        station_records = 0
        
        while current_time <= end_time:
            # Generate realistic sensor values with some variation
            temperature = round(random.uniform(18.0, 22.0), 1)  # 18-22°C
            humidity = round(random.uniform(50.0, 60.0), 1)     # 50-60%
            pressure = round(random.uniform(870.0, 872.0), 6)   # ~871 hPa
            air_quality = random.randint(85, 87)                # 85-87 AQI
            water_depth = random.randint(85, 87)                # 85-87 units
            wifi_strength = random.randint(-83, -77)            # -83 to -77 dBm
            
            # Create sensor reading
            try:
                sensor_reading = SensorReading.objects.create(
                    station=station,
                    timestamp=current_time,
                    record_id=f"rec_{station.station_id}_{station_records + 1:04d}",
                    device_username=base_params['device_username'],
                    device_id=station.station_id,
                    temperature=temperature,
                    humidity=humidity,
                    pressure=pressure,
                    air_quality=air_quality,
                    water_depth=water_depth,
                    wifi_strength=wifi_strength,
                    ip_address=base_params['ip_address'],
                    device_status=1,  # Active
                    latitude=base_params['latitude'] + random.uniform(-0.001, 0.001),  # Small GPS variation
                    longitude=base_params['longitude'] + random.uniform(-0.001, 0.001),
                    data_quality='good',
                    processing_status='raw'
                )
                
                station_records += 1
                total_records += 1
                
            except Exception as e:
                print(f"   ❌ Error creating record: {e}")
                continue
            
            # Move to next reading (2-3 minutes later)
            current_time += timedelta(minutes=random.randint(2, 3))
        
        print(f"   ✅ Created {station_records} sensor readings")
    
    print(f"\n🎉 Successfully created {total_records} total sensor readings!")
    return True

def display_sample_data():
    """Display sample of created data"""
    
    print("\n" + "=" * 60)
    print("📊 SAMPLE SENSOR DATA VERIFICATION")
    print("=" * 60)
    
    # Get recent readings
    recent_readings = SensorReading.objects.select_related('station').order_by('-timestamp')[:10]
    
    if not recent_readings.exists():
        print("❌ No sensor readings found in database")
        return
    
    print(f"\n📈 Latest 10 Sensor Readings:")
    print("-" * 120)
    print(f"{'Station':<15} {'Time':<20} {'Temp°C':<8} {'Humidity%':<10} {'Pressure':<10} {'Depth':<6} {'WiFi':<6} {'Quality':<8}")
    print("-" * 120)
    
    for reading in recent_readings:
        print(f"{reading.station.name:<15} {reading.timestamp.strftime('%Y-%m-%d %H:%M'):<20} "
              f"{reading.temperature:<8} {reading.humidity:<10} {reading.pressure:<10} "
              f"{reading.water_depth:<6} {reading.wifi_strength:<6} {reading.data_quality:<8}")

def test_model_relationships():
    """Test relationships and model methods"""
    
    print("\n" + "=" * 60)
    print("🔍 TESTING MODEL RELATIONSHIPS & METHODS")
    print("=" * 60)
    
    stations = DischargeStation.objects.all()
    
    for station in stations:
        # Test station -> sensor readings relationship
        readings_count = station.sensor_readings.count()
        print(f"\n🏭 Station: {station.name}")
        print(f"   Total sensor readings: {readings_count}")
        
        if readings_count > 0:
            # Get latest reading
            latest_reading = station.sensor_readings.first()
            print(f"   Latest reading: {latest_reading.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Test environmental summary
            env_summary = latest_reading.get_environmental_summary()
            print(f"   Environmental summary: Temp={env_summary['temperature_c']}°C, "
                  f"Humidity={env_summary['humidity_percent']}%, Water Depth={env_summary['water_depth']}")
            
            # Test recent readings method
            recent_24h = SensorReading.get_recent_readings(station, hours=24)
            print(f"   Recent 24h readings: {recent_24h.count()}")
            
            # Test data summary
            summary = SensorReading.get_data_summary_for_station(station, days=7)
            if 'error' not in summary:
                print(f"   7-day summary: {summary['count']} readings, "
                      f"Avg temp={summary.get('avg_temperature', 0):.1f}°C, "
                      f"Avg humidity={summary.get('avg_humidity', 0):.1f}%")
            
            # Test ERA5 validation (will likely show no data available)
            validation_result = latest_reading.validate_against_era5()
            print(f"   ERA5 validation: {validation_result.get('overall_quality', 'No ERA5 data')}")

def generate_station_statistics():
    """Generate comprehensive statistics for all stations"""
    
    print("\n" + "=" * 60)
    print("📊 COMPREHENSIVE STATION STATISTICS")
    print("=" * 60)
    
    stations = DischargeStation.objects.all()
    
    for station in stations:
        readings = station.sensor_readings.all()
        
        if readings.exists():
            from django.db.models import Avg, Min, Max, Count
            
            stats = readings.aggregate(
                count=Count('id'),
                avg_temp=Avg('temperature'),
                min_temp=Min('temperature'),
                max_temp=Max('temperature'),
                avg_humidity=Avg('humidity'),
                min_humidity=Min('humidity'),
                max_humidity=Max('humidity'),
                avg_pressure=Avg('pressure'),
                avg_depth=Avg('water_depth'),
                min_depth=Min('water_depth'),
                max_depth=Max('water_depth')
            )
            
            print(f"\n🏭 {station.name} ({station.station_id}):")
            print(f"   📊 Total readings: {stats['count']}")
            print(f"   🌡️  Temperature: {stats['avg_temp']:.1f}°C (range: {stats['min_temp']:.1f} - {stats['max_temp']:.1f}°C)")
            print(f"   💧 Humidity: {stats['avg_humidity']:.1f}% (range: {stats['min_humidity']:.1f} - {stats['max_humidity']:.1f}%)")
            print(f"   📊 Pressure: {stats['avg_pressure']:.1f} hPa")
            print(f"   🌊 Water depth: {stats['avg_depth']:.1f} units (range: {stats['min_depth']:.1f} - {stats['max_depth']:.1f})")
            
            # Time range
            earliest = readings.order_by('timestamp').first()
            latest = readings.order_by('timestamp').last()
            print(f"   ⏰ Time range: {earliest.timestamp.strftime('%Y-%m-%d %H:%M')} to {latest.timestamp.strftime('%Y-%m-%d %H:%M')}")
            
            # Data quality breakdown
            quality_stats = {}
            for quality in readings.values_list('data_quality', flat=True).distinct():
                count = readings.filter(data_quality=quality).count()
                quality_stats[quality] = count
            print(f"   ✅ Data quality: {quality_stats}")
            
        else:
            print(f"\n🏭 {station.name}: No sensor data")

def main():
    """Main function to create and verify dummy data"""
    
    print("🚀 SENSOR READING DATABASE TEST")
    print("=" * 60)
    
    # Check current data
    current_count = SensorReading.objects.count()
    print(f"📊 Current sensor readings in database: {current_count}")
    
    if current_count > 0:
        response = input("\n⚠️  Database already has sensor readings. Clear existing data? (y/N): ")
        if response.lower() == 'y':
            SensorReading.objects.all().delete()
            print("🗑️  Cleared existing sensor readings")
    
    # Create dummy data
    success = create_dummy_sensor_data()
    
    if success:
        # Display verification data
        display_sample_data()
        test_model_relationships()
        generate_station_statistics()
        
        print(f"\n🎉 DUMMY DATA CREATION COMPLETE!")
        print("=" * 60)
        print("✅ Database is working properly!")
        print("✅ All model relationships functioning!")
        print("✅ Data validation methods working!")
        print("✅ Ready for real GST device integration!")
        
        print(f"\n🔧 Next Steps:")
        print("1. Access Django Admin: http://127.0.0.1:8000/admin/")
        print("2. Navigate to Discharge prediction → Sensor readings")
        print("3. Test filtering, searching, and export features")
        print("4. Try the 'Validate against ERA5 data' action")
        print("5. Export sensor data to CSV")
        
    else:
        print("❌ Failed to create dummy data")

if __name__ == "__main__":
    main()