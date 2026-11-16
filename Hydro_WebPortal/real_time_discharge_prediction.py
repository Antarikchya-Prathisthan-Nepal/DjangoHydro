#!/usr/bin/env python3
"""
Real-Time Discharge Prediction System
Integrates your trained PyTorch model with ERA5 data for live predictions
"""

import os
import sys
import django
import numpy as np
import pandas as pd
import torch
import joblib
from datetime import datetime, timedelta, date
import logging
from pathlib import Path

# Setup Django
sys.path.append(os.path.dirname(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import (
    DischargeStation, ERA5Data, ForecastSequence, 
    DischargePrediction, MonthlyForecast
)
from django.utils import timezone

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class RealTimeDischargePredictor:
    """
    Real-time discharge prediction using your trained PyTorch model
    """
    
    def __init__(self):
        # Your actual model paths
        self.model_path = "models/pytorch/lower_lekhu.pt"
        self.scaler_path = "models/scalers/Scaler_file.pkl"
        
        # Model configuration (adjust based on your training)
        self.sequence_length = 90  # 90-day input sequence
        self.n_features = 5       # ERA5 features: [t2m, u10, v10, tp, q]
        self.lead_time_days = 45  # 45-day lead time
        
        # Initialize components
        self.model = None
        self.scaler = None
        self.is_model_loaded = False
        
        # Feature names in exact training order
        self.feature_names = [
            'temperature_2m',      # t2m
            'u_component_10m',     # u10
            'v_component_10m',     # v10
            'total_precipitation', # tp
            'specific_humidity'    # q
        ]
        
    def load_trained_model(self):
        """Load your actual trained PyTorch model and scaler"""
        try:
            print("🔄 Loading trained model...")
            
            # Load PyTorch model
            if os.path.exists(self.model_path):
                print(f"📂 Loading model from: {self.model_path}")
                
                # Handle PyTorch loading with proper error handling
                try:
                    self.model = torch.load(
                        self.model_path, 
                        map_location='cpu',
                        weights_only=False  # Allow custom classes
                    )
                    print("✅ PyTorch model loaded successfully")
                except Exception as e:
                    print(f"⚠️  Loading with weights_only=False failed: {e}")
                    # Fallback for older PyTorch versions
                    self.model = torch.load(self.model_path, map_location='cpu')
                    print("✅ PyTorch model loaded (fallback method)")
                
                # Set model to evaluation mode
                if hasattr(self.model, 'eval'):
                    self.model.eval()
                    
            else:
                raise FileNotFoundError(f"Model file not found: {self.model_path}")
            
            # Load scaler
            if os.path.exists(self.scaler_path):
                print(f"📂 Loading scaler from: {self.scaler_path}")
                self.scaler = joblib.load(self.scaler_path)
                print("✅ Scaler loaded successfully")
            else:
                raise FileNotFoundError(f"Scaler file not found: {self.scaler_path}")
            
            # Validate model compatibility
            self._validate_model_setup()
            
            self.is_model_loaded = True
            print("🎉 Model and scaler loaded successfully!")
            return True
            
        except Exception as e:
            print(f"❌ Error loading model: {e}")
            logger.error(f"Model loading failed: {e}")
            return False
    
    def _validate_model_setup(self):
        """Validate that model and scaler work with expected input format"""
        try:
            print("🔍 Validating model setup...")
            
            # Create test input: (batch_size=1, sequence_length=90, n_features=5)
            test_input = np.random.random((1, self.sequence_length, self.n_features))
            print(f"   Test input shape: {test_input.shape}")
            
            # Test scaler
            scaled_input = self.scaler.transform(test_input)
            print(f"   Scaled input shape: {scaled_input.shape}")
            
            # Test model prediction
            test_tensor = torch.FloatTensor(scaled_input)
            
            with torch.no_grad():
                test_prediction = self.model(test_tensor)
                print(f"   Model output shape: {test_prediction.shape}")
                
            print("✅ Model validation successful!")
            
        except Exception as e:
            print(f"❌ Model validation failed: {e}")
            raise
    
    def extract_era5_sequence(self, station, target_date):
        """
        Extract 90-day ERA5 sequence for prediction
        
        Args:
            station: DischargeStation instance
            target_date: Date to predict discharge for
            
        Returns:
            numpy array: (90, 5) feature matrix
        """
        try:
            print(f"📊 Extracting ERA5 sequence for {station.station_id}")
            
            # Calculate sequence dates (90 days ending 45 days before prediction)
            sequence_end_date = target_date - timedelta(days=self.lead_time_days)
            sequence_start_date = sequence_end_date - timedelta(days=self.sequence_length - 1)
            
            print(f"   Target date: {target_date}")
            print(f"   Sequence: {sequence_start_date} to {sequence_end_date}")
            
            # Query ERA5 data for the sequence
            era5_records = ERA5Data.objects.filter(
                station=station,
                date__range=[sequence_start_date, sequence_end_date],
                is_complete=True
            ).order_by('date')
            
            available_days = era5_records.count()
            print(f"   Available data: {available_days}/{self.sequence_length} days")
            
            if available_days < self.sequence_length * 0.9:  # At least 90% data
                raise ValueError(f"Insufficient data: only {available_days}/{self.sequence_length} days available")
            
            # Build feature matrix
            feature_matrix = []
            dates_processed = []
            
            for record in era5_records:
                # Extract features in exact training order: [t2m, u10, v10, tp, q]
                features = [
                    record.temperature_2m or 0.0,
                    record.u_component_10m or 0.0,
                    record.v_component_10m or 0.0,
                    record.total_precipitation or 0.0,
                    record.specific_humidity or 0.0
                ]
                feature_matrix.append(features)
                dates_processed.append(record.date)
            
            # Convert to numpy array
            feature_matrix = np.array(feature_matrix)
            
            # Handle missing days (pad if necessary)
            if len(feature_matrix) < self.sequence_length:
                print(f"   ⚠️  Padding {self.sequence_length - len(feature_matrix)} missing days")
                # Pad with last available values
                padding = np.repeat(feature_matrix[-1:], self.sequence_length - len(feature_matrix), axis=0)
                feature_matrix = np.vstack([feature_matrix, padding])
            
            print(f"   ✅ Feature matrix shape: {feature_matrix.shape}")
            return feature_matrix, dates_processed
            
        except Exception as e:
            print(f"❌ Error extracting ERA5 sequence: {e}")
            raise
    
    def predict_discharge(self, station, target_date):
        """
        Make real-time discharge prediction using your trained model
        
        Args:
            station: DischargeStation instance  
            target_date: Date to predict discharge for
            
        Returns:
            dict: Prediction results
        """
        try:
            if not self.is_model_loaded:
                if not self.load_trained_model():
                    raise Exception("Failed to load trained model")
            
            print(f"\n🎯 Making discharge prediction for {station.name}")
            print(f"   Target date: {target_date}")
            
            # Extract ERA5 sequence
            feature_matrix, sequence_dates = self.extract_era5_sequence(station, target_date)
            
            # Reshape for model input: (1, 90, 5)
            model_input = feature_matrix.reshape(1, self.sequence_length, self.n_features)
            
            # Scale input using your trained scaler
            scaled_input = self.scaler.transform(model_input)
            
            # Convert to PyTorch tensor
            input_tensor = torch.FloatTensor(scaled_input)
            
            # Make prediction
            with torch.no_grad():
                prediction_tensor = self.model(input_tensor)
                
                # Extract prediction value
                if prediction_tensor.dim() > 1:
                    predicted_discharge = float(prediction_tensor[0][0])
                else:
                    predicted_discharge = float(prediction_tensor[0])
            
            # Calculate confidence metrics (based on recent training performance)
            # You can adjust these based on your model's validation metrics
            base_confidence = 0.85  # Adjust based on your model's R² or accuracy
            prediction_std = abs(predicted_discharge * 0.15)  # Assume 15% uncertainty
            
            confidence_lower = max(0, predicted_discharge - 1.96 * prediction_std)
            confidence_upper = predicted_discharge + 1.96 * prediction_std
            
            results = {
                'station': station,
                'target_date': target_date,
                'predicted_discharge': predicted_discharge,
                'confidence_score': base_confidence,
                'confidence_lower': confidence_lower,
                'confidence_upper': confidence_upper,
                'sequence_start': sequence_dates[0] if sequence_dates else None,
                'sequence_end': sequence_dates[-1] if sequence_dates else None,
                'data_completeness': len(sequence_dates) / self.sequence_length * 100,
                'model_used': self.model_path
            }
            
            print(f"   ✅ Prediction: {predicted_discharge:.2f} m³/s")
            print(f"   📊 Confidence: {base_confidence:.1%}")
            print(f"   📈 Range: {confidence_lower:.2f} - {confidence_upper:.2f} m³/s")
            
            return results
            
        except Exception as e:
            print(f"❌ Prediction failed: {e}")
            logger.error(f"Prediction failed for {station.station_id} on {target_date}: {e}")
            return None
    
    def save_prediction_to_database(self, prediction_results):
        """Save prediction results to database"""
        try:
            if not prediction_results:
                return None
            
            print("💾 Saving prediction to database...")
            
            # Create database record
            prediction = DischargePrediction.objects.create(
                station=prediction_results['station'],
                target_date=prediction_results['target_date'],
                predicted_discharge=prediction_results['predicted_discharge'],
                prediction_confidence=prediction_results['confidence_score'],
                confidence_lower=prediction_results['confidence_lower'],
                confidence_upper=prediction_results['confidence_upper'],
                model_name=f"trained_model_{self.sequence_length}day",
                sequence_length=self.sequence_length,
                forecast_type='daily',
                processing_status='completed'
            )
            
            print(f"   ✅ Saved prediction ID: {prediction.id}")
            return prediction
            
        except Exception as e:
            print(f"❌ Error saving prediction: {e}")
            logger.error(f"Failed to save prediction: {e}")
            return None
    
    def predict_september_discharge(self, station_id='KULK001'):
        """
        Predict discharge for entire September 2024
        
        Args:
            station_id: Station identifier (default: 'KULK001')
        """
        try:
            print(f"\n🗓️  SEPTEMBER 2024 DISCHARGE PREDICTIONS")
            print("=" * 60)
            
            # Get station
            station = DischargeStation.objects.get(station_id=station_id)
            print(f"🏭 Station: {station.name}")
            
            # September 2024 date range
            september_start = date(2024, 9, 1)
            september_end = date(2024, 9, 30)
            
            predictions = []
            successful_predictions = 0
            
            current_date = september_start
            while current_date <= september_end:
                try:
                    print(f"\n📅 Processing: {current_date}")
                    
                    # Make prediction
                    result = self.predict_discharge(station, current_date)
                    
                    if result:
                        # Save to database
                        db_prediction = self.save_prediction_to_database(result)
                        
                        if db_prediction:
                            predictions.append(result)
                            successful_predictions += 1
                            
                except Exception as e:
                    print(f"   ❌ Failed: {e}")
                
                current_date += timedelta(days=1)
            
            # Summary
            print(f"\n📊 SEPTEMBER PREDICTION SUMMARY")
            print("=" * 40)
            print(f"✅ Successful predictions: {successful_predictions}/30 days")
            
            if predictions:
                discharges = [p['predicted_discharge'] for p in predictions]
                print(f"📈 Discharge range: {min(discharges):.2f} - {max(discharges):.2f} m³/s")
                print(f"📊 Average discharge: {np.mean(discharges):.2f} m³/s")
                
                # Create monthly forecast summary
                self._create_monthly_forecast_summary(station, 2024, 9, predictions)
            
            return predictions
            
        except Exception as e:
            print(f"❌ September prediction failed: {e}")
            logger.error(f"September prediction failed: {e}")
            return []
    
    def _create_monthly_forecast_summary(self, station, year, month, daily_predictions):
        """Create monthly forecast summary from daily predictions"""
        try:
            print("\n💾 Creating monthly forecast summary...")
            
            discharges = [p['predicted_discharge'] for p in daily_predictions]
            confidences = [p['confidence_score'] for p in daily_predictions]
            
            # Create or update monthly forecast
            monthly_forecast, created = MonthlyForecast.objects.update_or_create(
                station=station,
                target_year=year,
                target_month=month,
                defaults={
                    'mean_discharge': np.mean(discharges),
                    'min_discharge': np.min(discharges),
                    'max_discharge': np.max(discharges),
                    'std_discharge': np.std(discharges),
                    'total_daily_forecasts': len(daily_predictions),
                    'rolling_window_days': self.sequence_length,
                    'prediction_confidence': np.mean(confidences),
                    'uncertainty_band_lower': np.mean(discharges) - 1.96 * np.std(discharges),
                    'uncertainty_band_upper': np.mean(discharges) + 1.96 * np.std(discharges),
                    'processing_status': 'completed'
                }
            )
            
            print(f"   ✅ Monthly forecast {'created' if created else 'updated'}: {monthly_forecast}")
            return monthly_forecast
            
        except Exception as e:
            print(f"❌ Error creating monthly summary: {e}")
            return None
    
    def test_single_prediction(self, station_id='KULK001', target_date=None):
        """Test single prediction with your trained model"""
        try:
            print(f"\n🧪 TESTING SINGLE PREDICTION")
            print("=" * 40)
            
            # Use September 15, 2024 as default test date
            if target_date is None:
                target_date = date(2024, 9, 15)
            
            # Get station
            station = DischargeStation.objects.get(station_id=station_id)
            
            # Make prediction
            result = self.predict_discharge(station, target_date)
            
            if result:
                # Save to database
                db_prediction = self.save_prediction_to_database(result)
                
                print(f"\n🎉 PREDICTION SUCCESS!")
                print(f"   Station: {station.name}")
                print(f"   Date: {target_date}")
                print(f"   Predicted discharge: {result['predicted_discharge']:.2f} m³/s")
                print(f"   Confidence: {result['confidence_score']:.1%}")
                print(f"   Uncertainty range: {result['confidence_lower']:.2f} - {result['confidence_upper']:.2f} m³/s")
                print(f"   Database ID: {db_prediction.id if db_prediction else 'Not saved'}")
                
                return result
            else:
                print("❌ Prediction failed")
                return None
                
        except Exception as e:
            print(f"❌ Test failed: {e}")
            return None

def main():
    """Main execution function"""
    print("🚀 REAL-TIME DISCHARGE PREDICTION SYSTEM")
    print("=" * 50)
    
    # Initialize predictor
    predictor = RealTimeDischargePredictor()
    
    # Load trained model
    if not predictor.load_trained_model():
        print("❌ Failed to load model. Exiting.")
        return
    
    print("\n🎯 Choose prediction mode:")
    print("1. Test single prediction (Sept 15, 2024)")
    print("2. Predict entire September 2024")
    print("3. Custom date prediction")
    
    try:
        choice = input("\nEnter choice (1-3): ").strip()
        
        if choice == '1':
            # Test single prediction
            predictor.test_single_prediction()
            
        elif choice == '2':
            # Predict entire September
            predictor.predict_september_discharge()
            
        elif choice == '3':
            # Custom date
            date_str = input("Enter date (YYYY-MM-DD): ").strip()
            target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            
            station_id = input("Enter station ID (default: KULK001): ").strip() or 'KULK001'
            
            predictor.test_single_prediction(station_id, target_date)
            
        else:
            print("Invalid choice")
            
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"❌ Error: {e}")

if __name__ == "__main__":
    main()
