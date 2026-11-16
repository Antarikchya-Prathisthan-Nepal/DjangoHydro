#!/usr/bin/env python3
"""
Automated ForecastSequence Creation and Prediction Script
=======================================================
- For each discharge station:
    - Finds available ERA5 data range
    - Iterates over all possible target dates (90-day input, 45-day lead)
    - For each date:
        - Creates ForecastSequence if not exists (idempotent)
        - Normalizes input sequence using station's scaler
        - Loads station's model
        - Triggers prediction if sequence is ready
- Model/scaler paths are station-specific (customize as needed)

Usage:
    python manage.py shell < automate_sequences_and_predictions.py
"""

import os
import sys
import re
import django
from datetime import timedelta, date
import logging

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from django.conf import settings
_BASE_DIR = str(settings.BASE_DIR)

from discharge_prediction.models import DischargeStation, ERA5Data, ForecastSequence, DischargePrediction
from discharge_prediction.prediction_utils import DischargePredictionEngine
from django.db import transaction

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

LEAD_TIME = 45

def get_data_range(station):
    qs = ERA5Data.objects.filter(station=station, is_complete=True).order_by('date')
    if not qs.exists():
        return None, None
    return qs.first().date, qs.last().date

def main():
    stations = DischargeStation.objects.all()
    for station in stations:
        logger.info(f"Processing station: {station.name} ({station.station_id})")
        data_start, data_end = get_data_range(station)
        if not data_start or not data_end:
            logger.warning(f"No ERA5 data for station {station.name}")
            continue
        logger.info(f"Available data: {data_start} to {data_end}")
        def _abs(p):
            """Resolve a DB-stored path (possibly relative) to an absolute path."""
            if p and not os.path.isabs(p):
                return os.path.join(_BASE_DIR, p)
            return p

        model_path = _abs(station.model_file_path)
        scaler_path = _abs(station.scaler_file_path)
        denorm_scaler_path = _abs(getattr(station, 'denormalization_scaler_path', None))
        if not model_path or not scaler_path or not denorm_scaler_path:
            logger.error(f"Model/scaler/denormalization scaler path not configured for station id {station.id} ({station.name})")
            continue
        # Derive sequence length from the input scaler filename (e.g. UM_input_scaler_365day → 365)
        _match = re.search(r'(\d+)day', scaler_path) if scaler_path else None
        station_seq_length = int(_match.group(1)) if _match else 90
        logger.info(f"Using sequence_length={station_seq_length} for station {station.name}")
        earliest_sequence_end = data_start + timedelta(days=station_seq_length-1)
        earliest_target_date = earliest_sequence_end + timedelta(days=LEAD_TIME)
        latest_sequence_end = data_end
        latest_target_date = latest_sequence_end + timedelta(days=LEAD_TIME)
        target_date = earliest_target_date
        engine = DischargePredictionEngine(
            model_path=model_path,
            normalization_scaler_path=scaler_path,
            denormalization_scaler_path=denorm_scaler_path,
            sequence_length=station_seq_length
        )
        logger.info(f"Attempting to load model from: {model_path}")
        logger.info(f"Attempting to load normalization scaler from: {scaler_path}")
        logger.info(f"Attempting to load denormalization scaler from: {denorm_scaler_path}")
        model_loaded = engine.load_model()
        if hasattr(engine.model, '__class__'):
            logger.info(f"Loaded model class: {engine.model.__class__}")
        else:
            logger.warning("Model class could not be determined.")
        if hasattr(engine.normalization_scaler, '__class__'):
            logger.info(f"Loaded normalization scaler class: {engine.normalization_scaler.__class__}")
        else:
            logger.warning("Normalization scaler class could not be determined.")
        if hasattr(engine.denormalization_scaler, '__class__'):
            logger.info(f"Loaded denormalization scaler class: {engine.denormalization_scaler.__class__}")
        else:
            logger.warning("Denormalization scaler class could not be determined.")
        if not model_loaded:
            logger.warning("Model loading failed or fallback to demo model occurred!")
        while target_date <= latest_target_date:
            sequence_end = target_date - timedelta(days=LEAD_TIME)
            sequence_start = sequence_end - timedelta(days=station_seq_length-1)
            if sequence_start < data_start or sequence_end > data_end:
                target_date += timedelta(days=1)
                continue
            # Skip dates that already have a completed prediction
            if DischargePrediction.objects.filter(
                station=station,
                target_date=target_date,
                processing_status='completed'
            ).exists():
                logger.debug(f"Skipping {target_date} — prediction already exists")
                target_date += timedelta(days=1)
                continue
            try:
                with transaction.atomic():
                    seq, created = ForecastSequence.objects.get_or_create(
                        station=station,
                        target_date=target_date,
                        defaults={
                            'sequence_length': station_seq_length,
                            'lead_time_days': LEAD_TIME,
                        }
                    )
                    if created:
                        seq.calculate_sequence_dates()
                        seq.save()
                        logger.info(f"Created ForecastSequence for {target_date}")
                    else:
                        # Recalculate dates if sequence_length or either date bound is inconsistent
                        expected_seq_end = target_date - timedelta(days=LEAD_TIME)
                        expected_seq_start = expected_seq_end - timedelta(days=station_seq_length - 1)
                        if (seq.sequence_length != station_seq_length or
                                seq.sequence_end_date != expected_seq_end or
                                seq.sequence_start_date != expected_seq_start):
                            seq.sequence_length = station_seq_length
                            seq.lead_time_days = LEAD_TIME
                            seq.calculate_sequence_dates()
                            seq.save()
                        logger.info(f"ForecastSequence already exists for {target_date}")
                    # Validate data completeness
                    seq.validate_data_availability()
                    seq.save()
                    if not seq.is_ready_for_prediction:
                        logger.warning(f"Sequence not ready for prediction: {target_date}")
                        target_date += timedelta(days=1)
                        continue
                    # Prepare input sequence and normalize
                    input_sequence = engine.era5_downloader.preprocess_for_model_inference(
                        station, seq.sequence_start_date, seq.sequence_end_date, training_scaler_path=scaler_path
                    )
                    logger.debug(f"Raw input sequence for {target_date} (first row): {input_sequence[0] if hasattr(input_sequence, '__getitem__') else input_sequence}")
                    if input_sequence.shape != (station_seq_length, engine.n_features):
                        logger.error(f"Input shape mismatch for {target_date}: {input_sequence.shape}")
                        target_date += timedelta(days=1)
                        continue
                    X = input_sequence.reshape(1, station_seq_length, engine.n_features)
                    original_shape = X.shape
                    X_2d = X.reshape(-1, X.shape[-1])
                    X_scaled_2d = engine.normalization_scaler.transform(X_2d)
                    X_scaled = X_scaled_2d.reshape(original_shape)
                    # Print or log the full normalized sequence for inspection
                    print(f"\n=== Normalized input sequence for prediction on {target_date} (sequence {seq.sequence_start_date} to {seq.sequence_end_date}) ===")
                    print(X_scaled[0])
                    logger.debug(f"Normalized input sequence for {target_date} (first row): {X_scaled[0,0] if hasattr(X_scaled, '__getitem__') else X_scaled}")
                    # Make prediction and update or create in DB
                    logger.debug(f"Loading normalization scaler from: {station.scaler_file_path}")
                    logger.debug(f"Loading model from: {station.model_file_path}")
                    if engine.normalization_scaler is not None:
                        logger.debug(f"Normalization scaler loaded: {type(engine.normalization_scaler)}")
                    else:
                        logger.warning("Normalization scaler is None!")
                    if engine.model is not None:
                        logger.debug(f"Model loaded: {type(engine.model)}")
                    else:
                        logger.warning("Model is None!")
                    # Use engine's prediction method
                    # Handle model output: (pred, (lower, upper), success)
                    result = engine.predict_single_day(station, target_date)
                    if isinstance(result, tuple) and len(result) == 3 and isinstance(result[1], tuple):
                        pred, bounds, success = result
                        lower, upper = bounds
                        conf = None
                    else:
                        logger.error(f"Unexpected prediction output format for {target_date}: {result}")
                        success = False
                    logger.debug(f"Prediction output for {target_date}: {result}")
                    if success:
                        logger.info(f"Prediction complete for {target_date}: {pred:.2f} m³/s")
                        try:
                            obj, created = DischargePrediction.objects.update_or_create(
                                station=station,
                                target_date=target_date,
                                model_name=engine.model_name if hasattr(engine, 'model_name') else 'unknown',
                                defaults={
                                    'predicted_discharge': pred,
                                    'prediction_confidence': conf,
                                    'confidence_lower': lower,
                                    'confidence_upper': upper,
                                    'sequence_length': station_seq_length,
                                    'forecast_type': 'daily',
                                    'processing_status': 'completed',
                                }
                            )
                            if created:
                                logger.info(f"Saved new prediction for {station.name} on {target_date}")
                            else:
                                logger.info(f"Updated existing prediction for {station.name} on {target_date}")
                        except Exception as e:
                            logger.error(f"Prediction save/update failed for {station.name} on {target_date}: {e}")
                            logger.error(f"Prediction failed for {target_date}")
                    else:
                        logger.error(f"Prediction failed for {target_date}")
            except Exception as e:
                logger.error(f"Error for {target_date}: {e}")
            target_date += timedelta(days=1)

if __name__ == "__main__":
    main()
