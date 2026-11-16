"""
Simple Django JSON API Views with Access Control
===============================================

API endpoints for station selection with authentication and permission checks
"""

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from functools import wraps
from .api_permissions import station_api_access_required

# API authentication decorator
def api_login_required(view_func):
    """Custom login_required decorator for API views that returns JSON response"""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({
                'success': False, 
                'error': 'Authentication required',
                'message': 'You must be logged in to access this resource'
            }, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper
from datetime import date, timedelta, datetime
import json
import logging
import random
import math

from .models import DischargeStation, ERA5Data, DischargePrediction

logger = logging.getLogger(__name__)

@api_login_required
@require_http_methods(["GET"])
def simple_list_stations(request):
    """
    GET /api/stations/
    
    Returns list of all available hydropower stations that the user has access to
    """
    try:
        user = request.user
        
        # If superuser or staff, get all stations
        if user.is_superuser or user.is_staff:
            stations = DischargeStation.objects.filter(is_active=True).order_by('name')
        else:
            # Get only stations the user has access to
            stations = DischargeStation.objects.filter(
                is_active=True, 
                user_accesses__user=user
            ).order_by('name')
        
        station_list = []
        for station in stations:
            # Get basic station info
            era5_count = ERA5Data.objects.filter(station=station).count()
            prediction_count = DischargePrediction.objects.filter(station=station).count()
            latest_prediction = DischargePrediction.objects.filter(station=station).order_by('-created_at').first()
            
            station_info = {
                'id': str(station.id),
                'name': station.name,
                'station_id': station.station_id,
                'river_name': station.river_name,
                'country': station.country,
                'coordinates': [station.location.y, station.location.x] if station.location else None,
                'elevation': station.elevation,
                'catchment_area': station.catchment_area,
                'is_model_ready': station.is_model_ready,
                'has_model': station.is_model_ready,  # Frontend expects 'has_model'
                'era5_data_count': era5_count,
                'prediction_count': prediction_count,
                'latest_prediction': {
                    'date': latest_prediction.target_date.isoformat() if latest_prediction else None,
                    'discharge': latest_prediction.predicted_discharge if latest_prediction else None,
                    'confidence': latest_prediction.prediction_confidence if latest_prediction else None
                } if latest_prediction else None,
                'status': 'active' if station.is_active else 'inactive'
            }
            station_list.append(station_info)
        
        return JsonResponse({
            'success': True,
            'stations': station_list,
            'count': len(station_list)
        })
        
    except Exception as e:
        logger.error(f"Error in simple_list_stations: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Failed to load stations'
        }, status=500)

@api_login_required
@station_api_access_required
@require_http_methods(["GET"])
def simple_station_details(request, station_id):
    """
    Get detailed information about a specific station
    Requires the user to have access to this station
    """
    try:
        # Try to get station by station_id first, then by UUID
        try:
            station = DischargeStation.objects.get(station_id=station_id)
        except DischargeStation.DoesNotExist:
            station = DischargeStation.objects.get(id=station_id)
        
        # Get ERA5 data info
        era5_data = ERA5Data.objects.filter(station=station)
        era5_count = era5_data.count()
        era5_complete = era5_data.filter(is_complete=True).count()
        
        # Get recent predictions
        recent_predictions = DischargePrediction.objects.filter(
            station=station
        ).order_by('-created_at')[:10]
        
        predictions_data = []
        for pred in recent_predictions:
            predictions_data.append({
                'id': str(pred.id),
                'target_date': pred.target_date.isoformat(),
                'predicted_discharge': pred.predicted_discharge,
                'confidence': pred.prediction_confidence,
                'model_name': pred.model_name,
                'status': pred.processing_status,
                'created_at': pred.created_at.isoformat()
            })
        
        # Get data date range
        latest_era5 = era5_data.order_by('-date').first()
        earliest_era5 = era5_data.order_by('date').first()
        
        station_details = {
            'id': str(station.id),
            'name': station.name,
            'station_id': station.station_id,
            'river_name': station.river_name,
            'country': station.country,
            'operator': station.operator,
            'coordinates': [station.location.y, station.location.x] if station.location else None,
            'elevation': station.elevation,
            'catchment_area': station.catchment_area,
            'is_active': station.is_active,
            'is_model_ready': station.is_model_ready,
            'model_file_path': station.model_file_path,
            'model_description': station.model_description,
            'model_performance_score': station.model_performance_score,
            'era5_data': {
                'total_records': era5_count,
                'complete_records': era5_complete,
                'latest_date': latest_era5.date.isoformat() if latest_era5 else None,
                'earliest_date': earliest_era5.date.isoformat() if earliest_era5 else None,
                'completeness_rate': (era5_complete / era5_count * 100) if era5_count > 0 else 0
            },
            'recent_predictions': predictions_data,
            'prediction_count': len(predictions_data)
        }
        
        return JsonResponse({
            'success': True,
            'station': station_details
        })
        
    except DischargeStation.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Station not found',
            'message': f'Station with ID {station_id} does not exist'
        }, status=404)
        
    except Exception as e:
        logger.error(f"Error in simple_station_details: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Failed to load station details'
        }, status=500)

