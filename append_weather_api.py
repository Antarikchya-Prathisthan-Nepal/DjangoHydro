

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
