"""
Utilities for discharge prediction using trained models

Model Configuration Recommendations:
====================================

For ERA5-only workflow (RECOMMENDED):
- DischargeRecord: Historical DHM data (pre-2015)  
- ERA5Data: Your PyTorch model input (current workflow)
- WeatherData: Future flexibility (can be unused for now)

Note: We recommend keeping all models for future flexibility, even if WeatherData
is not currently used. This allows for easy integration of additional data sources
later without major refactoring.

For minimal workflow (alternative):
You could comment out WeatherData if you're certain you'll only use ERA5 data,
but this is not recommended as it reduces future flexibility.

Consolidated from: model_recommendations.py (August 21, 2025)
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date
from django.utils import timezone
from django.conf import settings
from .models import (
    DischargeStation, ForecastSequence, MonthlyForecast, 
    DischargePrediction, PredictionModel, PipelineRun
)
from .era5_utils import ERA5Downloader
import logging
import os

# Try to import TensorFlow, but don't fail if not available
try:
    import tensorflow as tf
    TF_AVAILABLE = True
except ImportError:
    TF_AVAILABLE = False

# Try to import PyTorch for model loading
try:
    import torch
    import torch.nn as nn
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    
# Try to import joblib for scikit-learn models
try:
    import joblib
    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False

logger = logging.getLogger(__name__)

class DischargePredictionEngine:
    """Handle discharge predictions using trained models"""

    def __init__(self, model_path=None, normalization_scaler_path=None, denormalization_scaler_path=None, sequence_length=90):
        """Initialize prediction engine with your trained model
        
        Args:
            model_path: Path to your trained model file (.h5, .pkl, .joblib)
            normalization_scaler_path: Path to scaler for input normalization (.pkl, .joblib)
            denormalization_scaler_path: Path to scaler for output denormalization (.pkl, .joblib)
            sequence_length: Number of input days the model expects (default 90)
        """
        self.model_path = model_path
        self.normalization_scaler_path = normalization_scaler_path
        self.denormalization_scaler_path = denormalization_scaler_path
        self.model = None
        self.normalization_scaler = None
        self.denormalization_scaler = None
        self.era5_downloader = ERA5Downloader()

        # Model configuration - adjust these to match your trained model
        self.sequence_length = sequence_length
        self.lead_time_days = 45  # Lead time from last input to prediction
        self.era5_delay_days = 7  # ERA5 data availability delay

        # Feature configuration — MUST match the training order used when the model was trained.
        # Default: 6-feature pipeline (t2m, u10, v10, tp, q, soil_moisture).
        # For legacy 5-feature models, pass feature_names explicitly to __init__ or set
        # use_extended_features=False when calling preprocess_for_model_inference().
        self.feature_names = [
            'temperature_2m',      # t2m
            'u_component_10m',     # u10
            'v_component_10m',     # v10
            'total_precipitation', # tp
            'specific_humidity',   # q
            'soil_moisture',       # swvl1
        ]
        self.n_features = len(self.feature_names)  # 6

        # Model metadata
        self.model_name = f"discharge_model_{self.sequence_length}day"
        self.model_version = "1.0"
    
    def load_model(self):
        """Load your trained model and preprocessing artifacts"""
        try:
            # Load your actual trained model
            if self.model_path and os.path.exists(self.model_path):
                file_ext = os.path.splitext(self.model_path)[1].lower()

                if file_ext in ['.h5', '.hdf5']:
                    # TensorFlow/Keras model
                    if not TF_AVAILABLE:
                        raise ImportError("TensorFlow not available but .h5 model file provided")
                    self.model = tf.keras.models.load_model(self.model_path)
                    logger.info(f"Loaded Keras model from {self.model_path}")

                elif file_ext in ['.pt', '.pth']:
                    # PyTorch model (load from state_dict using GRUModel or LSTMModel)
                    if not TORCH_AVAILABLE:
                        raise ImportError("PyTorch not available but .pt/.pth model file provided")
                    import torch
                    from .pytorch_utils import GRUModel
                    try:
                        from .pytorch_utils import LSTMModel
                        has_lstm = True
                    except ImportError:
                        has_lstm = False
                    # Choose model class based on file name or config
                    model_class = None
                    if 'lstm' in os.path.basename(self.model_path).lower() and has_lstm:
                        model_class = LSTMModel
                        logger.info("Detected LSTM model checkpoint.")
                    else:
                        model_class = GRUModel
                        logger.info("Detected GRU model checkpoint (default).")
                    checkpoint = torch.load(self.model_path, map_location='cpu')
                    # Handle both checkpoint dicts and plain state_dicts
                    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
                        state_dict = checkpoint["model_state_dict"]
                        logger.info("Loaded model_state_dict from checkpoint.")
                    else:
                        state_dict = checkpoint
                        logger.info("Loaded plain state_dict.")
                    # Auto-detect input_size from checkpoint weights before instantiating model
                    if 'lstm.weight_ih_l0' in state_dict:
                        detected_input_size = state_dict['lstm.weight_ih_l0'].shape[1]
                        if detected_input_size != self.n_features:
                            logger.info(
                                f"Auto-detected input_size={detected_input_size} from checkpoint "
                                f"(overrides n_features={self.n_features})."
                            )
                            self.n_features = detected_input_size
                            self.feature_names = self.feature_names[:self.n_features]
                    model = model_class(input_size=self.n_features, hidden_size=64, num_layers=2, dropout=0.2)
                    model.load_state_dict(state_dict)
                    model.eval()
                    self.model = model
                    # Set model_name dynamically based on loaded model class
                    self.model_name = type(self.model).__name__
                    logger.info(f"Loaded PyTorch model ({self.model_name}) from state_dict: {self.model_path}")

                elif file_ext in ['.pkl', '.joblib']:
                    # Scikit-learn or other joblib model
                    if not JOBLIB_AVAILABLE:
                        raise ImportError("joblib not available but .pkl/.joblib model file provided")
                    import joblib
                    self.model = joblib.load(self.model_path)
                    logger.info(f"Loaded joblib model from {self.model_path}")

                else:
                    raise ValueError(f"Unsupported model file format: {file_ext}. Supported: .h5/.hdf5 (Keras), .pt/.pth (PyTorch), .pkl/.joblib (scikit-learn)")
            else:
                raise FileNotFoundError(f"Model file not found: {self.model_path}")

            # Load normalization scaler
            if self.normalization_scaler_path and os.path.exists(self.normalization_scaler_path):
                import joblib
                self.normalization_scaler = joblib.load(self.normalization_scaler_path)
                logger.info(f"Loaded normalization scaler from {self.normalization_scaler_path}")
                # The model's detected input_size is authoritative. If the scaler was fit
                # on more features than the model needs (e.g. 7-feature scaler + 5-feature
                # model), subset it so transform() accepts the correct number of features.
                if hasattr(self.normalization_scaler, 'n_features_in_'):
                    scaler_n = self.normalization_scaler.n_features_in_
                    if scaler_n != self.n_features:
                        if scaler_n > self.n_features:
                            # Subset: keep only the first n_features columns
                            import numpy as np
                            s = self.normalization_scaler
                            for attr in ('data_min_', 'data_max_', 'data_range_', 'scale_', 'min_'):
                                if hasattr(s, attr):
                                    setattr(s, attr, getattr(s, attr)[:self.n_features])
                            s.n_features_in_ = self.n_features
                            logger.info(
                                f"Scaler had {scaler_n} features; subsetted to first "
                                f"{self.n_features} to match model input_size."
                            )
                        else:
                            # Scaler has fewer features than model — genuine mismatch
                            logger.warning(
                                f"Scaler has {scaler_n} features but model expects "
                                f"{self.n_features}. This may cause errors."
                            )
            else:
                raise FileNotFoundError(f"Normalization scaler file not found: {self.normalization_scaler_path}")

            # Load denormalization scaler
            if self.denormalization_scaler_path and os.path.exists(self.denormalization_scaler_path):
                import joblib
                self.denormalization_scaler = joblib.load(self.denormalization_scaler_path)
                logger.info(f"Loaded denormalization scaler from {self.denormalization_scaler_path}")
            else:
                raise FileNotFoundError(f"Denormalization scaler file not found: {self.denormalization_scaler_path}")

            # Validate model input shape
            self._validate_model_compatibility()

            # Explicitly log the loaded model class name for verification
            logger.info(f"Model loaded successfully: {self.model_name}")
            logger.info(f"Loaded model Python class: {type(self.model).__name__}")
            return True

        except Exception as e:
            logger.error(f"Failed to load model or scaler: {str(e)}")
            raise
    
    def _validate_model_compatibility(self):
        """Validate that the loaded model is compatible with our data format"""
        try:
            # Create test input with correct shape: (batch_size, sequence_length, n_features)
            test_input = np.random.random((1, self.sequence_length, self.n_features))

            # Test if normalization scaler works - always reshape to 2D for sklearn scalers, then back to original shape
            if hasattr(self.normalization_scaler, 'transform'):
                original_shape = test_input.shape
                test_2d = test_input.reshape(-1, self.n_features)
                scaled_2d = self.normalization_scaler.transform(test_2d)
                scaled_input = scaled_2d.reshape(original_shape)
            else:
                scaled_input = test_input

            # Test if model can make predictions
            if TORCH_AVAILABLE and hasattr(self.model, 'forward'):
                # PyTorch model - use the _make_prediction method
                test_prediction = self._make_prediction(scaled_input)
                logger.info(f"Model validation successful - output shape: {test_prediction.shape}")
            elif hasattr(self.model, 'predict'):
                # scikit-learn or Keras model
                test_prediction = self.model.predict(scaled_input)
                logger.info(f"Model validation successful - output shape: {test_prediction.shape}")
            else:
                raise ValueError("Model does not have predict method or forward method")

        except Exception as e:
            logger.error(f"Model compatibility validation failed: {e}")
            raise
    
    def _make_prediction(self, X_scaled):
        """Make prediction using the appropriate method for different model types"""
        try:
            # Handle PyTorch models
            if TORCH_AVAILABLE and hasattr(self.model, 'forward'):
                import torch
                # Convert to torch tensor
                X_tensor = torch.FloatTensor(X_scaled)
                
                # Make prediction in evaluation mode
                with torch.no_grad():
                    if hasattr(self.model, 'eval'):
                        self.model.eval()
                    prediction = self.model(X_tensor)
                    
                # Convert back to numpy
                if hasattr(prediction, 'cpu'):
                    prediction = prediction.cpu().numpy()
                else:
                    prediction = prediction.detach().numpy()
                    
                return prediction
            
            # Handle TensorFlow/Keras models 
            elif TF_AVAILABLE and hasattr(self.model, 'predict'):
                return self.model.predict(X_scaled, verbose=0)
            
            # Handle scikit-learn models
            elif hasattr(self.model, 'predict'):
                return self.model.predict(X_scaled)
            
            # Handle custom models (like demo model)
            elif hasattr(self.model, 'predict'):
                return self.model.predict(X_scaled)
                
            else:
                raise ValueError(f"Unknown model type: {type(self.model)}. Model should have 'predict' method or be a PyTorch model with 'forward' method.")
                
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            raise
    
    def predict_single_day(self, station, target_date):
        """
        Predict discharge for a single day.

        Data-source strategy
        --------------------
        1. ERA5 (primary) — always required; drives the 90-day model input.
        2. DischargeRecord (observed avg discharge) — if a record exists for
           ``target_date``, it is stored in ``DischargePrediction.actual_discharge``
           so accuracy metrics can be calculated immediately.
        3. SensorReading (GST) — if a reading with ``discharge_depth`` exists
           on ``target_date``, it is logged and stored in
           ``DischargePrediction.actual_discharge`` (takes priority over
           DischargeRecord when both are present, as it is higher-frequency /
           more recent).

        If only ERA5 is available the pipeline proceeds normally (existing
        behaviour).  The ``data_sources_used`` key in the pipeline_run log
        captures which sources were actually available.

        Args:
            station: DischargeStation instance
            target_date: Date to predict discharge for

        Returns:
            tuple: (predicted_discharge, confidence_interval, success)
        """
        from .models import DHMStage, SensorReading

        try:
            if self.model is None:
                if not self.load_model():
                    raise Exception("Failed to load prediction model")

            # ── Build / retrieve ForecastSequence ────────────────────────
            sequence, created = ForecastSequence.objects.get_or_create(
                station=station,
                target_date=target_date,
                defaults={
                    'sequence_length': self.sequence_length,
                    'lead_time_days': self.lead_time_days,
                    'era5_delay_days': self.era5_delay_days,
                    'window_position': 0,
                    'is_rolling_window': True,
                }
            )

            if created:
                sequence.calculate_sequence_dates()
                sequence.save()

            # ── Check all data sources ────────────────────────────────────
            availability = sequence.get_available_data_sources()
            logger.info(
                "[DATA_SOURCES] %s / %s — ERA5: %d days, DischargeRecords: %d days, "
                "SensorReadings: %d days",
                station.name, target_date,
                availability['era5']['count'],
                availability['discharge_records']['count'],
                availability['sensor_readings']['count'],
            )

            # ERA5 is the gating condition for inference
            sequence.validate_data_availability()
            if not sequence.is_ready_for_prediction:
                raise Exception(
                    f"Insufficient ERA5 data for prediction: "
                    f"{sequence.data_completeness:.1f}% complete "
                    f"({availability['era5']['count']}/{self.sequence_length} days)"
                )

            # ── ERA5-based inference (unchanged) ─────────────────────────
            input_sequence = self.era5_downloader.preprocess_for_model_inference(
                station,
                sequence.sequence_start_date,
                sequence.sequence_end_date,
                training_scaler_path=self.normalization_scaler_path,
                use_extended_features=(self.n_features >= 6),
            )

            if input_sequence.shape != (self.sequence_length, self.n_features):
                logger.warning(
                    "Sequence shape %s, expected (%d, %d)",
                    input_sequence.shape, self.sequence_length, self.n_features
                )

            X = input_sequence.reshape(1, self.sequence_length, self.n_features)
            original_shape = X.shape
            X_2d = X.reshape(-1, self.n_features)
            X_scaled_2d = self.normalization_scaler.transform(X_2d)
            X_scaled = X_scaled_2d.reshape(original_shape)

            prediction = self._make_prediction(X_scaled)

            if hasattr(prediction, 'shape') and prediction.ndim > 1:
                predicted_discharge_scaled = float(prediction[0][0])
            else:
                predicted_discharge_scaled = float(prediction[0])

            if hasattr(self.denormalization_scaler, 'inverse_transform'):
                y_pred = self.denormalization_scaler.inverse_transform(
                    np.array([[predicted_discharge_scaled]])
                ).flatten()
                y_pred[y_pred < 0] = 0
                predicted_discharge = float(y_pred[0])
            else:
                predicted_discharge = predicted_discharge_scaled

            # ── Energy calculation ────────────────────────────────────────
            net_head = getattr(station, 'net_head', None)
            efficiency = getattr(station, 'efficiency', None)
            max_discharge = getattr(station, 'max_discharge_for_energy', None)
            rho, g = 1000, 9.81

            discharge_for_energy = predicted_discharge
            debug_energy_log = {
                'station': getattr(station, 'name', str(station)),
                'predicted_discharge': predicted_discharge,
                'max_discharge_for_energy': max_discharge,
                'net_head': net_head,
                'efficiency': efficiency,
                'data_sources': availability,
            }
            if max_discharge is not None:
                try:
                    max_discharge = float(max_discharge)
                    if predicted_discharge > max_discharge:
                        discharge_for_energy = max_discharge
                except Exception as cap_err:
                    logger.warning(
                        "Could not apply discharge cap for %s: %s",
                        getattr(station, 'name', str(station)), cap_err
                    )
            debug_energy_log['discharge_for_energy'] = discharge_for_energy
            logger.info("[ENERGY_CALC] %s", debug_energy_log)

            power_mw = (efficiency * rho * g * discharge_for_energy * net_head) / 1e6
            predicted_energy = power_mw * 24

            prediction_std = np.std(
                [predicted_discharge * (1 + np.random.normal(0, 0.1)) for _ in range(10)]
            )
            confidence_lower = max(0, predicted_discharge - 1.96 * prediction_std)
            confidence_upper = predicted_discharge + 1.96 * prediction_std
            confidence_score = max(
                0.5,
                1.0 - (prediction_std / predicted_discharge) if predicted_discharge > 0 else 0.5
            )

            # ── Resolve actual observed discharge for immediate validation ─
            # Priority: GST SensorReading.discharge_depth > DischargeRecord.discharge
            actual_discharge = None

            # 1. Check SensorReading (GST device — higher priority)
            gst_reading = (
                SensorReading.objects
                .filter(station=station, timestamp__date=target_date, discharge_depth__isnull=False)
                .order_by('-timestamp')
                .first()
            )
            if gst_reading:
                actual_discharge = gst_reading.discharge_depth
                logger.info(
                    "[ACTUAL_DISCHARGE] %s / %s — GST reading: %.3f m³/s",
                    station.name, target_date, actual_discharge
                )

            # 2. Fall back to DHMStage (DHM / manual entry)
            if actual_discharge is None:
                obs_record = (
                    DHMStage.objects
                    .filter(station=station, timestamp__date=target_date)
                    .order_by('-timestamp')
                    .first()
                )
                if obs_record:
                    actual_discharge = station.compute_discharge_from_stage(obs_record.stage_height)
                    logger.info(
                        "[ACTUAL_DISCHARGE] %s / %s — DHMStage: %.3f m³/s",
                        station.name, target_date, actual_discharge
                    )

            # ── Persist prediction ────────────────────────────────────────
            discharge_prediction, _ = DischargePrediction.objects.update_or_create(
                station=station,
                target_date=target_date,
                model_name=self.model_name,
                defaults={
                    'predicted_discharge': predicted_discharge,
                    'predicted_energy': predicted_energy,
                    'prediction_confidence': confidence_score,
                    'confidence_lower': confidence_lower,
                    'confidence_upper': confidence_upper,
                    'sequence_length': self.sequence_length,
                    'forecast_type': 'daily',
                    'processing_status': 'completed',
                    'actual_discharge': actual_discharge,
                }
            )

            if actual_discharge is not None:
                discharge_prediction.calculate_accuracy()

            sequence.last_processed = timezone.now()
            sequence.save()

            logger.info(
                "Prediction completed for %s on %s: %.2f m³/s%s",
                station.name, target_date, predicted_discharge,
                f" (actual: {actual_discharge:.2f})" if actual_discharge else ""
            )

            return predicted_discharge, (confidence_lower, confidence_upper), True

        except Exception as e:
            logger.error("Prediction failed for %s on %s: %s", station.name, target_date, str(e))
            return None, None, False
    
    def predict_monthly_discharge(self, station, forecast_month_date):
        """
        Generate predictions for entire month
        
        Args:
            station: DischargeStation instance
            forecast_month_date: First day of month to forecast
        
        Returns:
            MonthlyForecast instance
        """
        try:
            # Get or create monthly forecast record
            forecast_year = forecast_month_date.year
            forecast_month_number = forecast_month_date.month
            
            # Get prediction model
            try:
                model_record = PredictionModel.objects.get(name=self.model_name, is_active=True)
            except PredictionModel.DoesNotExist:
                # Create default model record
                model_record = PredictionModel.objects.create(
                    name=self.model_name,
                    version='1.0',
                    model_type='deep_learning',
                    description='LSTM model for discharge prediction',
                    input_features=['precipitation', 'temperature', 'humidity', 'wind_speed'],
                    validation_score=0.85,
                    is_active=True
                )
            
            monthly_forecast, created = MonthlyForecast.objects.get_or_create(
                station=station,
                target_year=forecast_year,
                target_month=forecast_month_number,
                defaults={
                    'processing_status': 'in_progress'
                }
            )
            
            if not created and monthly_forecast.processing_status == 'completed':
                logger.info(f"Monthly forecast already exists for {station.name} - {forecast_month_date.strftime('%B %Y')}")
                return monthly_forecast
            
            # Create pipeline run for tracking
            pipeline_run = PipelineRun.objects.create(
                run_type='monthly',
                station=station,
                target_date=forecast_month_date,
                scheduled_time=timezone.now(),
                parameters={
                    'forecast_month': forecast_month_date.isoformat(),
                    'model_name': self.model_name
                }
            )
            
            pipeline_run.mark_started()
            monthly_forecast.processing_status = 'processing'
            monthly_forecast.save()
            
            # Calculate all days in the month
            if forecast_month_date.month == 12:
                next_month = forecast_month_date.replace(year=forecast_month_date.year + 1, month=1)
            else:
                next_month = forecast_month_date.replace(month=forecast_month_date.month + 1)
            
            last_day_of_month = next_month - timedelta(days=1)
            
            # Predict each day in the month
            current_date = forecast_month_date
            successful_predictions = 0
            failed_predictions = 0
            
            # Monthly energy tracking
            monthly_energy_total = 0.0
            monthly_discharge_total = 0.0
            daily_energy_predictions = []
            daily_discharge_predictions = []
            
            while current_date <= last_day_of_month:
                try:
                    predicted_discharge, confidence_interval, success = self.predict_single_day(
                        station, current_date
                    )
                    
                    if success:
                        successful_predictions += 1
                        daily_discharge_predictions.append(predicted_discharge)
                        monthly_discharge_total += predicted_discharge
                        
                        # Get the daily energy prediction from the saved DischargePrediction record
                        daily_prediction = DischargePrediction.objects.filter(
                            station=station,
                            target_date=current_date
                        ).order_by('-id').first()
                        
                        if daily_prediction and daily_prediction.predicted_energy:
                            daily_energy = daily_prediction.predicted_energy
                            daily_energy_predictions.append(daily_energy)
                            monthly_energy_total += daily_energy
                            
                            pipeline_run.add_log('INFO', f"Predicted {current_date}: {predicted_discharge:.2f} m³/s, {daily_energy:.2f} MWh")
                        else:
                            pipeline_run.add_log('INFO', f"Predicted {current_date}: {predicted_discharge:.2f} m³/s (energy calculation failed)")
                    else:
                        failed_predictions += 1
                        pipeline_run.add_log('ERROR', f"Failed to predict {current_date}")
                    
                except Exception as e:
                    failed_predictions += 1
                    pipeline_run.add_log('ERROR', f"Error predicting {current_date}: {str(e)}")
                
                current_date += timedelta(days=1)
                
                # Update progress (save current state)
                monthly_forecast.save()
            
            # Finalize forecast
            pipeline_run.processed_records = successful_predictions
            pipeline_run.error_count = failed_predictions
            
            if successful_predictions > 0:
                # Calculate monthly energy statistics
                avg_daily_discharge = monthly_discharge_total / successful_predictions if successful_predictions > 0 else 0
                avg_daily_energy = monthly_energy_total / len(daily_energy_predictions) if daily_energy_predictions else 0
                
                # Add monthly energy summary to pipeline parameters
                monthly_energy_summary = {
                    'total_monthly_energy_mwh': round(monthly_energy_total, 2),
                    'average_daily_energy_mwh': round(avg_daily_energy, 2),
                    'total_monthly_discharge_m3s': round(monthly_discharge_total, 2),
                    'average_daily_discharge_m3s': round(avg_daily_discharge, 2),
                    'successful_predictions': successful_predictions,
                    'failed_predictions': failed_predictions,
                    'energy_predictions_count': len(daily_energy_predictions)
                }
                
                # Update pipeline run parameters with energy summary
                pipeline_run.parameters.update({
                    'monthly_energy_summary': monthly_energy_summary
                })
                pipeline_run.save()
                
                monthly_forecast.aggregate_daily_predictions()
                pipeline_run.mark_completed()
                
                monthly_forecast.processing_status = 'completed'
                
                # Enhanced logging with energy information
                logger.info(f"Monthly forecast completed for {station.name}: {successful_predictions}/{successful_predictions + failed_predictions} days predicted")
                logger.info(f"Monthly Energy Summary for {station.name} ({forecast_month_date.strftime('%B %Y')}):")
                logger.info(f"  - Total Monthly Energy: {monthly_energy_total:.2f} MWh")
                logger.info(f"  - Average Daily Energy: {avg_daily_energy:.2f} MWh/day")
                logger.info(f"  - Total Monthly Discharge: {monthly_discharge_total:.2f} m³/s")
                logger.info(f"  - Average Daily Discharge: {avg_daily_discharge:.2f} m³/s")
                
                # Add final energy summary log to pipeline
                pipeline_run.add_log('INFO', f"MONTHLY ENERGY SUMMARY: {monthly_energy_total:.2f} MWh total, {avg_daily_energy:.2f} MWh/day average")
                
            else:
                monthly_forecast.processing_status = 'failed'
                pipeline_run.mark_failed("No successful predictions generated")
                logger.error(f"Monthly forecast failed for {station.name}: no successful predictions")
            
            monthly_forecast.save()
            return monthly_forecast
            
        except Exception as e:
            logger.error(f"Monthly forecast generation failed: {str(e)}")
            if 'monthly_forecast' in locals():
                monthly_forecast.processing_status = 'failed'
                monthly_forecast.save()
            if 'pipeline_run' in locals():
                pipeline_run.mark_failed(str(e))
            raise
    
    def validate_predictions(self, station, start_date, end_date):
        """
        Validate predictions against actual discharge data
        
        Args:
            station: DischargeStation instance
            start_date: Start date for validation
            end_date: End date for validation
        """
        try:
            from .models import DHMStage
            
            # Get predictions for validation period
            predictions = DischargePrediction.objects.filter(
                station=station,
                forecast_timestamp__date__range=[start_date, end_date],
                actual_discharge__isnull=True
            )
            
            validated_count = 0
            
            for prediction in predictions:
                try:
                    # Look for actual discharge data
                    actual_record = DHMStage.objects.filter(
                        station=station,
                        timestamp__date=prediction.forecast_timestamp.date()
                    ).first()
                    
                    if actual_record:
                        # Update prediction with actual data
                        actual_h = actual_record.stage_height
                        actual_q = station.compute_discharge_from_stage(actual_h) if actual_h is not None else None
                        prediction.actual_discharge = actual_q

                        # Calculate accuracy
                        if actual_q is not None:
                            error = abs(prediction.predicted_discharge - actual_q)
                            relative_error = error / max(actual_q, 0.001)
                            accuracy = max(0, 1 - relative_error)
                            prediction.accuracy_score = accuracy
                        
                        prediction.save()
                        validated_count += 1
                        
                except Exception as e:
                    logger.error(f"Error validating prediction for {prediction.forecast_timestamp}: {str(e)}")
            
            logger.info(f"Validated {validated_count} predictions for {station.name}")
            return validated_count
            
        except Exception as e:
            logger.error(f"Prediction validation failed: {str(e)}")
            return 0
    
    def get_monthly_energy_summary(self, station, year, month):
        """
        Get monthly energy summary for a specific station and month
        
        Args:
            station: DischargeStation instance
            year: Year (int)
            month: Month (int, 1-12)
        
        Returns:
            dict: Monthly energy summary with totals and averages
        """
        try:
            from calendar import monthrange
            
            # Get first and last day of the month
            first_day = date(year, month, 1)
            last_day = date(year, month, monthrange(year, month)[1])
            
            # Get all predictions for the month
            predictions = DischargePrediction.objects.filter(
                station=station,
                target_date__range=[first_day, last_day],
                processing_status='completed'
            ).order_by('target_date')
            
            if not predictions.exists():
                return {
                    'station_name': station.name,
                    'year': year,
                    'month': month,
                    'month_name': first_day.strftime('%B'),
                    'total_predictions': 0,
                    'total_monthly_energy_mwh': 0,
                    'total_monthly_discharge_m3s': 0,
                    'average_daily_energy_mwh': 0,
                    'average_daily_discharge_m3s': 0,
                    'max_daily_energy_mwh': 0,
                    'min_daily_energy_mwh': 0,
                    'predictions': []
                }
            
            # Calculate totals and statistics
            total_energy = sum(p.predicted_energy or 0 for p in predictions)
            total_discharge = sum(p.predicted_discharge or 0 for p in predictions)
            energy_values = [p.predicted_energy for p in predictions if p.predicted_energy]
            discharge_values = [p.predicted_discharge for p in predictions if p.predicted_discharge]
            
            summary = {
                'station_name': station.name,
                'year': year,
                'month': month,
                'month_name': first_day.strftime('%B'),
                'total_predictions': predictions.count(),
                'total_monthly_energy_mwh': round(total_energy, 2),
                'total_monthly_discharge_m3s': round(total_discharge, 2),
                'average_daily_energy_mwh': round(total_energy / predictions.count(), 2) if predictions.count() > 0 else 0,
                'average_daily_discharge_m3s': round(total_discharge / predictions.count(), 2) if predictions.count() > 0 else 0,
                'max_daily_energy_mwh': round(max(energy_values), 2) if energy_values else 0,
                'min_daily_energy_mwh': round(min(energy_values), 2) if energy_values else 0,
                'max_daily_discharge_m3s': round(max(discharge_values), 2) if discharge_values else 0,
                'min_daily_discharge_m3s': round(min(discharge_values), 2) if discharge_values else 0,
                'predictions': [
                    {
                        'date': p.target_date.isoformat(),
                        'discharge_m3s': round(p.predicted_discharge, 2),
                        'energy_mwh': round(p.predicted_energy, 2) if p.predicted_energy else 0,
                        'confidence': round(p.prediction_confidence, 3) if p.prediction_confidence else 0
                    }
                    for p in predictions
                ]
            }
            
            logger.info(f"Generated monthly energy summary for {station.name} - {first_day.strftime('%B %Y')}: {total_energy:.2f} MWh total")
            return summary
            
        except Exception as e:
            logger.error(f"Failed to generate monthly energy summary: {str(e)}")
            return {
                'error': str(e),
                'station_name': getattr(station, 'name', 'Unknown'),
                'year': year,
                'month': month
            }
    
    def get_monthly_forecast_with_energy(self, station, year, month):
        """
        Get or create MonthlyForecast and return with energy summary
        
        Args:
            station: DischargeStation instance
            year: Year (int)
            month: Month (int, 1-12)
            
        Returns:
            dict: MonthlyForecast energy summary with aggregated statistics
        """
        try:
            # Get or create monthly forecast
            monthly_forecast, created = MonthlyForecast.objects.get_or_create(
                station=station,
                target_year=year,
                target_month=month
            )
            
            # Update aggregated statistics if needed
            if created or monthly_forecast.processing_status != 'completed':
                monthly_forecast.aggregate_daily_predictions()
            
            # Return comprehensive energy summary
            summary = monthly_forecast.get_monthly_energy_summary()
            
            # Add daily breakdown if requested
            daily_predictions = list(monthly_forecast.get_daily_predictions_with_energy())
            summary['daily_predictions'] = daily_predictions
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to get monthly forecast with energy: {str(e)}")
            return {
                'error': str(e),
                'station_name': getattr(station, 'name', 'Unknown'),
                'year': year,
                'month': month
            }

class ForecastScheduler:
    """Handle scheduling and automation of forecast generation"""
    
    def __init__(self):
        self.prediction_engine = DischargePredictionEngine()
    
    def schedule_monthly_forecasts(self, target_month_date=None):
        """
        Schedule monthly forecasts for all active stations
        
        Args:
            target_month_date: Month to forecast (default: next month)
        """
        if target_month_date is None:
            # Default to next month
            today = date.today()
            if today.month == 12:
                target_month_date = date(today.year + 1, 1, 1)
            else:
                target_month_date = date(today.year, today.month + 1, 1)
        
        active_stations = DischargeStation.objects.filter(is_active=True)
        
        for station in active_stations:
            try:
                # Check if forecast should be generated (1 week before month)
                days_until_month = (target_month_date - date.today()).days
                
                if 0 <= days_until_month <= 7:  # Generate 1 week before
                    logger.info(f"Scheduling monthly forecast for {station.name} - {target_month_date.strftime('%B %Y')}")
                    
                    # Generate forecast
                    forecast = self.prediction_engine.predict_monthly_discharge(
                        station, target_month_date
                    )
                    
                    logger.info(f"Monthly forecast scheduled for {station.name}: Status {forecast.status}")
                    
            except Exception as e:
                logger.error(f"Failed to schedule forecast for {station.name}: {str(e)}")
    
    def run_automated_pipeline(self):
        """
        Run the complete automated pipeline:
        1. Download ERA5 data
        2. Generate predictions
        3. Update plots
        """
        try:
            from .era5_utils import ERA5PipelineManager
            
            logger.info("Starting automated daily pipeline")
            
            # Step 1: Download and process ERA5 data
            era5_manager = ERA5PipelineManager()
            era5_manager.run_daily_pipeline()
            
            # Step 2: Generate predictions for upcoming month
            self.schedule_monthly_forecasts()
            
            # Step 3: Validate past predictions
            yesterday = date.today() - timedelta(days=1)
            validation_start = yesterday - timedelta(days=30)
            
            active_stations = DischargeStation.objects.filter(is_active=True)
            for station in active_stations:
                self.prediction_engine.validate_predictions(
                    station, validation_start, yesterday
                )
            
            logger.info("Automated pipeline completed successfully")
            
        except Exception as e:
            logger.error(f"Automated pipeline failed: {str(e)}")
            raise