@csrf_exempt
@api_login_required
@station_api_access_required
@require_http_methods(["POST"])
def simple_generate_prediction(request, station_id):
    """
    Generate a new prediction for a station
    Requires the user to have access to this station
    """
    try:
        # Parse request data
        data = json.loads(request.body) if request.body else {}
        target_date = data.get('target_date')
        
        # If no target date provided, use proper 45-day lead time default
        if not target_date:
            from datetime import datetime, timedelta
            # Use 45-day lead time: prediction for 45 days from now
            prediction_date = datetime.now().date() + timedelta(days=45)
            target_date = prediction_date.isoformat()
        
        # Get station
        try:
            station = DischargeStation.objects.get(station_id=station_id)
        except DischargeStation.DoesNotExist:
            station = DischargeStation.objects.get(id=station_id)
        
        # Import and use the prediction system
        from datetime import datetime
        import random
        
        target_date_obj = datetime.strptime(target_date, '%Y-%m-%d').date()
        
        # For demo purposes, generate a simulated prediction
        # In production, this would use the actual prediction engine
        base_discharge = 5.0  # Base discharge in m³/s
        variation = random.uniform(-2.0, 3.0)  # Random variation
        predicted_discharge = max(0.1, base_discharge + variation)  # Ensure positive
        confidence_score = random.uniform(0.75, 0.95)  # Random confidence 75-95%
        
        # Check if prediction already exists for this station and date
        from .models import DischargePrediction
        existing_prediction = DischargePrediction.objects.filter(
            station=station,
            target_date=target_date_obj
        ).first()
        
        if existing_prediction:
            # Update existing prediction with new values
            existing_prediction.predicted_discharge = predicted_discharge
            existing_prediction.prediction_confidence = confidence_score
            existing_prediction.model_name = 'demo_model_v1'
            existing_prediction.processing_status = 'completed'
            existing_prediction.save()
            prediction = existing_prediction
            is_new = False
        else:
            # Create new prediction record
            prediction = DischargePrediction.objects.create(
                station=station,
                target_date=target_date_obj,
                predicted_discharge=predicted_discharge,
                prediction_confidence=confidence_score,
                model_name='demo_model_v1',
                processing_status='completed'
            )
            is_new = True
        
        return JsonResponse({
            'success': True,
            'is_new': is_new,
            'prediction': {
                'id': str(prediction.id),
                'target_date': target_date,
                'predicted_discharge': predicted_discharge,
                'confidence_lower': predicted_discharge * 0.85,
                'confidence_upper': predicted_discharge * 1.15,
                'confidence_score': confidence_score,
                'model_name': 'demo_model_v1',
                'status': 'completed'
            }
        })
            
    except Exception as e:
        logger.error(f"Error in simple_generate_prediction: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Failed to generate prediction'
        }, status=500)


