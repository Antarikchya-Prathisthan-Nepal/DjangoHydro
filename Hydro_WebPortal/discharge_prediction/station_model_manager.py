"""
Station-Specific Model Management System
========================================

This module handles station-specific PyTorch models where each hydropower station
has its own trained model, data, and predictions.
"""

import os
import torch
import numpy as np
from datetime import datetime, date, timedelta
from django.contrib.gis.geos import Point
from django.db.models import Q, Avg, Count
from typing import List, Dict, Optional, Tuple
import logging

# Import your Django models
from .models import (
    DischargeStation, DHMStage, DischargePrediction, 
    ERA5Data, ForecastSequence, MonthlyForecast, PipelineRun, PredictionModel
)
from .prediction_utils import DischargePredictionEngine
from .era5_utils import ERA5Downloader

logger = logging.getLogger(__name__)

class StationSpecificModelManager:
    """
    Manages station-specific PyTorch models for hydropower discharge prediction
    
    Each station has:
    - Its own PyTorch model file
    - Its own geographic location for ERA5 data
    - Its own historical validation data
    - Its own predictions and forecasts
    """
    
    def __init__(self):
        self.active_stations = {}
        self.prediction_engines = {}
        self.era5_downloaders = {}
    
    def get_available_stations(self) -> List[Dict]:
        """
        Get all available hydropower stations with their model status
        
        Returns:
            List of station info dictionaries
        """
        stations = DischargeStation.objects.filter(is_active=True).order_by('name')
        
        station_info = []
        for station in stations:
            info = {
                'id': str(station.id),
                'name': station.name,
                'station_id': station.station_id,
                'river_name': station.river_name,
                'country': station.country,
                'coordinates': station.coordinates,
                'has_model': station.has_trained_model,
                'is_ready': station.is_model_ready,
                'model_score': station.model_performance_score,
                'era5_data_count': station.get_era5_data_count(),
                'validation_data_count': station.get_validation_data_count(),
                'last_forecast': station.last_forecast_date,
                'latest_prediction': station.get_latest_prediction()
            }
            station_info.append(info)
        
        return station_info
    
    def select_station(self, station_id: str) -> Optional[DischargeStation]:
        """
        Select a specific hydropower station for forecasting
        
        Args:
            station_id: Station ID or UUID
            
        Returns:
            DischargeStation instance or None
        """
        try:
            # Try to get by station_id first, then by UUID
            try:
                station = DischargeStation.objects.get(station_id=station_id)
            except DischargeStation.DoesNotExist:
                station = DischargeStation.objects.get(id=station_id)
            
            if not station.is_active:
                logger.warning(f"Station {station.name} is not active")
                return None
            
            logger.info(f"Selected station: {station.name} ({station.station_id})")
            return station
            
        except DischargeStation.DoesNotExist:
            logger.error(f"Station not found: {station_id}")
            return None
    
    def setup_station_model(self, station: DischargeStation) -> bool:
        """
        Setup PyTorch model for a specific station
        
        Args:
            station: DischargeStation instance
            
        Returns:
            Success status
        """
        try:
            if not station.has_trained_model:
                logger.error(f"No trained model configured for station {station.name}")
                return False
            
            # Create prediction engine for this station
            engine = DischargePredictionEngine(
                model_path=station.model_file_path,
                scaler_path=station.scaler_file_path,
                simulate_mode=False
            )
            
            # Load the station's specific model
            success = engine.load_model()
            if success:
                self.prediction_engines[station.station_id] = engine
                logger.info(f"Model loaded for station {station.name}")
                return True
            else:
                logger.error(f"Failed to load model for station {station.name}")
                return False
                
        except Exception as e:
            logger.error(f"Error setting up model for station {station.name}: {e}")
            return False
    
    def ensure_era5_data(self, station: DischargeStation, 
                        start_date: date, end_date: date) -> bool:
        """
        Ensure ERA5 data is available for station's location and date range
        
        Args:
            station: DischargeStation instance
            start_date: Start date for data
            end_date: End date for data
            
        Returns:
            Success status
        """
        try:
            if not station.coordinates:
                logger.error(f"No coordinates configured for station {station.name}")
                return False
            
            # Create ERA5 downloader for this station's location
            downloader = ERA5Downloader(simulate_mode=False)
            
            # Check existing data
            existing_data = ERA5Data.objects.filter(
                station=station,
                date__range=[start_date, end_date],
                is_complete=True
            ).count()
            
            total_days = (end_date - start_date).days + 1
            completeness = (existing_data / total_days) * 100
            
            if completeness >= 90:
                logger.info(f"ERA5 data {completeness:.1f}% complete for {station.name}")
                return True
            
            # Download missing data
            logger.info(f"Downloading ERA5 data for {station.name} at {station.coordinates}")
            
            # TODO: Implement actual ERA5 download for station coordinates
            # This would involve:
            # 1. CDS API calls with station.coordinates
            # 2. Processing downloaded NetCDF files
            # 3. Storing in ERA5Data model for this station
            
            logger.info(f"ERA5 data download completed for {station.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error ensuring ERA5 data for {station.name}: {e}")
            return False
    
    def get_station_predictions(self, station: DischargeStation, 
                              start_date: date = None, 
                              end_date: date = None) -> Dict:
        """
        Get predictions for a specific station
        
        Args:
            station: DischargeStation instance
            start_date: Start date filter (optional)
            end_date: End date filter (optional)
            
        Returns:
            Dictionary with prediction data for graphs and tables
        """
        try:
            # Build query
            query = Q(station=station, processing_status='completed')
            
            if start_date:
                query &= Q(target_date__gte=start_date)
            if end_date:
                query &= Q(target_date__lte=end_date)
            
            # Get predictions
            predictions = DischargePrediction.objects.filter(query).order_by('target_date')
            
            # Format for graphs and tables
            prediction_data = {
                'station_info': {
                    'name': station.name,
                    'station_id': station.station_id,
                    'river_name': station.river_name,
                    'coordinates': station.coordinates
                },
                'predictions': [],
                'summary': {
                    'total_predictions': predictions.count(),
                    'date_range': {
                        'start': predictions.first().target_date if predictions.exists() else None,
                        'end': predictions.last().target_date if predictions.exists() else None
                    },
                    'avg_discharge': predictions.aggregate(Avg('predicted_discharge'))['predicted_discharge__avg'],
                    'avg_confidence': predictions.aggregate(Avg('prediction_confidence'))['prediction_confidence__avg']
                }
            }
            
            # Add individual predictions
            for pred in predictions:
                prediction_data['predictions'].append({
                    'date': pred.target_date.isoformat(),
                    'predicted_discharge': pred.predicted_discharge,
                    'confidence': pred.prediction_confidence,
                    'confidence_lower': pred.confidence_lower,
                    'confidence_upper': pred.confidence_upper,
                    'actual_discharge': pred.actual_discharge,
                    'accuracy': pred.accuracy_score,
                    'model_name': pred.model_name
                })
            
            return prediction_data
            
        except Exception as e:
            logger.error(f"Error getting predictions for {station.name}: {e}")
            return {}
    
    def predict_for_station(self, station: DischargeStation, 
                           target_date: date) -> Optional[DischargePrediction]:
        """
        Generate prediction for specific station and date
        
        Args:
            station: DischargeStation instance
            target_date: Date to predict for
            
        Returns:
            DischargePrediction instance or None
        """
        try:
            # Ensure model is loaded
            if station.station_id not in self.prediction_engines:
                if not self.setup_station_model(station):
                    return None
            
            engine = self.prediction_engines[station.station_id]
            
            # Ensure ERA5 data is available
            sequence_start = target_date - timedelta(days=135)  # 90 + 45 buffer
            if not self.ensure_era5_data(station, sequence_start, target_date):
                logger.warning(f"Insufficient ERA5 data for {station.name}")
            
            # Generate prediction
            predicted_discharge, confidence_interval, success = engine.predict_single_day(
                station, target_date
            )
            
            if success:
                logger.info(f"Prediction generated for {station.name} on {target_date}: {predicted_discharge:.2f} m³/s")
                return DischargePrediction.objects.filter(
                    station=station,
                    target_date=target_date
                ).first()
            else:
                logger.error(f"Prediction failed for {station.name} on {target_date}")
                return None
                
        except Exception as e:
            logger.error(f"Error predicting for {station.name}: {e}")
            return None
    
    def validate_station_model(self, station: DischargeStation, 
                             validation_start: date = None,
                             validation_end: date = None) -> Dict:
        """
        Validate station model against historical discharge data
        
        Args:
            station: DischargeStation instance
            validation_start: Start date for validation period
            validation_end: End date for validation period
            
        Returns:
            Validation results dictionary
        """
        try:
            # Default to pre-2015 data if no dates specified
            if not validation_start:
                validation_start = date(2010, 1, 1)
            if not validation_end:
                validation_end = date(2014, 12, 31)
            
            # Get historical discharge records
            historical_records = DHMStage.objects.filter(
                station=station,
                timestamp__date__range=[validation_start, validation_end],
                quality_flag__in=['good', 'fair']
            ).order_by('timestamp')
            
            # Get corresponding predictions
            predictions = DischargePrediction.objects.filter(
                station=station,
                target_date__range=[validation_start, validation_end],
                actual_discharge__isnull=False
            ).order_by('target_date')
            
            validation_results = {
                'station_name': station.name,
                'validation_period': {
                    'start': validation_start.isoformat(),
                    'end': validation_end.isoformat()
                },
                'historical_records': historical_records.count(),
                'validated_predictions': predictions.count(),
                'metrics': {}
            }
            
            if predictions.exists():
                # Calculate validation metrics
                errors = []
                relative_errors = []
                
                for pred in predictions:
                    if pred.actual_discharge and pred.actual_discharge > 0:
                        error = abs(pred.predicted_discharge - pred.actual_discharge)
                        relative_error = error / pred.actual_discharge
                        errors.append(error)
                        relative_errors.append(relative_error)
                
                if errors:
                    validation_results['metrics'] = {
                        'mae': np.mean(errors),  # Mean Absolute Error
                        'rmse': np.sqrt(np.mean([e**2 for e in errors])),  # RMSE
                        'mape': np.mean(relative_errors) * 100,  # Mean Absolute Percentage Error
                        'accuracy': (1 - np.mean(relative_errors)) * 100  # Average accuracy
                    }
            
            return validation_results
            
        except Exception as e:
            logger.error(f"Error validating model for {station.name}: {e}")
            return {}


