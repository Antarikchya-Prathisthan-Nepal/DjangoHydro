"""
API Permissions
==============

Functions for checking API permissions in the discharge prediction app
"""

from functools import wraps
from django.http import JsonResponse


def station_api_access_required(view_func):
    """
    Decorator to check if the user has access to the station in API views.
    Must be used after login_required.
    """
    @wraps(view_func)
    def wrapper(request, station_id, *args, **kwargs):
        # Already checked if user is authenticated
        user = request.user
        
        # Superusers and staff have access to all stations
        if user.is_superuser or user.is_staff:
            return view_func(request, station_id, *args, **kwargs)
        
        # Check if the station exists
        from .models import DischargeStation
        try:
            # Try to get station by station_id first, then by UUID
            try:
                station = DischargeStation.objects.get(station_id=station_id)
            except DischargeStation.DoesNotExist:
                station = DischargeStation.objects.get(id=station_id)
        except DischargeStation.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Station not found',
                'message': f'Station with ID {station_id} does not exist'
            }, status=404)
            
        # Check if user has access to this station
        if not station.user_accesses.filter(user=user).exists():
            return JsonResponse({
                'success': False,
                'error': 'Access denied',
                'message': 'You do not have permission to access this station'
            }, status=403)
            
        # User has access, proceed with the view
        return view_func(request, station_id, *args, **kwargs)
        
    return wrapper