@api_login_required
@station_api_access_required
@require_http_methods(["GET"])
def api_station_telemetry_data(request, station_id):
    """
    GET /api/stations/{station_id}/telemetry/
    
    Returns telemetry data for dashboard chart and observations table
    Requires the user to have access to this station
    
    Optional query parameters:
    - predictions_only: if 'true', returns only prediction data
    - days: number of days to include (default 90)
    """
    try:
        # Get station
        try:
            station = DischargeStation.objects.get(station_id=station_id)
        except DischargeStation.DoesNotExist:
            station = DischargeStation.objects.get(id=station_id)
        
        # Get query parameters
        predictions_only = request.GET.get('predictions_only', 'false').lower() == 'true'
        days = int(request.GET.get('days', 90))
        from .models import DischargePrediction
        from django.utils import timezone
        now = timezone.now()
        start_date_param = request.GET.get('start_date')
        end_date_param = request.GET.get('end_date')
        if start_date_param and end_date_param:
            try:
                start_date = parse_date(start_date_param)
                end_date = parse_date(end_date_param)
            except Exception:
                start_date = (now - timedelta(days=days)).date()
                end_date = (now + timedelta(days=30)).date()
        elif predictions_only:
            start_date = (now - timedelta(days=30)).date()
            end_date = (now + timedelta(days=60)).date()
        else:
            start_date = (now - timedelta(days=days)).date()
            end_date = (now + timedelta(days=30)).date()
        
        # Only get predictions from real models (exclude test/demo models)
        predictions_qs = DischargePrediction.objects.filter(
            station=station,
            target_date__gte=start_date,
            target_date__lte=end_date
        ).exclude(
            model_name__icontains='test'
        ).exclude(
            model_name__icontains='demo'
        ).exclude(
            model_name='discharge_model_90day'  # Exclude demo model
        ).order_by('target_date')
        
        prediction_data = []
        historical_data = []
        
        if predictions_qs.exists():
            # Use real prediction data from your actual GRU model
            logger.info(f"Serving {predictions_qs.count()} REAL MODEL predictions for station {station.name}")
            for pred in predictions_qs:
                data_point = {
                    'date': pred.target_date.isoformat(),
                    'discharge': round(float(pred.predicted_discharge), 3),
                    'energy': round(float(getattr(pred, 'predicted_energy', 0)), 3),
                    'is_prediction': pred.target_date >= now.date(),
                    'confidence': round(float(pred.prediction_confidence or 0.90), 3),
                    'model_name': pred.model_name or 'unknown_model'
                }
                if pred.target_date >= now.date():
                    prediction_data.append(data_point)
                else:
                    historical_data.append(data_point)
            
            logger.info(f"Real model data: {len(prediction_data)} predictions, {len(historical_data)} historical")
        else:
            # No real predictions available - this should not happen after cleanup
            logger.warning(f"No real model predictions found for station {station.name} in date range {start_date} to {end_date}")
            prediction_data = []
            historical_data = []
        
        # Return data based on request type
        if predictions_only:
            # Combine historical and prediction data when predictions_only=true to show all data
            all_predictions = historical_data + prediction_data
            all_predictions.sort(key=lambda x: x['date'])  # Sort by date
            return JsonResponse({
                'success': True,
                'station': {
                    'id': station.station_id,
                    'name': station.name,
                    'river': station.river_name,
                    'coordinates': [station.location.y, station.location.x] if station.location else None,
                },
                'telemetry_data': {
                    'predictions': all_predictions,
                    'date_range': {
                        'start': start_date.isoformat(),
                        'end': end_date.isoformat()
                    }
                }
            })
        else:
            return JsonResponse({
                'success': True,
                'station': {
                    'id': station.station_id,
                    'name': station.name,
                    'river': station.river_name,
                    'coordinates': [station.location.y, station.location.x] if station.location else None,
                },
                'telemetry_data': {
                    'historical': historical_data,
                    'predictions': prediction_data,
                    'date_range': {
                        'start': start_date.isoformat(),
                        'end': end_date.isoformat()
                    }
                }
            })
        
    except Exception as e:
        logger.error(f"Error in api_station_telemetry_data: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Failed to load telemetry data'
        }, status=500)


