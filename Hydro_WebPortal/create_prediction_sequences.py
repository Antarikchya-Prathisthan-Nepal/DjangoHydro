#!/usr/bin/env python
"""
Create Prediction Sequences Script
==================================

This script demonstrates the complete workflow for creating 90-day input sequences
with 45-day lead time for discharge prediction using preprocessed ERA5 data.

Workflow:
1. Load preprocessed ERA5 data from database
2. Create 90-day sequences with 45-day lead time
3. Validate data completeness (≥90%)
4. Generate discharge predictions using trained models
5. Store results itabn daase

Usage:
    python manage.py shell
    exec(open('create_prediction_sequences.py').read())
"""

import os
import sys
import django
from datetime import date, timedelta, datetime
import numpy as np
import pandas as pd

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from discharge_prediction.models import (
    DischargeStation, ERA5Data, ForecastSequence, 
    DischargePrediction, PipelineRun
)
from discharge_prediction.prediction_utils import DischargePredictionEngine
from django.utils import timezone
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SequenceCreator:
    """Create and manage 90-day sequences with 45-day lead time for predictions"""
    
    def __init__(self):
        self.sequence_length = 90  # 90-day input window
        self.lead_time_days = 45   # 45-day forecast horizon
        self.era5_delay_days = 7   # ERA5 data availability delay
        self.min_completeness = 90 # Minimum 90% data completeness
        
        # Initialize prediction engine
        self.prediction_engine = DischargePredictionEngine(simulate_mode=True)
        
    def calculate_sequence_dates(self, target_date):
        """
        Calculate sequence start and end dates for 90-day input with 45-day lead time
        
        Logic:
        - Target Date: Date we want to predict discharge for
        - Last Input Date: Target Date - 45 days (lead time)
        - First Input Date: Last Input Date - 89 days (90-day sequence)
        
        Example:
        - Target: 2025-03-01 (predict discharge for March 1st)
        - Last Input: 2025-01-15 (45 days before target)
        - First Input: 2024-10-18 (90 days ending at last input)
        """
        # Calculate last input date (45 days before prediction)
        sequence_end_date = target_date - timedelta(days=self.lead_time_days)
        
        # Calculate first input date (89 days before last input for 90-day total)
        sequence_start_date = sequence_end_date - timedelta(days=self.sequence_length - 1)
        
        logger.info(f"Target Date: {target_date}")
        logger.info(f"Sequence: {sequence_start_date} to {sequence_end_date} (90 days)")
        logger.info(f"Lead Time: {self.lead_time_days} days")
        
        return sequence_start_date, sequence_end_date
    
    def validate_data_availability(self, station, start_date, end_date):
        """
        Check if sufficient ERA5 data is available for the sequence period
        
        Returns:
            tuple: (is_valid, completeness_percentage, available_count, total_days)
        """
        # Calculate total days in sequence
        total_days = (end_date - start_date).days + 1
        
        # Check available data
        available_data = ERA5Data.objects.filter(
            station=station,
            date__range=[start_date, end_date],
            is_complete=True,
            processing_status__in=['processed', 'validated']
        ).count()
        
        # Calculate completeness percentage
        completeness = (available_data / total_days) * 100
        is_valid = completeness >= self.min_completeness
        
        logger.info(f"Data availability: {available_data}/{total_days} days ({completeness:.1f}%)")
        
        return is_valid, completeness, available_data, total_days
    
    def extract_sequence_data(self, station, start_date, end_date):
        """
        Extract 90-day sequence data in the correct feature order for model input
        
        Returns:
            numpy.array: Shape (90, 5) with features [t2m, u10, v10, tp, q]
        """
        # Get ERA5 data for the sequence period, ordered by date
        era5_records = ERA5Data.objects.filter(
            station=station,
            date__range=[start_date, end_date],
            is_complete=True
        ).order_by('date')
        
        if not era5_records.exists():
            raise ValueError(f"No ERA5 data found for {station.name} between {start_date} and {end_date}")
        
        # Extract feature vectors in correct order
        sequence_data = []
        date_list = []
        
        for record in era5_records:
            # Get 5-feature vector in training order: [t2m, u10, v10, tp, q]
            feature_vector = record.get_feature_vector()
            sequence_data.append(feature_vector)
            date_list.append(record.date)
        
        # Convert to numpy array
        sequence_array = np.array(sequence_data)
        
        # Handle missing days with interpolation if needed
        expected_days = (end_date - start_date).days + 1
        if len(sequence_array) < expected_days:
            logger.warning(f"Missing data: got {len(sequence_array)} days, expected {expected_days}")
            sequence_array = self._interpolate_missing_days(
                sequence_array, date_list, start_date, end_date
            )
        
        # Ensure we have exactly 90 days
        if len(sequence_array) != self.sequence_length:
            logger.warning(f"Adjusting sequence length: {len(sequence_array)} → {self.sequence_length}")
            sequence_array = sequence_array[:self.sequence_length]
        
        logger.info(f"Extracted sequence shape: {sequence_array.shape}")
        logger.info(f"Feature order: {ERA5Data.get_feature_names()}")
        
        return sequence_array
    
    def _interpolate_missing_days(self, data_array, date_list, start_date, end_date):
        """Fill missing days in sequence using linear interpolation"""
        # Create complete date range
        complete_dates = pd.date_range(start=start_date, end=end_date, freq='D')
        
        # Create DataFrame with available data
        df = pd.DataFrame(data_array, columns=ERA5Data.get_feature_names())
        df['date'] = date_list
        df.set_index('date', inplace=True)
        
        # Reindex to complete date range and interpolate
        df_complete = df.reindex(complete_dates)
        df_interpolated = df_complete.interpolate(method='linear')
        
        # Fill any remaining NaN with forward/backward fill
        df_interpolated = df_interpolated.fillna(method='ffill').fillna(method='bfill')
        
        return df_interpolated.values
    
    def create_forecast_sequence(self, station, target_date):
        """
        Create a ForecastSequence record for prediction
        
        Returns:
            ForecastSequence: The created or existing sequence
        """
        # Calculate sequence dates
        start_date, end_date = self.calculate_sequence_dates(target_date)
        
        # Create or get existing sequence
        sequence, created = ForecastSequence.objects.get_or_create(
            station=station,
            target_date=target_date,
            defaults={
                'sequence_start_date': start_date,
                'sequence_end_date': end_date,
                'sequence_length': self.sequence_length,
                'lead_time_days': self.lead_time_days,
                'era5_delay_days': self.era5_delay_days,
                'window_position': 1,
                'is_rolling_window': True
            }
        )
        
        if created:
            logger.info(f"Created new ForecastSequence for {station.name} targeting {target_date}")
        else:
            logger.info(f"Using existing ForecastSequence for {station.name} targeting {target_date}")
        
        # Validate data availability
        is_valid, completeness, available_count, total_days = self.validate_data_availability(
            station, start_date, end_date
        )
        
        # Update sequence with validation results
        sequence.data_completeness = completeness
        sequence.is_ready_for_prediction = is_valid
        sequence.save()
        
        return sequence
    
    def generate_prediction(self, station, target_date):
        """
        Generate discharge prediction for a specific station and date
        
        Returns:
            DischargePrediction: The prediction result
        """
        logger.info(f"\n🎯 Generating prediction for {station.name} on {target_date}")
        
        # Step 1: Create forecast sequence
        sequence = self.create_forecast_sequence(station, target_date)
        
        if not sequence.is_ready_for_prediction:
            raise ValueError(
                f"Insufficient data for prediction. "
                f"Completeness: {sequence.data_completeness:.1f}% (minimum: {self.min_completeness}%)"
            )
        
        # Step 2: Extract sequence data
        sequence_data = self.extract_sequence_data(
            station, sequence.sequence_start_date, sequence.sequence_end_date
        )
        
        # Step 3: Load model and make prediction
        if not self.prediction_engine.load_model():
            logger.warning("Using demo model for prediction")
        
        # Step 4: Preprocess data for model
        # Reshape for batch processing: (1, 90, 5)
        X = sequence_data.reshape(1, self.sequence_length, 5)
        
        # Apply scaling (always reshape to 2D for sklearn scalers, then back)
        original_shape = X.shape
        X_2d = X.reshape(-1, X.shape[-1])
        X_scaled_2d = self.prediction_engine.scaler.transform(X_2d)
        X_scaled = X_scaled_2d.reshape(original_shape)
        
        # Step 5: Make prediction
        prediction_result = self.prediction_engine._make_prediction(X_scaled)
        
        # Extract prediction value
        if hasattr(prediction_result, 'shape') and prediction_result.ndim > 1:
            predicted_discharge = float(prediction_result[0][0])
        else:
            predicted_discharge = float(prediction_result[0])
        
        # Step 6: Calculate confidence intervals
        prediction_std = abs(predicted_discharge * 0.15)  # 15% uncertainty
        confidence_lower = max(0, predicted_discharge - 1.96 * prediction_std)
        confidence_upper = predicted_discharge + 1.96 * prediction_std
        confidence_score = max(0.7, 1.0 - (prediction_std / predicted_discharge) if predicted_discharge > 0 else 0.7)
        
        # Step 7: Save prediction to database
        prediction, created = DischargePrediction.objects.get_or_create(
            station=station,
            target_date=target_date,
            model_name=self.prediction_engine.model_name,
            defaults={
                'predicted_discharge': predicted_discharge,
                'prediction_confidence': confidence_score,
                'confidence_lower': confidence_lower,
                'confidence_upper': confidence_upper,
                'sequence_length': self.sequence_length,
                'forecast_type': 'daily',
                'processing_status': 'completed'
            }
        )
        
        # Step 8: Update sequence processing status
        sequence.last_processed = timezone.now()
        sequence.save()
        
        logger.info(f"✅ Prediction completed: {predicted_discharge:.2f} m³/s (confidence: {confidence_score:.3f})")
        
        return prediction
    
    def create_monthly_rolling_forecast(self, station, target_month_date):
        """
        Create a complete monthly forecast using rolling 90-day windows
        
        Args:
            station: DischargeStation instance
            target_month_date: First day of the month to forecast
        
        Returns:
            list: List of daily predictions for the month
        """
        logger.info(f"\n📅 Creating monthly rolling forecast for {station.name} - {target_month_date.strftime('%B %Y')}")
        
        # Calculate last day of the month
        if target_month_date.month == 12:
            next_month = target_month_date.replace(year=target_month_date.year + 1, month=1)
        else:
            next_month = target_month_date.replace(month=target_month_date.month + 1)
        last_day_of_month = next_month - timedelta(days=1)
        
        predictions = []
        current_date = target_month_date
        
        while current_date <= last_day_of_month:
            try:
                prediction = self.generate_prediction(station, current_date)
                predictions.append(prediction)
                logger.info(f"  📊 {current_date}: {prediction.predicted_discharge:.2f} m³/s")
                
            except Exception as e:
                logger.error(f"  ❌ {current_date}: Failed - {str(e)}")
            
            current_date += timedelta(days=1)
        
        logger.info(f"📈 Monthly forecast completed: {len(predictions)} daily predictions generated")
        return predictions

