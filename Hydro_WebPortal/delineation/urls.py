from django.urls import path
from . import views

app_name = 'delineation'  # Define app_name for namespace

urlpatterns = [
    path('', views.index, name='index'),
    path('debug/', views.debug_page, name='debug_page'),
    path('api/delineate/', views.delineate_watershed, name='delineate_watershed'),
    path('api/rivers/', views.rivers_geojson, name='rivers_geojson'),
    path('api/download_geojson/<str:watershed_id>/', views.download_geojson, name='download_geojson'),
    path('api/recent_watersheds/', views.recent_watersheds, name='recent_watersheds'),
]