@api_login_required
@station_api_access_required
@require_http_methods(["GET"])
def api_station_observations(request, station_id):
    """
    GET /api/stations/{station_id}/observations/
    
    Returns observation data for the observations table
    Requires the user to have access to this station
    """
    try:
        # Get station
        try:
            station = DischargeStation.objects.get(station_id=station_id)
        except DischargeStation.DoesNotExist:
            station = DischargeStation.objects.get(id=station_id)
        
        # Get query parameters
        observation_date = request.GET.get('date', date.today().isoformat())
        period = request.GET.get('period', 'point')
        
        # Parse the date
        target_date = datetime.strptime(observation_date, '%Y-%m-%d').date()
        
        # Generate sample observations based on period
        observations = []
        
        if period == 'point':
            # Generate hourly data for the selected date
            for hour in range(0, 24, 2):  # Every 2 hours
                minute = random.choice([0, 10, 20, 30, 40, 50])
                time_str = f"{hour:02d}:{minute:02d}"
                
                # Generate realistic discharge value
                base_value = 5.0
                hour_variation = 0.3 * math.sin((hour / 24.0) * 2 * math.pi)
                noise = random.uniform(-0.2, 0.2)
                discharge_value = max(0.1, base_value + hour_variation + noise)
                
                observations.append({
                    'datetime': f"{target_date.strftime('%a, %b %d, %Y')}, {time_str}",
                    'value': round(discharge_value, 2)
                })
        
        elif period == 'daily':
            # Generate daily data for the week around the selected date
            for i in range(-3, 4):  # 7 days around target date
                current_date = target_date + timedelta(days=i)
                base_value = 5.0
                daily_variation = 0.5 * math.sin((i / 7.0) * 2 * math.pi)
                noise = random.uniform(-0.3, 0.3)
                discharge_value = max(0.1, base_value + daily_variation + noise)
                
                observations.append({
                    'datetime': current_date.strftime('%a, %b %d, %Y'),
                    'value': round(discharge_value, 2)
                })
        
        elif period == 'weekly':
            # Generate weekly data for the month around the selected date
            for i in range(-2, 3):  # 5 weeks around target date
                week_start = target_date + timedelta(weeks=i)
                base_value = 5.0
                weekly_variation = 0.8 * math.sin((i / 4.0) * 2 * math.pi)
                noise = random.uniform(-0.4, 0.4)
                discharge_value = max(0.1, base_value + weekly_variation + noise)
                
                observations.append({
                    'datetime': f"Week of {week_start.strftime('%b %d, %Y')}",
                    'value': round(discharge_value, 2)
                })
        
        elif period == 'monthly':
            # Generate monthly data for the year around the selected date
            for i in range(-6, 7):  # 13 months around target date
                if target_date.month + i > 12:
                    month_date = target_date.replace(year=target_date.year + 1, month=(target_date.month + i) - 12)
                elif target_date.month + i < 1:
                    month_date = target_date.replace(year=target_date.year - 1, month=12 + (target_date.month + i))
                else:
                    month_date = target_date.replace(month=target_date.month + i)
                
                base_value = 5.0
                seasonal_variation = 1.2 * math.sin((i / 12.0) * 2 * math.pi)
                noise = random.uniform(-0.5, 0.5)
                discharge_value = max(0.1, base_value + seasonal_variation + noise)
                
                observations.append({
                    'datetime': month_date.strftime('%B %Y'),
                    'value': round(discharge_value, 2)
                })
        
        return JsonResponse({
            'success': True,
            'station': {
                'id': station.station_id,
                'name': station.name
            },
            'observations': observations,
            'query': {
                'date': observation_date,
                'period': period
            }
        })
        
    except Exception as e:
        logger.error(f"Error in api_station_observations: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e),
            'message': 'Failed to load observations'
        }, status=500)


