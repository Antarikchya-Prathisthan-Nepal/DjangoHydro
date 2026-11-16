from django.urls import path
from . import views
from . import api_views
from . import simple_api_views
from .dhm_webhook import dhm_fetch_trigger
from .gst_views import gst_receive

app_name = 'discharge_prediction'

urlpatterns = [
    # Main telemetry dashboard - displays daily discharge predictions with dynamic station selection
    path('', views.dashboard_telemetry_view, name='dashboard'),
    
    # Real-time predictions-only dashboard with auto-refresh
    path('predictions/', views.predictions_dashboard_view, name='predictions_dashboard'),
    
    # API endpoints for telemetry dashboard
    path('api/stations/', simple_api_views.simple_list_stations, name='simple_api_list_stations'),
    path('api/stations/<str:station_id>/', simple_api_views.simple_station_details, name='simple_api_station_details'),
    path('api/stations/<str:station_id>/telemetry/', simple_api_views.api_station_telemetry_data, name='api_station_telemetry'),
    path('api/stations/<str:station_id>/observations/', simple_api_views.api_station_observations, name='api_station_observations'),
    path('api/stations/<str:station_id>/energy-calculator/', simple_api_views.api_energy_calculator, name='api_energy_calculator'),
    path('api/stations/<str:station_id>/weather-summary/', simple_api_views.api_weather_summary, name='api_weather_summary'),
    path('api/stations/<str:station_id>/monthly-forecast/', api_views.get_station_monthly_forecast, name='api_station_monthly_forecast'),
    
    # Keep essential prediction API for potential future use
    path('api/stations/<str:station_id>/predict/', simple_api_views.simple_generate_prediction, name='simple_api_generate_prediction'),

    # DHM webhook — called by GitHub Actions daily_fetch.yml
    path('api/dhm/trigger/', dhm_fetch_trigger, name='dhm_fetch_trigger'),

    # GST (Ground Station Telemetry) receiver — field device POSTs data here
    # Both with and without trailing slash to handle devices that omit it
    path('api/gst/receive/', gst_receive, name='gst_receive'),
    path('api/gst/receive', gst_receive, name='gst_receive_noslash'),
]