def demonstrate_sequence_workflow():
    """Demonstrate the complete sequence creation and prediction workflow"""
    
    print("=" * 80)
    print("🌊 DISCHARGE PREDICTION SEQUENCE WORKFLOW DEMONSTRATION")
    print("=" * 80)
    
    # Initialize sequence creator
    creator = SequenceCreator()
    
    # Get an active station
    try:
        station = DischargeStation.objects.filter(is_active=True).first()
        if not station:
            print("❌ No active stations found. Please create a station first.")
            return
        
        print(f"🏭 Selected Station: {station.name} ({station.station_id})")
        print(f"📍 Location: {station.coordinates}")
        
        # Check available ERA5 data
        era5_count = ERA5Data.objects.filter(station=station, is_complete=True).count()
        if era5_count == 0:
            print("❌ No ERA5 data found. Please download ERA5 data first.")
            return
        
        latest_data = ERA5Data.objects.filter(station=station).order_by('-date').first()
        earliest_data = ERA5Data.objects.filter(station=station).order_by('date').first()
        
        print(f"📊 Available ERA5 Data: {era5_count} records")
        print(f"📅 Date Range: {earliest_data.date} to {latest_data.date}")
        
        # Example 1: Single day prediction
        print("\n" + "="*60)
        print("🎯 EXAMPLE 1: SINGLE DAY PREDICTION")
        print("="*60)
        
        # Use a date that should have sufficient historical data
        target_date = date.today() + timedelta(days=45)  # 45 days from now
        
        try:
            prediction = creator.generate_prediction(station, target_date)
            
            print(f"\n📋 PREDICTION RESULTS:")
            print(f"  🎯 Target Date: {prediction.target_date}")
            print(f"  💧 Predicted Discharge: {prediction.predicted_discharge:.2f} m³/s")
            print(f"  📊 Confidence: {prediction.prediction_confidence:.3f}")
            print(f"  📈 Confidence Interval: [{prediction.confidence_lower:.2f}, {prediction.confidence_upper:.2f}] m³/s")
            print(f"  🔧 Model: {prediction.model_name}")
            print(f"  📏 Sequence Length: {prediction.sequence_length} days")
            
        except Exception as e:
            print(f"❌ Single prediction failed: {str(e)}")
        
        # Example 2: Monthly forecast (first 5 days only for demo)
        print("\n" + "="*60)
        print("🗓️ EXAMPLE 2: MONTHLY FORECAST (FIRST 5 DAYS)")
        print("="*60)
        
        # Create forecast for next month (first 5 days only for demo)
        next_month_start = target_date.replace(day=1)
        if target_date.month == 12:
            next_month_start = next_month_start.replace(year=target_date.year + 1, month=1)
        else:
            next_month_start = next_month_start.replace(month=target_date.month + 1)
        
        demo_predictions = []
        for i in range(5):  # First 5 days only
            demo_date = next_month_start + timedelta(days=i)
            try:
                prediction = creator.generate_prediction(station, demo_date)
                demo_predictions.append(prediction)
            except Exception as e:
                print(f"  ❌ {demo_date}: {str(e)}")
        
        if demo_predictions:
            print(f"\n📊 MONTHLY FORECAST SUMMARY (FIRST 5 DAYS):")
            avg_discharge = np.mean([p.predicted_discharge for p in demo_predictions])
            min_discharge = min([p.predicted_discharge for p in demo_predictions])
            max_discharge = max([p.predicted_discharge for p in demo_predictions])
            
            print(f"  📈 Average Discharge: {avg_discharge:.2f} m³/s")
            print(f"  📉 Minimum Discharge: {min_discharge:.2f} m³/s")
            print(f"  📊 Maximum Discharge: {max_discharge:.2f} m³/s")
        
        # Example 3: Sequence data analysis
        print("\n" + "="*60)
        print("🔍 EXAMPLE 3: SEQUENCE DATA ANALYSIS")
        print("="*60)
        
        # Create a sequence for analysis
        sequence = creator.create_forecast_sequence(station, target_date)
        
        if sequence.is_ready_for_prediction:
            sequence_data = creator.extract_sequence_data(
                station, sequence.sequence_start_date, sequence.sequence_end_date
            )
            
            print(f"\n📊 SEQUENCE STATISTICS:")
            print(f"  📏 Shape: {sequence_data.shape}")
            print(f"  📅 Date Range: {sequence.sequence_start_date} to {sequence.sequence_end_date}")
            print(f"  ✅ Data Completeness: {sequence.data_completeness:.1f}%")
            
            # Feature statistics
            feature_names = ['Temperature (°C)', 'U-Wind (m/s)', 'V-Wind (m/s)', 'Precipitation (mm)', 'Humidity (kg/kg)']
            print(f"\n📈 FEATURE STATISTICS (90-day sequence):")
            for i, feature_name in enumerate(feature_names):
                feature_data = sequence_data[:, i]
                print(f"  {feature_name}:")
                print(f"    Mean: {np.mean(feature_data):.3f}, Std: {np.std(feature_data):.3f}")
                print(f"    Min: {np.min(feature_data):.3f}, Max: {np.max(feature_data):.3f}")
        
        print("\n" + "="*80)
        print("✅ SEQUENCE WORKFLOW DEMONSTRATION COMPLETED")
        print("="*80)
        
    except Exception as e:
        print(f"❌ Demonstration failed: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    demonstrate_sequence_workflow()