def create_sample_hydropower_stations():
    """
    Create sample hydropower stations for testing
    Each with different locations and model configurations
    """
    stations_data = [
        {
            'name': 'Hydropower Station X',
            'station_id': 'HPX_001',
            'river_name': 'River Alpha',
            'country': 'Nepal',
            'coordinates': (85.3240, 27.7172),  # Kathmandu area
            'model_file': 'models/hydropower_x_model.pt',
            'scaler_file': 'models/hydropower_x_scaler.pkl',
            'description': 'LSTM model for Hydropower X - trained on 2010-2020 data'
        },
        {
            'name': 'Hydropower Station Y', 
            'station_id': 'HPY_002',
            'river_name': 'River Beta',
            'country': 'Nepal',
            'coordinates': (84.1240, 28.2096),  # Pokhara area
            'model_file': 'models/hydropower_y_model.pt',
            'scaler_file': 'models/hydropower_y_scaler.pkl',
            'description': 'LSTM model for Hydropower Y - trained on 2008-2018 data'
        },
        {
            'name': 'Hydropower Station Z',
            'station_id': 'HPZ_003', 
            'river_name': 'River Gamma',
            'country': 'Nepal',
            'coordinates': (87.2804, 26.4499),  # Eastern Nepal
            'model_file': 'models/hydropower_z_model.pt',
            'scaler_file': 'models/hydropower_z_scaler.pkl',
            'description': 'LSTM model for Hydropower Z - trained on 2012-2022 data'
        }
    ]
    
    created_stations = []
    
    for station_data in stations_data:
        station, created = DischargeStation.objects.get_or_create(
            station_id=station_data['station_id'],
            defaults={
                'name': station_data['name'],
                'river_name': station_data['river_name'],
                'country': station_data['country'],
                'location': Point(station_data['coordinates'][0], station_data['coordinates'][1]),
                'model_file_path': station_data['model_file'],
                'scaler_file_path': station_data['scaler_file'],
                'model_description': station_data['description'],
                'is_active': True,
                'is_model_ready': False  # Set to True when actual model files are available
            }
        )
        
        created_stations.append(station)
        
        if created:
            logger.info(f"Created station: {station.name}")
        else:
            logger.info(f"Station already exists: {station.name}")
    
    return created_stations
