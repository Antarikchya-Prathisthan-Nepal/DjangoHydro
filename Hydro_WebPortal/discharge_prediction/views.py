from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Avg, Max, Min, Count
from django.core.paginator import Paginator
from django.urls import reverse
from django.contrib import messages
from datetime import date, timedelta
from .models import (
    DischargeStation, DischargePrediction, MonthlyForecast, 
    ERA5Data, PipelineRun, DHMStage
)
from .prediction_utils import DischargePredictionEngine, ForecastScheduler
from .plotting_utils import ForecastPlotter
import json
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from functools import wraps

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


def station_selector_view(request):
    """
    Main view for the station selector interface.
    """
    return render(request, 'discharge_prediction/station_selector.html')

from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from django.shortcuts import redirect
from .access_control import StationAccessMixin, AnyStationAccessMixin

@login_required
def dashboard_telemetry_view(request):
    """
    Enhanced telemetry dashboard view with real-time predictions,
    glassmorphism effects, and auto-refresh functionality.
    Requires login and station access.
    """
    # Check if a specific station is requested
    station_id = request.GET.get('station')
    user = request.user
    
    # If superuser or staff, allow access to any station
    if user.is_superuser or user.is_staff:
        return render(request, 'discharge_prediction/dashboard_enhanced.html')

    # Free-tier users cannot access this module at all
    if user.account_tier == 'free':
        stations = DischargeStation.objects.filter(is_active=True).order_by('name')
        return render(request, 'discharge_prediction/access_denied.html',
                      {'reason': 'free_tier', 'stations': stations}, status=403)

    # Full-tier: check if any station access has been assigned yet
    if not station_id:
        if not user.station_accesses.exists():
            stations = DischargeStation.objects.filter(is_active=True).order_by('name')
            return render(request, 'discharge_prediction/access_denied.html',
                          {'reason': 'no_station', 'stations': stations}, status=403)
        # If user has only one station, redirect to that station
        if user.station_accesses.count() == 1:
            station = user.station_accesses.first().station
            return redirect(f"{reverse('discharge_prediction:dashboard')}?station={station.station_id}")
        return render(request, 'discharge_prediction/dashboard_enhanced.html')

    # Specific station requested — check access
    station = DischargeStation.objects.filter(station_id=station_id).first()
    if not station:
        return render(request, 'discharge_prediction/access_denied.html',
                      {'reason': 'no_station'}, status=403)

    if not station.user_accesses.filter(user=user).exists():
        return render(request, 'discharge_prediction/access_denied.html',
                      {'reason': 'no_station'}, status=403)

    return render(request, 'discharge_prediction/dashboard_enhanced.html')

def predictions_dashboard_view(request):
    """
    Real-time predictions-only dashboard with auto-refresh.
    Shows only predicted discharge values with daily updates.
    """
    return render(request, 'discharge_prediction/predictions_dashboard.html')

def dashboard(request):
    """Main dashboard view for discharge predictions"""
    # Get all active stations
    stations = DischargeStation.objects.filter(is_active=True)
    
    # Get recent forecasts
    recent_forecasts = MonthlyForecast.objects.select_related('station', 'model_used').order_by('-created_at')[:10]
    
    # Get recent pipeline runs
    recent_runs = PipelineRun.objects.order_by('-scheduled_time')[:10]
    
    # Summary statistics
    total_stations = stations.count()
    total_predictions = DischargePrediction.objects.count()
    completed_forecasts = MonthlyForecast.objects.filter(status='completed').count()
    
    # Current month forecast status
    current_month = date.today().replace(day=1)
    current_month_forecasts = MonthlyForecast.objects.filter(
        forecast_month=current_month
    ).select_related('station')
    
    context = {
        'stations': stations,
        'recent_forecasts': recent_forecasts,
        'recent_runs': recent_runs,
        'total_stations': total_stations,
        'total_predictions': total_predictions,
        'completed_forecasts': completed_forecasts,
        'current_month_forecasts': current_month_forecasts,
        'current_month': current_month,
    }
    
    return render(request, 'discharge_prediction/dashboard.html', context)