@api_login_required
@station_api_access_required
@require_http_methods(["GET"])
def api_energy_calculator(request, station_id):
    """
    GET /api/stations/{station_id}/energy-calculator/
        ?start_date=YYYY-MM-DD
        &end_date=YYYY-MM-DD
        &net_head=<float>          (optional, overrides station default)
        &operating_hours=<float>   (optional, default 24 — duty cycle hours/day)

    Calculates energy for the requested period by:
      1. Fetching DischargePrediction.predicted_discharge for each day in range
      2. Capping each day: discharge_for_energy = min(q, max_discharge_for_energy)
      3. Computing per-day energy = (η × 1000 × 9.81 × q_capped × H / 1e6) × operating_hours
      4. Summing all daily energies → total
    """
    try:
        try:
            station = DischargeStation.objects.get(station_id=station_id)
        except DischargeStation.DoesNotExist:
            station = DischargeStation.objects.get(id=station_id)

        # ── Parse query parameters ────────────────────────────────────────
        start_str = request.GET.get('start_date', '').strip()
        end_str   = request.GET.get('end_date', '').strip()

        if not start_str or not end_str:
            return JsonResponse({
                'success': False,
                'error': 'start_date and end_date are required (YYYY-MM-DD)'
            }, status=400)

        start_date = parse_date(start_str)
        end_date   = parse_date(end_str)

        if not start_date or not end_date:
            return JsonResponse({
                'success': False,
                'error': 'Invalid date format. Use YYYY-MM-DD.'
            }, status=400)

        if start_date > end_date:
            return JsonResponse({
                'success': False,
                'error': 'start_date must be before or equal to end_date'
            }, status=400)

        # operating_hours: 0 < h ≤ 24, default 24
        try:
            operating_hours = float(request.GET.get('operating_hours', 24))
            if not (0 < operating_hours <= 24):
                raise ValueError()
        except (ValueError, TypeError):
            return JsonResponse({
                'success': False,
                'error': 'operating_hours must be a number between 0 (exclusive) and 24'
            }, status=400)

        # net_head override (optional)
        net_head_override = request.GET.get('net_head', '').strip()
        if net_head_override:
            try:
                net_head_override = float(net_head_override)
                if net_head_override <= 0:
                    raise ValueError()
            except (ValueError, TypeError):
                return JsonResponse({
                    'success': False,
                    'error': 'net_head must be a positive number'
                }, status=400)
        else:
            net_head_override = None

        # ── Station hydropower parameters ─────────────────────────────────
        efficiency  = station.efficiency or 0.8827
        net_head    = net_head_override if net_head_override is not None else (station.net_head or 115.5)
        max_q       = station.max_discharge_for_energy or 29.75
        rho, g      = 1000, 9.81

        # ── Fetch daily discharge predictions for the range ───────────────
        from .models import DischargePrediction
        predictions = (
            DischargePrediction.objects
            .filter(station=station, target_date__range=[start_date, end_date])
            .order_by('target_date')
            .values('target_date', 'predicted_discharge')
        )

        if not predictions:
            return JsonResponse({
                'success': True,
                'station_id': station_id,
                'station_name': station.name,
                'has_data': False,
                'message': 'No discharge predictions found for the selected date range.'
            })

        # ── Per-day calculation ───────────────────────────────────────────
        daily_results = []
        total_energy  = 0.0
        discharge_values = []

        for p in predictions:
            q_raw    = p['predicted_discharge']
            q_capped = min(q_raw, max_q)
            power_mw = (efficiency * rho * g * q_capped * net_head) / 1e6
            energy   = power_mw * operating_hours
            total_energy += energy
            discharge_values.append(q_raw)
            daily_results.append({
                'date':              p['target_date'].strftime('%Y-%m-%d'),
                'discharge_m3s':     round(q_raw, 4),
                'capped_discharge':  round(q_capped, 4),
                'was_capped':        q_raw > max_q,
                'power_mw':          round(power_mw, 4),
                'energy_mwh':        round(energy, 4),
            })

        days_count    = len(daily_results)
        avg_discharge = sum(discharge_values) / days_count
        avg_power_mw  = (efficiency * rho * g * min(avg_discharge, max_q) * net_head) / 1e6
        days_capped   = sum(1 for d in daily_results if d['was_capped'])

        return JsonResponse({
            'success':      True,
            'has_data':     True,
            'station_id':   station_id,
            'station_name': station.name,
            'parameters': {
                'efficiency':             efficiency,
                'net_head_m':             net_head,
                'max_discharge_m3s':      max_q,
                'operating_hours_per_day': operating_hours,
                'net_head_source':        'override' if net_head_override is not None else 'station',
            },
            'period': {
                'start_date':  start_str,
                'end_date':    end_str,
                'days_requested': (end_date - start_date).days + 1,
                'days_with_data': days_count,
                'days_capped':    days_capped,
            },
            'results': {
                'avg_discharge_m3s': round(avg_discharge, 4),
                'avg_power_mw':      round(avg_power_mw, 4),
                'total_energy_mwh':  round(total_energy, 2),
                'avg_daily_energy_mwh': round(total_energy / days_count, 4),
            },
            'daily_breakdown': daily_results,
        })

    except DischargeStation.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Station {station_id} not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error in api_energy_calculator for station {station_id}: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@api_login_required
