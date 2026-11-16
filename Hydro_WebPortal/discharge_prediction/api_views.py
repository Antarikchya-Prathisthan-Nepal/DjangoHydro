"""
Station-Specific Model API Views
================================

API endpoints for selecting hydropower stations and getting their data:
- GET /api/stations/ - List all available stations
- GET /api/stations/{id}/ - Get specific station details
- POST /api/stations/{id}/predict/ - Generate new prediction
- GET /api/stations/{id}/predictions/ - Get station predictions
- GET /api/stations/{id}/validation/ - Get model validation results
"""

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from datetime import date, timedelta
import logging

from .models import DischargeStation
from .station_model_manager import StationSpecificModelManager

logger = logging.getLogger(__name__)
manager = StationSpecificModelManager()

@api_view(['GET'])
def list_stations(request):
    """
    GET /api/stations/
    
    Returns list of all available hydropower stations
    """
    try:
        stations = manager.get_available_stations()
        return Response({
            'success': True,
            'stations': stations,
            'count': len(stations)
        })
    except Exception as e:
        logger.error(f"Error listing stations: {e}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_station_details(request, station_id):
    """
    GET /api/stations/{station_id}/
    
    Returns detailed information about a specific station
    """
    try:
        station = manager.select_station(station_id)
        if not station:
            return Response({
                'success': False,
                'error': 'Station not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Get recent predictions for preview
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        
        prediction_data = manager.get_station_predictions(station, start_date, end_date)
        
        station_details = {
            'id': str(station.id),
            'name': station.name,
            'station_id': station.station_id,
            'river_name': station.river_name,
            'country': station.country,
            'coordinates': station.coordinates,
            'elevation': station.elevation,
            'catchment_area': station.catchment_area,
            'has_model': station.has_trained_model,
            'is_ready': station.is_model_ready,
            'model_description': station.model_description,
            'model_score': station.model_performance_score,
            'last_forecast': station.last_forecast_date.isoformat() if station.last_forecast_date else None,
            'data_counts': {
                'era5_data': station.get_era5_data_count(),
                'validation_data': station.get_validation_data_count()
            },
            'recent_predictions': prediction_data
        }
        
        return Response({
            'success': True,
            'station': station_details
        })
        
    except Exception as e:
        logger.error(f"Error getting station details: {e}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
def generate_prediction(request, station_id):
    """
    POST /api/stations/{station_id}/predict/
    
    Generate new prediction for the station
    
    Body:
    {
        "target_date": "2025-09-15"  # Optional, defaults to 45 days from now
    }
    """
    try:
        station = manager.select_station(station_id)
        if not station:
            return Response({
                'success': False,
                'error': 'Station not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Parse target date
        target_date_str = request.data.get('target_date')
        if target_date_str:
            target_date = parse_date(target_date_str)
            if not target_date:
                return Response({
                    'success': False,
                    'error': 'Invalid date format. Use YYYY-MM-DD'
                }, status=status.HTTP_400_BAD_REQUEST)
        else:
            target_date = date.today() + timedelta(days=45)
        
        # Generate prediction
        prediction = manager.predict_for_station(station, target_date)
        
        if prediction:
            return Response({
                'success': True,
                'prediction': {
                    'station_name': station.name,
                    'target_date': prediction.target_date.isoformat(),
                    'predicted_discharge': prediction.predicted_discharge,
                    'confidence': prediction.prediction_confidence,
                    'confidence_lower': prediction.confidence_lower,
                    'confidence_upper': prediction.confidence_upper,
                    'model_name': prediction.model_name,
                    'processing_status': prediction.processing_status
                }
            })
        else:
            return Response({
                'success': False,
                'error': 'Prediction generation failed'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        logger.error(f"Error generating prediction: {e}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_station_predictions(request, station_id):
    """
    GET /api/stations/{station_id}/predictions/
    
    Get predictions for a station with filtering options
    
    Query parameters:
    - start_date: Start date (YYYY-MM-DD)
    - end_date: End date (YYYY-MM-DD)
    - limit: Number of predictions to return
    """
    try:
        station = manager.select_station(station_id)
        if not station:
            return Response({
                'success': False,
                'error': 'Station not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Parse query parameters
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        
        start_date = parse_date(start_date_str) if start_date_str else None
        end_date = parse_date(end_date_str) if end_date_str else None
        
        # Default to last 3 months if no dates specified
        if not start_date and not end_date:
            end_date = date.today()
            start_date = end_date - timedelta(days=90)
        
        prediction_data = manager.get_station_predictions(station, start_date, end_date)
        
        # Format for frontend consumption
        return Response({
            'success': True,
            'data': {
                'station_info': prediction_data.get('station_info', {}),
                'predictions': prediction_data.get('predictions', []),
                'summary': prediction_data.get('summary', {}),
                'graph_data': {
                    'dates': [p['date'] for p in prediction_data.get('predictions', [])],
                    'predicted_discharge': [p['predicted_discharge'] for p in prediction_data.get('predictions', [])],
                    'confidence_lower': [p['confidence_lower'] for p in prediction_data.get('predictions', [])],
                    'confidence_upper': [p['confidence_upper'] for p in prediction_data.get('predictions', [])],
                    'actual_discharge': [p['actual_discharge'] for p in prediction_data.get('predictions', []) if p['actual_discharge']]
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting predictions: {e}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_station_validation(request, station_id):
    """
    GET /api/stations/{station_id}/validation/
    
    Get model validation results for the station
    """
    try:
        station = manager.select_station(station_id)
        if not station:
            return Response({
                'success': False,
                'error': 'Station not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        validation_results = manager.validate_station_model(station)
        
        return Response({
            'success': True,
            'validation': validation_results
        })
        
    except Exception as e:
        logger.error(f"Error getting validation results: {e}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
def get_station_monthly_forecast(request, station_id):
    """
    GET /api/stations/{id}/monthly-forecast/?page=1&limit=3

    Returns paginated monthly energy forecast data for a specific station
    """
    try:
        from .models import MonthlyForecast
        import math

        station = get_object_or_404(DischargeStation, station_id=station_id)

        # Pagination params
        try:
            page = max(1, int(request.GET.get('page', 1)))
        except (ValueError, TypeError):
            page = 1
        try:
            limit = max(1, int(request.GET.get('limit', 3)))
        except (ValueError, TypeError):
            limit = 3

        # Base queryset — only completed records with energy data
        qs = MonthlyForecast.objects.filter(
            station=station,
            processing_status='completed',
            total_energy_mwh__isnull=False
        ).order_by('-target_year', '-target_month')

        total_records = qs.count()
        total_pages = max(1, math.ceil(total_records / limit))
        page = min(page, total_pages)
        offset = (page - 1) * limit

        monthly_forecasts = qs[offset:offset + limit]

        month_names = [
            '', 'January', 'February', 'March', 'April', 'May', 'June',
            'July', 'August', 'September', 'October', 'November', 'December'
        ]

        forecast_data = []
        for forecast in monthly_forecasts:
            forecast_data.append({
                'id': forecast.id,
                'year': forecast.target_year,
                'month': forecast.target_month,
                'month_name': month_names[forecast.target_month],
                'station_name': station.name,
                'predictions_count': forecast.total_daily_forecasts,
                'average_discharge': float(forecast.mean_discharge) if forecast.mean_discharge else None,
                'monthly_energy': float(forecast.total_energy_mwh) if forecast.total_energy_mwh else None,
                'daily_energy': float(forecast.mean_energy_mwh) if forecast.mean_energy_mwh else None,
                'calculation_method': 'average_monthly_discharge',
                'status': 'completed',
                'created_at': forecast.created_at.isoformat() if forecast.created_at else None,
                'updated_at': forecast.updated_at.isoformat() if forecast.updated_at else None,
            })

        return Response({
            'success': True,
            'station_id': station_id,
            'station_name': station.name,
            'monthly_forecasts': forecast_data,
            'total_records': total_records,
            'total_pages': total_pages,
            'current_page': page,
            'has_previous': page > 1,
            'has_next': page < total_pages,
            'count': len(forecast_data),
        })

    except Exception as e:
        logger.error(f"Error getting monthly forecast for station {station_id}: {e}")
        return Response({
            'success': False,
            'error': str(e)
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