def station_detail(request, station_id):
    """Detailed view for a specific station"""
    station = get_object_or_404(DischargeStation, station_id=station_id)
    
    # Get recent predictions
    recent_predictions = DischargePrediction.objects.filter(
        station=station
    ).order_by('-forecast_timestamp')[:30]
    
    # Get monthly forecasts
    monthly_forecasts = MonthlyForecast.objects.filter(
        station=station
    ).order_by('-forecast_month')[:12]
    
    # Get recent ERA5 data
    recent_era5 = ERA5Data.objects.filter(
        station=station
    ).order_by('-date')[:30]
    
    # Performance statistics
    validated_predictions = DischargePrediction.objects.filter(
        station=station,
        actual_discharge__isnull=False
    )
    
    accuracy_stats = None
    if validated_predictions.exists():
        accuracy_stats = {
            'count': validated_predictions.count(),
            'avg_accuracy': validated_predictions.aggregate(Avg('accuracy_score'))['accuracy_score__avg'],
            'min_accuracy': validated_predictions.aggregate(Min('accuracy_score'))['accuracy_score__min'],
            'max_accuracy': validated_predictions.aggregate(Max('accuracy_score'))['accuracy_score__max'],
        }
    
    context = {
        'station': station,
        'recent_predictions': recent_predictions,
        'monthly_forecasts': monthly_forecasts,
        'recent_era5': recent_era5,
        'accuracy_stats': accuracy_stats,
    }
    
    return render(request, 'discharge_prediction/station_detail.html', context)

def forecast_detail(request, forecast_id):
    """Detailed view for a monthly forecast"""
    forecast = get_object_or_404(MonthlyForecast, id=forecast_id)
    
    # Get all predictions for this forecast
    predictions = DischargePrediction.objects.filter(
        station=forecast.station,
        forecast_timestamp__year=forecast.forecast_year,
        forecast_timestamp__month=forecast.forecast_month_number
    ).order_by('forecast_timestamp')
    
    # Prepare chart data
    chart_data = {
        'dates': [p.forecast_timestamp.strftime('%Y-%m-%d') for p in predictions],
        'predicted_discharge': [float(p.predicted_discharge) for p in predictions],
        'confidence_lower': [float(p.confidence_interval_lower or 0) for p in predictions],
        'confidence_upper': [float(p.confidence_interval_upper or 0) for p in predictions],
    }
    
    # Get actual data if available
    actual_records = DHMStage.objects.filter(
        station=forecast.station,
        timestamp__year=forecast.forecast_year,
        timestamp__month=forecast.forecast_month_number
    ).order_by('timestamp')
    
    if actual_records.exists():
        station = forecast.station
        chart_data['actual_dates'] = [r.timestamp.strftime('%Y-%m-%d') for r in actual_records]
        chart_data['actual_discharge'] = [
            float(station.compute_discharge_from_stage(r.stage_height))
            if r.stage_height is not None else None
            for r in actual_records
        ]
    
    context = {
        'forecast': forecast,
        'predictions': predictions,
        'chart_data': json.dumps(chart_data),
        'actual_records': actual_records,
    }
    
    return render(request, 'discharge_prediction/forecast_detail.html', context)

@csrf_exempt
@api_login_required
def api_station_predictions(request, station_id):
    """API endpoint for station predictions - requires authentication"""
    # Check station access permission
    user = request.user
    if not (user.is_superuser or user.is_staff):
        station = get_object_or_404(DischargeStation, station_id=station_id)
        if not station.user_accesses.filter(user=user).exists():
            return JsonResponse({
                'success': False,
                'error': 'Access denied',
                'message': 'You do not have permission to access this station'
            }, status=403)
    station = get_object_or_404(DischargeStation, station_id=station_id)
    
    # Get date range from query parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    
    if start_date and end_date:
        predictions = DischargePrediction.objects.filter(
            station=station,
            forecast_timestamp__date__range=[start_date, end_date]
        ).order_by('forecast_timestamp')
    else:
        # Default to last 30 days
        end_date = date.today()
        start_date = end_date - timedelta(days=30)
        predictions = DischargePrediction.objects.filter(
            station=station,
            forecast_timestamp__date__range=[start_date, end_date]
        ).order_by('forecast_timestamp')
    
    data = []
    for prediction in predictions:
        data.append({
            'date': prediction.forecast_timestamp.strftime('%Y-%m-%d'),
            'predicted_discharge': float(prediction.predicted_discharge),
            'confidence_lower': float(prediction.confidence_interval_lower or 0),
            'confidence_upper': float(prediction.confidence_interval_upper or 0),
            'actual_discharge': float(prediction.actual_discharge) if prediction.actual_discharge else None,
            'accuracy_score': float(prediction.accuracy_score) if prediction.accuracy_score else None,
        })
    
    return JsonResponse({
        'station': {
            'id': station.station_id,
            'name': station.name,
            'river': station.river_name,
        },
        'predictions': data,
        'count': len(data),
        'date_range': {
            'start': start_date.isoformat() if isinstance(start_date, date) else start_date,
            'end': end_date.isoformat() if isinstance(end_date, date) else end_date,
        }
    })

