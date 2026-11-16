#!/usr/bin/env python3
"""
Update Station Model Configuration
Points station to your actual trained model files
"""

import os
import sys
import django
from pathlib import Path

# Setup Django
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import DischargeStation

def update_station_model_paths():
    """Update station configuration with actual model paths"""
    
    print("🔧 Updating Station Model Configuration")
    print("=" * 45)
    
    # Your actual model file paths (relative to project root)
    model_file_path = "models/pytorch/lower_lekhu.pt"
    scaler_file_path = "models/scalers/Scaler_file.pkl"
    
    # Check if files exist
    if not os.path.exists(model_file_path):
        print(f"❌ Model file not found: {model_file_path}")
        return False
        
    if not os.path.exists(scaler_file_path):
        print(f"❌ Scaler file not found: {scaler_file_path}")
        return False
    
    print(f"✅ Model file found: {model_file_path}")
    print(f"✅ Scaler file found: {scaler_file_path}")
    
    # Update all stations (you can specify specific stations if needed)
    stations = DischargeStation.objects.all()
    
    updated_count = 0
    for station in stations:
        try:
            # Update model configuration
            station.model_file_path = model_file_path
            station.scaler_file_path = scaler_file_path
            station.model_description = "Trained PyTorch LSTM model for discharge prediction using 90-day ERA5 sequences"
            station.is_model_ready = True
            station.save()
            
            print(f"✅ Updated {station.station_id}: {station.name}")
            updated_count += 1
            
        except Exception as e:
            print(f"❌ Failed to update {station.station_id}: {e}")
    
    print(f"\n🎉 Updated {updated_count} stations with model configuration")
    return True

def verify_station_configuration():
    """Verify that stations are properly configured"""
    
    print("\n🔍 Verifying Station Configuration")
    print("=" * 35)
    
    stations = DischargeStation.objects.all()
    
    for station in stations:
        print(f"\n📍 {station.station_id}: {station.name}")
        print(f"   Model file: {station.model_file_path}")
        print(f"   Scaler file: {station.scaler_file_path}")
        print(f"   Model ready: {station.is_model_ready}")
        print(f"   Has trained model: {station.has_trained_model}")
        
        if station.coordinates:
            print(f"   Coordinates: {station.coordinates}")
        
        # Check ERA5 data availability
        era5_count = station.get_era5_data_count()
        print(f"   ERA5 data points: {era5_count}")

if __name__ == "__main__":
    print("🚀 Station Model Configuration Update")
    print("=" * 40)
    
    if update_station_model_paths():
        verify_station_configuration()
        
        print(f"\n✅ Configuration complete!")
        print(f"   Your stations are now ready for real-time predictions")
        print(f"   Run: python real_time_discharge_prediction.py")
    else:
        print(f"\n❌ Configuration failed!")
        print(f"   Please check that your model files exist")
