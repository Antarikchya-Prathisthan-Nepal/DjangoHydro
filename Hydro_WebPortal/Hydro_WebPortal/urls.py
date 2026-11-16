from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic.base import RedirectView
from . import views

urlpatterns = [
    # Add favicon.ico at root level
    path('favicon.ico', RedirectView.as_view(url=settings.STATIC_URL + 'images/APN-logo.png', permanent=True)),
    path('admin/', admin.site.urls),
    path('', views.home, name='home'),
    path('delineation/', include('delineation.urls', namespace='delineation')),
    path('discharge-prediction/', include('discharge_prediction.urls', namespace='discharge_prediction')),
    path('users/', include('users.urls', namespace='users')),  # Include the users app URLs
    path('watershed-report/', include('watershed_report.urls', namespace='watershed_report')),
]

# Serve static and media files in development
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Custom error handlers
handler404 = 'delineation.views.handler404'
handler500 = 'delineation.views.handler500'