@login_required
def generate_forecast(request):
    """View to manually trigger forecast generation"""
    if request.method == 'POST':
        station_id = request.POST.get('station_id')
        target_month = request.POST.get('target_month')  # YYYY-MM format
        
        try:
            station = DischargeStation.objects.get(station_id=station_id)
            year, month = map(int, target_month.split('-'))
            target_date = date(year, month, 1)
            
            # Generate forecast
            prediction_engine = DischargePredictionEngine()
            forecast = prediction_engine.predict_monthly_discharge(station, target_date)
            
            return JsonResponse({
                'status': 'success',
                'message': f'Forecast generated for {station.name}',
                'forecast_id': str(forecast.id),
                'forecast_status': forecast.status,
                'progress': forecast.progress_percentage,
            })
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            })
    
    # GET request - show form
    stations = DischargeStation.objects.filter(is_active=True)
    return render(request, 'discharge_prediction/generate_forecast.html', {'stations': stations})

@login_required
def pipeline_status(request):
    """View to show pipeline run status"""
    runs = PipelineRun.objects.order_by('-scheduled_time')
    
    # Pagination
    paginator = Paginator(runs, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Summary statistics
    total_runs = runs.count()
    successful_runs = runs.filter(status='completed').count()
    failed_runs = runs.filter(status='failed').count()
    
    context = {
        'page_obj': page_obj,
        'total_runs': total_runs,
        'successful_runs': successful_runs,
        'failed_runs': failed_runs,
        'success_rate': (successful_runs / total_runs * 100) if total_runs > 0 else 0,
    }
    
    return render(request, 'discharge_prediction/pipeline_status.html', context)

@api_login_required
def api_pipeline_logs(request, run_id):
    """API endpoint to get pipeline run logs - requires authentication
    Only staff and superusers can access pipeline logs"""
    # Only staff and superusers can access pipeline logs
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({
            'success': False, 
            'error': 'Access denied',
            'message': 'Only staff can access pipeline logs'
        }, status=403)
    run = get_object_or_404(PipelineRun, id=run_id)
    
    return JsonResponse({
        'run_id': str(run.id),
        'run_type': run.run_type,
        'status': run.status,
        'target_date': run.target_date.isoformat(),
        'duration': run.duration_seconds,
        'logs': run.log_messages,
        'output_files': run.output_files,
    })

@login_required
def run_pipeline(request):
    """View to manually trigger pipeline run"""
    if request.method == 'POST':
        run_type = request.POST.get('run_type', 'daily')
        
        try:
            if run_type == 'daily':
                from .management.commands.run_daily_pipeline import Command
                command = Command()
                # This would typically be run asynchronously
                # For demo, we'll just create a placeholder response
                
                return JsonResponse({
                    'status': 'success',
                    'message': 'Daily pipeline started',
                    'run_type': run_type,
                })
            else:
                return JsonResponse({
                    'status': 'error',
                    'message': f'Unknown run type: {run_type}'
                })
                
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'message': str(e)
            })
    
    return render(request, 'discharge_prediction/run_pipeline.html')

def plots_gallery(request):
    """View to display generated forecast plots"""
    stations = DischargeStation.objects.filter(is_active=True)
    
    # Get available plots (this would scan the plots directory)
    # For demo, we'll create placeholder data
    available_plots = []
    
    for station in stations:
        current_month = date.today().replace(day=1)
        available_plots.append({
            'station': station,
            'type': 'monthly_forecast',
            'month': current_month,
            'filename': f"{station.station_id}_{current_month.strftime('%Y_%m')}_forecast.png",
            'title': f"{station.name} - {current_month.strftime('%B %Y')} Forecast"
        })
    
    context = {
        'stations': stations,
        'available_plots': available_plots,
    }
    
    return render(request, 'discharge_prediction/plots_gallery.html', context)

def data_quality(request):
    """View to show data quality metrics"""
    stations = DischargeStation.objects.filter(is_active=True)
    
    data_quality_metrics = []
    
    for station in stations:
        # Check ERA5 data completeness for last 90 days
        end_date = date.today()
        start_date = end_date - timedelta(days=90)
        
        total_days = 90
        available_era5 = ERA5Data.objects.filter(
            station=station,
            date__range=[start_date, end_date],
            is_complete=True
        ).count()
        
        era5_completeness = (available_era5 / total_days) * 100
        
        # Check prediction accuracy for last 30 days
        accuracy_data = DischargePrediction.objects.filter(
            station=station,
            forecast_timestamp__date__range=[end_date - timedelta(days=30), end_date],
            actual_discharge__isnull=False
        )
        
        avg_accuracy = None
        if accuracy_data.exists():
            avg_accuracy = accuracy_data.aggregate(Avg('accuracy_score'))['accuracy_score__avg']
        
        data_quality_metrics.append({
            'station': station,
            'era5_completeness': era5_completeness,
            'prediction_accuracy': avg_accuracy,
            'data_status': 'good' if era5_completeness >= 90 else 'warning' if era5_completeness >= 70 else 'error'
        })
    
    context = {
        'data_quality_metrics': data_quality_metrics,
    }
    
    return render(request, 'discharge_prediction/data_quality.html', context)