@station_api_access_required
@require_http_methods(['GET'])
def api_weather_summary(request, station_id):
    """
    GET /api/stations/<station_id>/weather-summary/

    Returns the latest DHM meteorological observations for all DHM meteo
    stations linked to this hydropower station.
    """
    from .models import DHMMeteoStation, DHMMeteoRecord
    from datetime import date

    try:
        station = DischargeStation.objects.get(station_id=station_id)
    except DischargeStation.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Station not found'}, status=404)

    def _compass(deg):
        if deg is None:
            return None
        directions = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                      'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']
        idx = round(deg / 22.5) % 16
        return directions[idx]

    today = date.today()
    weather_entries = []

    meteo_stations = DHMMeteoStation.objects.filter(
        hydro_stations=station
    ).order_by('variable_type', 'name')

    for ms in meteo_stations:
        latest = ms.records.order_by('-timestamp').first()
        if latest is None:
            weather_entries.append({
                'dhm_station':   ms.name,
                'variable_type': ms.variable_type,
                'as_of':         None,
                'data_age_days': None,
                'is_stale':      True,
                'has_data':      False,
            })
            continue

        rec_date = latest.timestamp.date()
        age_days = (today - rec_date).days

        entry = {
            'dhm_station':       ms.name,
            'variable_type':     ms.variable_type,
            'as_of':             str(rec_date),
            'data_age_days':     age_days,
            'is_stale':          age_days > 2,
            'has_data':          True,
            # Rainfall
            'rainfall_mm':       latest.rainfall_mm,
            # Temperature
            'temp_avg_c':        latest.temp_avg_c,
            'temp_min_c':        latest.temp_min_c,
            'temp_max_c':        latest.temp_max_c,
            # Humidity
            'rh_avg':            latest.rh_avg,
            # Wind speed
            'wind_speed_avg_ms': latest.wind_speed_avg_ms,
            'wind_speed_max_ms': latest.wind_speed_max_ms,
            # Wind direction
            'wind_dir_avg_deg':  latest.wind_dir_avg_deg,
            'wind_dir_compass':  _compass(latest.wind_dir_avg_deg),
        }
        weather_entries.append(entry)

    return JsonResponse({
        'success':      True,
        'station_id':   station_id,
        'station_name': station.name,
        'weather':      weather_entries,
    })
