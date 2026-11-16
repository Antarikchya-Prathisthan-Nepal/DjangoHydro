from django.contrib.auth.mixins import UserPassesTestMixin, LoginRequiredMixin
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from .models import DischargeStation


class StationAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin to check if a user has access to a specific station.
    Redirects to login page if not authenticated.
    Shows an access denied message if authenticated but not authorized.
    """
    
    def get_station(self):
        """Get the station from URL parameters or request data"""
        # Default implementation - override in child classes as needed
        if hasattr(self, 'kwargs') and 'station_id' in self.kwargs:
            return DischargeStation.objects.filter(station_id=self.kwargs['station_id']).first()
        return None
    
    def test_func(self):
        """Test if the user has access to the station"""
        user = self.request.user
        
        # Superusers and staff can access any station
        if user.is_superuser or user.is_staff:
            return True
            
        # Get the station
        station = self.get_station()
        if not station:
            return False
            
        # Check if user has access to this station
        return station.user_accesses.filter(user=user).exists()
    
    def handle_no_permission(self):
        """Handle when user doesn't have permission"""
        if not self.request.user.is_authenticated:
            # User is not logged in, redirect to login page
            return super().handle_no_permission()
        
        # User is logged in but doesn't have access to this station
        messages.error(self.request, 'Access denied: You do not have permission to access this station.')
        
        # Redirect to the my stations page
        return redirect(reverse('my_stations'))


class AnyStationAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Mixin to check if a user has access to any station.
    If not, redirects them to a page explaining they need to request access.
    """
    
    def test_func(self):
        """Test if the user has access to any station"""
        user = self.request.user
        
        # Superusers and staff can access any station
        if user.is_superuser or user.is_staff:
            return True
            
        # Check if user has access to any station
        return user.station_accesses.exists()
    
    def handle_no_permission(self):
        """Handle when user doesn't have permission"""
        if not self.request.user.is_authenticated:
            # User is not logged in, redirect to login page
            return super().handle_no_permission()
        
        # User is logged in but doesn't have access to any stations
        messages.warning(
            self.request, 
            'You don\'t have access to any discharge stations yet. '
            'Please contact the administrator to request access.'
        )
        
        # Redirect to profile page
        return redirect(reverse('profile'))
