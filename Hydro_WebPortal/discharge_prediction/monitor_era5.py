#!/usr/bin/env python3
"""
Monitor ERA5 download progress and database status
"""

import os
import sys
import django
from datetime import datetime, timedelta

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation, ERA5Data

def monitor_era5_progress(station_name="Lower likhu"):
    """Monitor ERA5 data download progress"""
    try:
        # Get station
        station = DischargeStation.objects.get(name__icontains=station_name)
        
        # Get latest records
        recent_records = ERA5Data.objects.filter(
            station=station
        ).order_by('-date')[:10]
        
        print(f"📊 ERA5 Data Status for {station.name}")
        print("=" * 60)
        
        total_records = ERA5Data.objects.filter(station=station).count()
        complete_records = ERA5Data.objects.filter(station=station, is_complete=True).count()
        
        print(f"📈 Total Records: {total_records}")
        print(f"✅ Complete Records: {complete_records}")
        print(f"⚠️ Incomplete Records: {total_records - complete_records}")
        print()
        
        print("📅 Recent Records:")
        print("-" * 60)
        for record in recent_records:
            status_icon = "✅" if record.is_complete else "⚠️"
            print(f"{status_icon} {record.date} | T:{record.temperature_2m:.1f}°C | "
                  f"P:{record.total_precipitation:.2f}mm | "
                  f"H:{record.specific_humidity:.6f} | "
                  f"Status: {record.processing_status}")
        
        print()
        
        # Check for recent downloads
        recent_downloads = ERA5Data.objects.filter(
            station=station,
            download_timestamp__gte=datetime.now() - timedelta(hours=2)
        ).order_by('-download_timestamp')
        
        if recent_downloads.exists():
            print("🔄 Recent Downloads (last 2 hours):")
            print("-" * 60)
            for record in recent_downloads:
                print(f"📥 {record.date} | Downloaded: {record.download_timestamp.strftime('%H:%M:%S')} | "
                      f"Complete: {record.is_complete}")
        else:
            print("⏱️ No recent downloads in the last 2 hours")
        
        return True
        
    except DischargeStation.DoesNotExist:
        print(f"❌ Station '{station_name}' not found")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False

if __name__ == "__main__":
    monitor_era5_progress()
