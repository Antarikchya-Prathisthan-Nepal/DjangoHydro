from django.contrib import admin
from django.contrib.gis import admin as gis_admin
from django.shortcuts import render, redirect
from django.urls import path, reverse
from django.http import HttpResponseRedirect, JsonResponse
from django.contrib import messages
from django.utils.html import format_html
from django.db import models
from django import forms
from django.contrib.gis.geos import Point
from datetime import date, timedelta
from django.utils import timezone
import json
import os

from .models import (
    DischargeStation, DHMStage, DischargePrediction,
    PredictionModel, ERA5Data, ForecastSequence, MonthlyForecast, PipelineRun, SensorReading,
    DHMMeteoStation, DHMMeteoRecord,
)


class DischargeStationAdminForm(forms.ModelForm):
    """Custom form for DischargeStation admin to handle coordinate conversion and GeoJSON upload"""

    # Add a file upload field for GeoJSON
    catchment_geojson_file = forms.FileField(
        required=False,
        label='Upload Catchment GeoJSON File',
        help_text='Upload a GeoJSON file containing the catchment area polygon (Polygon or MultiPolygon)',
        widget=forms.FileInput(attrs={'accept': '.geojson,.json'})
    )

    class Meta:
        model = DischargeStation
        fields = '__all__'
        widgets = {
            'catchment_polygon': forms.HiddenInput(),  # Hide the map widget
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make location field optional in the form
        self.fields['location'].required = False

        # Make catchment_polygon optional (will be set via file upload)
        # Check if field exists before accessing it
        if 'catchment_polygon' in self.fields:
            self.fields['catchment_polygon'].required = False

        # Ensure catchment_geojson_file is in self.fields (it should be auto-added from class declaration)
        # This verification helps with debugging
        if 'catchment_geojson_file' not in self.fields:
            # If for some reason it's not there, add it manually
            self.fields['catchment_geojson_file'] = forms.FileField(
                required=False,
                label='Upload Catchment GeoJSON File',
                help_text='Upload a GeoJSON file containing the catchment area polygon (Polygon or MultiPolygon)',
                widget=forms.FileInput(attrs={'accept': '.geojson,.json'})
            )

        # If we have an instance with coordinates, populate lat/lng fields
        if self.instance and self.instance.pk and self.instance.location:
            self.fields['latitude'].initial = self.instance.location.y
            self.fields['longitude'].initial = self.instance.location.x

    def clean(self):
        cleaned_data = super().clean()
        latitude = cleaned_data.get('latitude')
        longitude = cleaned_data.get('longitude')
        location = cleaned_data.get('location')
        catchment_geojson_file = cleaned_data.get('catchment_geojson_file')

        # Handle location point synchronization
        if latitude is not None and longitude is not None and not location:
            try:
                cleaned_data['location'] = Point(longitude, latitude)
            except Exception as e:
                raise forms.ValidationError(f"Invalid coordinates: {e}")
        elif location and (latitude is None or longitude is None):
            cleaned_data['latitude'] = location.y
            cleaned_data['longitude'] = location.x
        elif not location and (latitude is None or longitude is None):
            raise forms.ValidationError("Please provide either map coordinates or latitude/longitude values.")

        # Process GeoJSON file upload
        if catchment_geojson_file:
            try:
                # Read the uploaded file
                file_content = catchment_geojson_file.read()

                # Decode if bytes
                if isinstance(file_content, bytes):
                    file_content = file_content.decode('utf-8')

                # Parse JSON
                geojson_data = json.loads(file_content)

                # Validate it's a valid GeoJSON
                if 'type' not in geojson_data:
                    raise forms.ValidationError("Invalid GeoJSON file: missing 'type' field")

                # Import using the model method
                from django.contrib.gis.geos import GEOSGeometry, MultiPolygon

                # Handle different GeoJSON types
                geom_type = geojson_data.get('type')

                if geom_type == 'FeatureCollection':
                    # Extract geometry from first feature in collection
                    features = geojson_data.get('features', [])
                    if not features:
                        raise forms.ValidationError("FeatureCollection has no features")

                    # Get geometry from first feature
                    geometry_data = features[0].get('geometry')
                    if not geometry_data:
                        raise forms.ValidationError("First feature has no geometry")

                    geom = GEOSGeometry(json.dumps(geometry_data))

                elif geom_type == 'Feature':
                    # Extract geometry from feature
                    geometry_data = geojson_data.get('geometry')
                    if not geometry_data:
                        raise forms.ValidationError("Feature has no geometry")

                    geom = GEOSGeometry(json.dumps(geometry_data))

                elif geom_type in ['Polygon', 'MultiPolygon']:
                    # Direct geometry object
                    geom = GEOSGeometry(json.dumps(geojson_data))

                else:
                    raise forms.ValidationError(
                        f"Unsupported GeoJSON type: {geom_type}. "
                        f"Expected Feature, FeatureCollection, Polygon, or MultiPolygon."
                    )

                # Convert Polygon to MultiPolygon if needed
                if geom.geom_type == 'Polygon':
                    geom = MultiPolygon(geom)
                elif geom.geom_type != 'MultiPolygon':
                    raise forms.ValidationError(
                        f"Invalid geometry type: {geom.geom_type}. "
                        f"Expected Polygon or MultiPolygon."
                    )

                # Set SRID to WGS84
                if geom.srid is None or geom.srid != 4326:
                    geom.srid = 4326

                cleaned_data['catchment_polygon'] = geom

            except json.JSONDecodeError as e:
                raise forms.ValidationError(f"Invalid JSON file: {str(e)}")
            except Exception as e:
                raise forms.ValidationError(f"Error processing GeoJSON file: {str(e)}")

        return cleaned_data

    def save(self, commit=True):
        """Override save to handle catchment_polygon from cleaned_data"""
        instance = super().save(commit=False)

        # Get the processed catchment_polygon from cleaned_data
        if 'catchment_polygon' in self.cleaned_data:
            instance.catchment_polygon = self.cleaned_data['catchment_polygon']

        if commit:
            instance.save()

        return instance


@admin.register(DischargeStation)
class DischargeStationAdmin(gis_admin.GISModelAdmin):
    form = DischargeStationAdminForm
    list_display = [
        'name', 'station_id', 'river_name', 'country', 'elevation',
        'catchment_area_display', 'geojson_status', 'is_active', 'model_status', 'era5_data_count',
        'download_era5_action', 'predict_action'
    ]
    list_filter = ['is_active', 'country', 'operator', 'is_model_ready', 'created_at']
    search_fields = ['name', 'station_id', 'river_name', 'country']
    readonly_fields = ['id', 'created_at', 'updated_at', 'coordinates_display', 'catchment_polygon_display']
    actions = ['download_era5_batch', 'download_90_days_auto', 'configure_models_batch', 'run_predictions_batch']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'station_id', 'river_name', 'operator', 'country')
        }),
        ('Location & Geography', {
            'fields': ('latitude', 'longitude', 'location', 'coordinates_display', 'elevation'),
            'description': 'You can either enter latitude/longitude coordinates directly OR click on the map. '
                          'The system will automatically sync both methods. '
                          '<br><strong>Tip:</strong> Enter coordinates in decimal degrees (e.g., 27.7172 for latitude, 85.3240 for longitude).'
        }),
        ('Catchment Area (GeoJSON)', {
            'fields': ('catchment_area', 'catchment_geojson_file', 'catchment_polygon_display'),
            'description': 'Enter the catchment area in kmÂ² and upload a GeoJSON file (.geojson or .json) containing the catchment area polygon. '
                          'Supported geometry types: Polygon or MultiPolygon (EPSG:4326 / WGS84).'
        }),
        ('Ground Station Sensor (GST)', {
            'fields': ('sensor_api_endpoint', 'gst_depth_api_field'),
            'description': 'Configure the API endpoint URL for fetching real-time sensor data from the ground station. '
                          'Set the JSON key name used for the discharge depth value in the API response (default: <code>water_depth</code>).'
        }),
        ('ERA5 Download Area Configuration', {
            'fields': ('use_auto_area', 'download_area_north', 'download_area_west',
                      'download_area_south', 'download_area_east'),
            'description': 'Configure custom area boundaries for ERA5 data downloads. '
                          'When auto area is disabled, provide custom coordinates (North, West, South, East) '
                          'to define the bounding box for downloading ERA5 data for this station.'
        }),
        ('Rating Curve & CAR Method (Stage Height â Discharge)', {
            'fields': (
                'rating_curve_c', 'rating_curve_a', 'rating_curve_b',
                'reference_catchment_area_km2',
            ),
            'description': (
                'Power-law rating curve for the nearest DHM reference gauging station: '
                '<code>Q1 = c Ã (H â a)<sup>b</sup></code>. '
                'The CAR method then scales Q1 to this station: '
                '<code>Q2 = Q1 Ã (A2 / A1)</code> '
                'where A2 = <em>Catchment Area</em> above and A1 = <em>Reference Catchment Area</em> here. '
                'For the Sangutar reference station: c=62.59397, a=1.85553, b=1.83024, A1=851 kmÂ². '
                'After setting these values, run <code>manage.py set_rating_curve --recompute</code> '
                'to recompute Q2 for all existing records.'
            ),
            'classes': ('collapse',),
        }),
        ('Model Configuration', {
            'fields': ('model_file_path', 'scaler_file_path', 'denormalization_scaler_path', 'model_description',
                      'model_performance_score', 'is_model_ready')
        }),
        ('Hydropower Energy Parameters', {
            'fields': ('net_head', 'efficiency', 'max_discharge_for_energy'),
            'description': 'Configure per-station hydropower energy calculation parameters.\n'
                          'Net head (m), efficiency (0-1), and maximum discharge for energy (mÂ³/s).'
        }),
        ('Status & Monitoring', {
            'fields': ('is_active', 'last_forecast_date')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('download-era5/<uuid:station_id>/',
                 self.admin_site.admin_view(self.download_era5_view),
                 name='discharge_station_download_era5'),
            path('predict/<uuid:station_id>/',
                 self.admin_site.admin_view(self.predict_view),
                 name='discharge_station_predict'),
            path('era5-status/<uuid:station_id>/',
                 self.admin_site.admin_view(self.era5_status_view),
                 name='discharge_station_era5_status'),
            path('download-geojson/<uuid:station_id>/',
                 self.admin_site.admin_view(self.download_geojson_view),
                 name='discharge_station_download_geojson'),
            path('remove-geojson/<uuid:station_id>/',
                 self.admin_site.admin_view(self.remove_geojson_view),
                 name='discharge_station_remove_geojson'),
        ]
        return custom_urls + urls
    
    def coordinates_display(self, obj):
        """Display coordinates in a readable format"""
        if obj.location:
            return f"{obj.location.y:.4f}Â°N, {obj.location.x:.4f}Â°E"
        return "Not set"
    coordinates_display.short_description = "Coordinates"

    def catchment_area_display(self, obj):
        """Display catchment area from admin-provided value"""
        if obj.catchment_area:
            # Format the number first, then pass to format_html
            area_formatted = f"{obj.catchment_area:.2f}"
            return format_html('<span style="color: green;">{} kmÂ²</span>', area_formatted)
        return format_html('<span style="color: gray;">Not provided</span>')
    catchment_area_display.short_description = "Catchment Area"

    def catchment_polygon_display(self, obj):
        """Display catchment polygon status and download button"""
        if not obj.catchment_polygon:
            return format_html('<span style="color: gray;">No GeoJSON file uploaded</span>')

        # Add download button for GeoJSON
        download_url = reverse('admin:discharge_station_download_geojson', args=[obj.pk])

        # Get polygon info
        info = obj.get_catchment_info()

        # Format numbers first to avoid format_html issues
        north = float(info['bounds']['north'])
        south = float(info['bounds']['south'])
        east = float(info['bounds']['east'])
        west = float(info['bounds']['west'])
        lat = float(info['centroid']['latitude'])
        lon = float(info['centroid']['longitude'])

        remove_url = reverse('admin:discharge_station_remove_geojson', args=[obj.pk])

        html_parts = [
            '<span style="color: green;">â GeoJSON file uploaded</span><br>',
            f"<strong>Polygons:</strong> {info['num_polygons']}<br>",
            f"<strong>Bounds:</strong> ",
            f"N: {north:.4f}Â°, ",
            f"S: {south:.4f}Â°, ",
            f"E: {east:.4f}Â°, ",
            f"W: {west:.4f}Â°<br>",
            f"<strong>Centroid:</strong> {lat:.4f}Â°N, {lon:.4f}Â°E<br><br>",
            f'<a class="button" href="{download_url}" style="background-color: #417690; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;">Download GeoJSON</a>',
            f'&nbsp;<a class="button" href="{remove_url}" style="background-color: #ba2121; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;">Remove GeoJSON</a>'
        ]

        return format_html(''.join(html_parts))
    catchment_polygon_display.short_description = "GeoJSON File Status"

    def geojson_status(self, obj):
        """Display GeoJSON file status for list view (concise)"""
        if obj.catchment_polygon:
            info = obj.get_catchment_info()
            return format_html(
                '<span style="color: green;">â Uploaded ({} polygons)</span>',
                info['num_polygons']
            )
        return format_html('<span style="color: gray;">No file</span>')
    geojson_status.short_description = "GeoJSON"

    def area_config_status(self, obj):
        """Display area configuration status"""
        try:
            if obj.use_auto_area:
                return format_html('<span style="color: blue;">ð Auto Area</span>')
            elif obj.has_custom_area():
                area_info = obj.get_area_info()
                size_info = area_info.get('size_degrees', {})
                
                # Safely get dimensions with fallback values
                lon_span = size_info.get('lon_span', 0)
                lat_span = size_info.get('lat_span', 0)
                
                # Convert to float if needed and format safely
                try:
                    lon_span = float(lon_span) if lon_span is not None else 0.0
                    lat_span = float(lat_span) if lat_span is not None else 0.0
                    dimension_text = f"{lon_span:.2f}Â° Ã {lat_span:.2f}Â°"
                except (ValueError, TypeError):
                    dimension_text = "Invalid dimensions"
                
                return format_html(
                    '<span style="color: green;">ð Custom Area</span><br>'
                    '<small>{}</small>',
                    dimension_text
                )
            else:
                return format_html('<span style="color: orange;">â ï¸ No Area Set</span>')
        except Exception as e:
            return format_html('<span style="color: red;">â Error: {}</span>', str(e)[:50])
    area_config_status.short_description = "Download Area"
    
    def model_status(self, obj):
        """Display model readiness status with color"""
        if obj.is_model_ready:
            return format_html('<span style="color: green;">â Ready</span>')
        else:
            return format_html('<span style="color: red;">â Not Configured</span>')
    model_status.short_description = "Model Status"
    
    def era5_data_count(self, obj):
        """Show ERA5 data count with date range"""
        count = ERA5Data.objects.filter(station=obj).count()
        if count > 0:
            latest = ERA5Data.objects.filter(station=obj).order_by('-date').first()
            earliest = ERA5Data.objects.filter(station=obj).order_by('date').first()
            return format_html(
                '<span style="color: blue;">{} records</span><br>'
                '<small>{} to {}</small>',
                count, earliest.date, latest.date
            )
        return format_html('<span style="color: gray;">No data</span>')
    era5_data_count.short_description = "ERA5 Data"
    
    def download_era5_action(self, obj):
        """Add download ERA5 action button"""
        return format_html(
            '<a class="button" href="{}" title="Download historical ERA5 weather data for this station">Download ERA5</a>',
            reverse('admin:discharge_station_download_era5', args=[obj.pk])
        )
    download_era5_action.short_description = "ERA5 Download"
    
    def predict_action(self, obj):
        """Add prediction action button"""
        if obj.is_model_ready:
            return format_html(
                '<a class="button" href="{}" title="Run discharge prediction using trained model">Run Prediction</a>',
                reverse('admin:discharge_station_predict', args=[obj.pk])
            )
        return format_html('<span style="color: gray;" title="Model not configured for this station">Model not ready</span>')
    predict_action.short_description = "Prediction"
    
    def download_era5_view(self, request, station_id):
        """Handle ERA5 download for a specific station using the same logic as the management command."""
        try:
            station = DischargeStation.objects.get(pk=station_id)
        except DischargeStation.DoesNotExist:
            messages.error(request, f"Station with ID {station_id} not found.")
            return redirect('admin:discharge_prediction_dischargestation_changelist')

        if request.method == 'POST':
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            try:
                from datetime import datetime, date, timedelta
                # Parse dates
                start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
                max_date = date.today() - timedelta(days=7)
                if end_date > max_date:
                    messages.error(request, f"End date {end_date} exceeds maximum allowed date {max_date} (ERA5 delay)")
                    return redirect('admin:discharge_prediction_dischargestation_changelist')
                if start_date > end_date:
                    messages.error(request, "Start date must be before end date")
                    return redirect('admin:discharge_prediction_dischargestation_changelist')
                from .era5_utils import ERA5Downloader
                downloader = ERA5Downloader(simulate_mode=False)
                variables = [
                    '2m_temperature', 'total_precipitation',
                    '10m_u_component_of_wind', '10m_v_component_of_wind',
                    'specific_humidity', 'volumetric_soil_water_layer_1'
                ]
                # Download data for the range using download_for_station
                era5_data = downloader.download_for_station(
                    station=station,
                    start_date=start_date,
                    end_date=end_date,
                    variables=variables
                )
                # Store each day's data in the database
                from django.db import transaction
                from discharge_prediction.models import ERA5Data
                for day in (start_date + timedelta(n) for n in range((end_date - start_date).days + 1)):
                    day_str = day.strftime('%Y-%m-%d')
                    if era5_data and day_str in era5_data:
                        day_vars = era5_data[day_str]
                        mapped_data = {
                            '2m_temperature': day_vars.get('temperature_2m', 0.0),
                            'total_precipitation': day_vars.get('total_precipitation', 0.0),
                            '10m_u_component_of_wind': day_vars.get('u_component_10m', 0.0),
                            '10m_v_component_of_wind': day_vars.get('v_component_10m', 0.0),
                            'specific_humidity': day_vars.get('specific_humidity', 0.0),
                            'volumetric_soil_water_layer_1': day_vars.get('soil_moisture') or day_vars.get('swvl1') or 0.0,
                        }
                        with transaction.atomic():
                            ERA5Data.objects.update_or_create(
                                station=station,
                                date=day,
                                defaults={
                                    'temperature_2m': mapped_data.get('2m_temperature', 0.0),
                                    'total_precipitation': mapped_data.get('total_precipitation', 0.0),
                                    'u_component_10m': mapped_data.get('10m_u_component_of_wind', 0.0),
                                    'v_component_10m': mapped_data.get('10m_v_component_of_wind', 0.0),
                                    'specific_humidity': mapped_data.get('specific_humidity', 0.0),
                                    'soil_moisture': mapped_data.get('volumetric_soil_water_layer_1') or None,
                                    'download_timestamp': timezone.now(),
                                    'data_source': 'ERA5_CDS',
                                    'is_complete': True,
                                    'processing_status': 'processed'
                                }
                            )
                messages.success(
                    request,
                    f"Successfully downloaded and stored ERA5 data for {station.name} from {start_date} to {end_date}"
                )
            except Exception as e:
                import traceback
                tb = traceback.format_exc()
                error_msg = (
                    f"Error downloading ERA5 data for station '{station.name}' "
                    f"(ID: {station_id}) from {start_date} to {end_date}: {str(e)}\n"
                    f"Traceback:\n{tb}"
                )
                import logging
                logger = logging.getLogger(__name__)
                logger.error(error_msg)
                messages.error(request, error_msg.replace('\n', '<br>'))
            return redirect('admin:discharge_prediction_dischargestation_changelist')

        from datetime import date, timedelta
        context = {
            'station': station,
            'title': f'Download ERA5 Data for {station.name}',
            'opts': self.model._meta,
            'has_change_permission': True,
            'default_start_date': (date.today() - timedelta(days=120)).strftime('%Y-%m-%d'),
            'default_end_date': (date.today() - timedelta(days=7)).strftime('%Y-%m-%d'),
        }
        return render(request, 'admin/discharge_prediction/download_era5.html', context)
    
    def predict_view(self, request, station_id):
        """Handle prediction for a specific station"""
        try:
            station = DischargeStation.objects.get(pk=station_id)
        except DischargeStation.DoesNotExist:
            messages.error(request, f"Station with ID {station_id} not found.")
            return redirect('admin:discharge_prediction_dischargestation_changelist')
        
        if request.method == 'POST':
            prediction_date = request.POST.get('prediction_date')
            
            try:
                from datetime import datetime
                prediction_date = datetime.strptime(prediction_date, '%Y-%m-%d').date()
                
                # Import and run prediction pipeline
                from .prediction_utils import DischargePredictionEngine
                
                engine = DischargePredictionEngine()
                
                if engine.load_station_model(station):
                    # Calculate sequence dates
                    sequence_end = prediction_date - timedelta(days=45)
                    sequence_start = sequence_end - timedelta(days=89)
                    
                    # Check if we have data
                    era5_count = ERA5Data.objects.filter(
                        station=station,
                        date__range=[sequence_start, sequence_end]
                    ).count()
                    
                    if era5_count < 80:  # At least 80% of 90 days
                        messages.warning(
                            request,
                            f"Insufficient ERA5 data for prediction. "
                            f"Found {era5_count}/90 days. Download more data first."
                        )
                    else:
                        # Run prediction pipeline
                        from .real_time_era5_pipeline import RealTimeERA5Pipeline
                        pipeline = RealTimeERA5Pipeline()
                        
                        results = pipeline.run_complete_pipeline(
                            station.station_id, 
                            prediction_date.strftime('%Y-%m-%d')
                        )
                        
                        if results['success']:
                            messages.success(
                                request,
                                f"Prediction completed for {station.name} on {prediction_date}. "
                                f"Predicted discharge: {results['predicted_discharge']:.2f} mÂ³/s"
                            )
                        else:
                            messages.error(
                                request,
                                f"Prediction failed: {'; '.join(results['errors'])}"
                            )
                else:
                    messages.error(request, f"Could not load model for {station.name}")
                    
            except Exception as e:
                messages.error(request, f"Error running prediction: {str(e)}")
            
            return redirect('admin:discharge_prediction_dischargestation_changelist')
        
        # Show prediction form
        context = {
            'station': station,
            'title': f'Run Prediction for {station.name}',
            'opts': self.model._meta,
            'has_change_permission': True,
            'default_prediction_date': (date.today() + timedelta(days=45)).strftime('%Y-%m-%d'),
        }
        
        return render(request, 'admin/discharge_prediction/run_prediction.html', context)
    
    def era5_status_view(self, request, station_id):
        """Show ERA5 data status for a station"""
        try:
            station = DischargeStation.objects.get(pk=station_id)
        except DischargeStation.DoesNotExist:
            return JsonResponse({'error': 'Station not found'}, status=404)
        
        # Get ERA5 data statistics
        era5_data = ERA5Data.objects.filter(station=station)
        
        if era5_data.exists():
            total_records = era5_data.count()
            latest_date = era5_data.order_by('-date').first().date
            earliest_date = era5_data.order_by('date').first().date
            complete_records = era5_data.filter(is_complete=True).count()
            
            status = {
                'has_data': True,
                'total_records': total_records,
                'latest_date': latest_date.strftime('%Y-%m-%d'),
                'earliest_date': earliest_date.strftime('%Y-%m-%d'),
                'complete_records': complete_records,
                'completion_rate': (complete_records / total_records * 100) if total_records > 0 else 0
            }
        else:
            status = {
                'has_data': False,
                'total_records': 0,
                'latest_date': None,
                'earliest_date': None,
                'complete_records': 0,
                'completion_rate': 0
            }
        
        return JsonResponse(status)

    def download_geojson_view(self, request, station_id):
        """Download catchment area as GeoJSON file"""
        try:
            station = DischargeStation.objects.get(pk=station_id)
        except DischargeStation.DoesNotExist:
            messages.error(request, f"Station with ID {station_id} not found.")
            return redirect('admin:discharge_prediction_dischargestation_changelist')

        # Check if station has catchment polygon
        if not station.catchment_polygon:
            messages.error(request, f"Station '{station.name}' does not have a catchment polygon.")
            return redirect('admin:discharge_prediction_dischargestation_changelist')

        # Get GeoJSON representation
        geojson_data = station.get_catchment_geojson()

        # Create HTTP response with GeoJSON file
        from django.http import HttpResponse
        response = HttpResponse(
            json.dumps(geojson_data, indent=2),
            content_type='application/geo+json'
        )

        # Set filename
        filename = f"{station.station_id}_catchment_area.geojson"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        return response

    def remove_geojson_view(self, request, station_id):
        """Confirm and remove the catchment polygon for a station."""
        try:
            station = DischargeStation.objects.get(pk=station_id)
        except DischargeStation.DoesNotExist:
            messages.error(request, f"Station with ID {station_id} not found.")
            return redirect('admin:discharge_prediction_dischargestation_changelist')

        if not station.catchment_polygon:
            messages.warning(request, f"Station '{station.name}' has no catchment GeoJSON to remove.")
            return redirect(
                reverse('admin:discharge_prediction_dischargestation_change', args=[station_id])
            )

        if request.method == 'POST':
            station.catchment_polygon = None
            station.save(update_fields=['catchment_polygon'])
            messages.success(
                request,
                f"Catchment GeoJSON removed from '{station.name}'. "
                f"You can upload a new file by editing the station."
            )
            return redirect(
                reverse('admin:discharge_prediction_dischargestation_change', args=[station_id])
            )

        # GET â show confirmation page
        context = {
            'station': station,
            'title': f'Remove Catchment GeoJSON â {station.name}',
            'opts': self.model._meta,
            'has_change_permission': True,
        }
        return render(request, 'admin/discharge_prediction/remove_geojson_confirm.html', context)

    # Batch actions
    def download_era5_batch(self, request, queryset):
        """Download ERA5 data for selected stations"""
        count = 0
        for station in queryset:
            if station.is_active:
                # Default date range: last 90 days
                end_date = date.today() - timedelta(days=7)
                start_date = end_date - timedelta(days=90)
                
                try:
                    from .era5_utils import ERA5Downloader
                    downloader = ERA5Downloader(simulate_mode=True)  # Default to simulation
                    
                    if downloader.download_era5_data(station, start_date, end_date):
                        count += 1
                except Exception as e:
                    messages.error(request, f"Failed to download data for {station.name}: {e}")
        
        self.message_user(
            request, 
            f"Successfully initiated ERA5 download for {count} stations."
        )
    download_era5_batch.short_description = "Download ERA5 data (last 90 days)"
    
    def download_90_days_auto(self, request, queryset):
        """Automatically download latest 90 days of ERA5 data for selected stations (same as new station creation)"""
        from django.core.management import call_command
        import threading
        
        count = 0
        for station in queryset:
            try:
                # Use the same logic as automatic downloads for new stations
                end_date = date.today()
                start_date = end_date - timedelta(days=89)  # 90 days total
                
                # Run download in background thread
                def download_task():
                    try:
                        call_command(
                            'download_era5_data',
                            station_name=station.name,
                            start_date=start_date.strftime('%Y-%m-%d'),
                            end_date=end_date.strftime('%Y-%m-%d'),
                            verbosity=1
                        )
                    except Exception as e:
                        pass  # Error handling in the command itself
                
                download_thread = threading.Thread(target=download_task)
                download_thread.daemon = True
                download_thread.start()
                
                count += 1
                
            except Exception as e:
                messages.error(request, f"Failed to initiate download for {station.name}: {e}")
        
        self.message_user(
            request, 
            f"Successfully initiated automatic 90-day ERA5 download for {count} stations. "
            f"Downloads are running in the background."
        )
    download_90_days_auto.short_description = "Download latest 90 days (auto mode - same as new station creation)"
    
    def configure_models_batch(self, request, queryset):
        """Configure models for selected stations"""
        count = 0
        for station in queryset:
            # Check if model files exist
            model_file = 'models/pytorch/lower_lekhu.pt'
            scaler_file = 'models/scalers/Scaler_file.pkl'
            
            if os.path.exists(model_file) and os.path.exists(scaler_file):
                station.model_file_path = model_file
                station.scaler_file_path = scaler_file
                station.is_model_ready = True
                station.save()
                count += 1
        
        self.message_user(
            request,
            f"Successfully configured models for {count} stations."
        )
    configure_models_batch.short_description = "Configure PyTorch models"
    
    def run_predictions_batch(self, request, queryset):
        """Run predictions for selected stations"""
        count = 0
        prediction_date = date.today() + timedelta(days=45)
        
        for station in queryset:
            if station.is_model_ready:
                try:
                    from .real_time_era5_pipeline import RealTimeERA5Pipeline
                    pipeline = RealTimeERA5Pipeline()
                    
                    results = pipeline.run_complete_pipeline(
                        station.station_id,
                        prediction_date.strftime('%Y-%m-%d')
                    )
                    
                    if results['success']:
                        count += 1
                except Exception as e:
                    messages.error(request, f"Prediction failed for {station.name}: {e}")
        
        self.message_user(
            request,
            f"Successfully ran predictions for {count} stations."
        )
    run_predictions_batch.short_description = "Run discharge predictions"


@admin.register(SensorReading)
class SensorReadingAdmin(admin.ModelAdmin):
    """Admin interface for sensor telemetry data"""
    list_display = [
        'station', 'timestamp', 'temperature', 'humidity', 'pressure',
        'water_depth', 'discharge_depth', 'wifi_strength', 'device_status', 'data_quality', 'processing_status'
    ]
    list_filter = [
        'station', 'data_quality', 'processing_status', 'device_status', 
        'is_validated', 'timestamp'
    ]
    search_fields = ['station__name', 'station__station_id', 'device_username', 'device_id', 'ip_address']
    date_hierarchy = 'timestamp'
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['station']
    actions = ['validate_readings', 'mark_as_processed', 'export_to_csv']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('station', 'timestamp', 'record_id')
        }),
        ('Device Information', {
            'fields': ('device_username', 'device_id', 'ip_address', 'wifi_strength', 'device_status'),
            'classes': ('collapse',)
        }),
        ('Environmental Measurements', {
            'fields': ('temperature', 'humidity', 'pressure', 'air_quality'),
            'description': 'Temperature (Â°C), Humidity (%), Pressure (hPa), Air Quality Index'
        }),
        ('Water Measurements', {
            'fields': ('water_depth', 'discharge_depth'),
            'description': 'Water depth in meters or sensor-specific units. '
                          'Discharge depth is populated from the GST API response field configured per station.'
        }),
        ('Location (Optional)', {
            'fields': ('latitude', 'longitude'),
            'classes': ('collapse',),
            'description': 'GPS coordinates if different from station location'
        }),
        ('Data Quality & Processing', {
            'fields': ('data_quality', 'is_validated', 'processing_status', 'notes')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request):
        """Optimize queryset with select_related for better performance"""
        return super().get_queryset(request).select_related('station')
    
    def validate_readings(self, request, queryset):
        """Validate selected sensor readings against ERA5 data"""
        validated_count = 0
        error_count = 0
        
        for reading in queryset:
            try:
                # Run validation against ERA5 data
                validation_results = reading.validate_against_era5()
                
                if validation_results.get('overall_quality') in ['excellent', 'good']:
                    reading.is_validated = True
                    reading.data_quality = validation_results['overall_quality']
                    reading.processing_status = 'processed'
                    reading.save()
                    validated_count += 1
                else:
                    # Mark as needing attention
                    reading.data_quality = 'fair'
                    reading.notes = f"Validation issues: {', '.join(validation_results.get('anomalies', []))}"
                    reading.save()
                    error_count += 1
                    
            except Exception as e:
                error_count += 1
                from django.contrib import messages
                messages.warning(request, f"Validation failed for reading {reading.id}: {str(e)}")
        
        from django.contrib import messages
        self.message_user(
            request,
            f"Validation completed: {validated_count} readings validated successfully, {error_count} with issues."
        )
    validate_readings.short_description = "Validate against ERA5 data"
    
    def mark_as_processed(self, request, queryset):
        """Mark selected readings as processed"""
        updated = queryset.update(processing_status='processed')
        self.message_user(
            request,
            f"Successfully marked {updated} readings as processed."
        )
    mark_as_processed.short_description = "Mark as processed"
    
    def export_to_csv(self, request, queryset):
        """Export selected sensor readings to CSV"""
        import csv
        from django.http import HttpResponse
        from django.utils import timezone
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="sensor_readings_{timezone.now().strftime("%Y%m%d_%H%M")}.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'Station', 'Timestamp', 'Temperature', 'Humidity', 'Pressure',
            'Water Depth', 'Discharge Depth', 'Air Quality', 'WiFi Strength', 'Device Status',
            'Data Quality', 'Latitude', 'Longitude'
        ])

        for reading in queryset:
            writer.writerow([
                reading.station.name,
                reading.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                reading.temperature,
                reading.humidity,
                reading.pressure,
                reading.water_depth,
                reading.discharge_depth,
                reading.air_quality,
                reading.wifi_strength,
                reading.device_status,
                reading.data_quality,
                reading.latitude,
                reading.longitude
            ])
        
        return response
    export_to_csv.short_description = "Export to CSV"


@admin.register(DHMStage)
class DHMStageAdmin(admin.ModelAdmin):
    list_display = [
        'station', 'timestamp',
        'stage_height', 'stage_height_max', 'stage_height_min',
        'discharge_q2',
        'quality_flag', 'data_source',
    ]
    list_filter = ['quality_flag', 'data_source', 'timestamp', 'station']
    search_fields = ['station__name', 'station__station_id']
    date_hierarchy = 'timestamp'
    readonly_fields = ['created_at']
    raw_id_fields = ['station']

    fieldsets = (
        ('Raw Stage Height (DHM input)', {
            'fields': ('station', 'timestamp', 'stage_height', 'stage_height_max', 'stage_height_min'),
            'description': 'Raw stage height H (metres) as received from DHM River Watch. '
                           'These values drive the rating-curve conversion.'
        }),
        ('Derived Discharge (CAR)', {
            'fields': ('discharge_q2',),
            'description': 'Q2 (mÂ³/s) computed via Q1=c*(H-a)^b â Q2=Q1*(A2/A1). '
                           'Auto-populated on save. Used as 7th feature in era5_car pipeline.',
        }),
        ('Quality & Source', {
            'fields': ('quality_flag', 'data_source', 'notes'),
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )

@admin.register(DischargePrediction)
class DischargePredictionAdmin(admin.ModelAdmin):
    list_display = ['station', 'target_date', 'predicted_discharge', 'predicted_energy', 'model_name', 'processing_status', 'created_at']
    list_filter = ['processing_status', 'forecast_type', 'model_name', 'created_at']
    search_fields = ['station__name', 'station__station_id', 'model_name']
    date_hierarchy = 'target_date'
    ordering = ['-target_date']
    readonly_fields = ['id', 'created_at']
    raw_id_fields = ['station']
    
    fieldsets = (
        ('Prediction Info', {
            'fields': ('station', 'target_date', 'predicted_discharge', 'predicted_energy')
        }),
        ('Model & Confidence', {
            'fields': ('model_name', 'sequence_length', 'forecast_type', 'prediction_confidence', 'confidence_lower', 'confidence_upper')
        }),
        ('Processing', {
            'fields': ('processing_status',)
        }),
        ('Validation', {
            'fields': ('actual_discharge', 'accuracy_score')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(PredictionModel)
class PredictionModelAdmin(admin.ModelAdmin):
    list_display = ['name', 'version', 'model_type', 'validation_score', 'is_active', 'created_at']
    list_filter = ['model_type', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Model Information', {
            'fields': ('name', 'version', 'model_type', 'description')
        }),
        ('Configuration', {
            'fields': ('input_features', 'parameters', 'training_period')
        }),
        ('Performance', {
            'fields': ('validation_score', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

# Customize admin site headers
admin.site.site_header = "Hydro Portal - Discharge Prediction Admin"
admin.site.site_title = "Discharge Prediction Admin"
admin.site.index_title = "Discharge Prediction Management"

@admin.register(ERA5Data)
class ERA5DataAdmin(admin.ModelAdmin):
    list_display = [
        'station', 'date', 'temperature_2m', 'total_precipitation',
        'u_component_10m', 'v_component_10m', 'specific_humidity', 'soil_moisture',
        'processing_status', 'is_complete', 'data_source'
    ]
    list_filter = ['processing_status', 'is_complete', 'data_source', 'date', 'station']
    search_fields = ['station__name', 'station__station_id']
    date_hierarchy = 'date'
    readonly_fields = ['download_timestamp', 'created_at']
    raw_id_fields = ['station']

    fieldsets = (
        ('Basic Info', {
            'fields': ('station', 'date', 'data_source')
        }),
        ('Core ERA5 Features (6 Variables for Model)', {
            'fields': (
                'temperature_2m', 'total_precipitation',
                'u_component_10m', 'v_component_10m',
                'specific_humidity', 'soil_moisture'
            ),
            'description': 'These 6 features are used for discharge prediction model input: '
                           't2m, tp, u10, v10, q (925 hPa specific humidity), swvl1 (soil moisture 0â7 cm)'
        }),
        ('Data Quality & Processing', {
            'fields': ('processing_status', 'is_complete', 'download_timestamp', 'created_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(ForecastSequence)
class ForecastSequenceAdmin(admin.ModelAdmin):
    list_display = ['station', 'target_date', 'sequence_start_date', 'sequence_end_date', 'data_completeness', 'is_ready_for_prediction']
    list_filter = ['is_ready_for_prediction', 'lead_time_days', 'era5_delay_days', 'created_at']
    search_fields = ['station__name', 'station__station_id']
    date_hierarchy = 'target_date'
    readonly_fields = ['id', 'created_at', 'updated_at', 'last_processed']
    raw_id_fields = ['station']
    
    fieldsets = (
        ('Target & Station', {
            'fields': ('station', 'target_date')
        }),
        ('Sequence Configuration', {
            'fields': ('sequence_start_date', 'sequence_end_date', 'lead_time_days', 'era5_delay_days', 'sequence_length')
        }),
        ('Data Quality', {
            'fields': ('data_completeness', 'is_ready_for_prediction')
        }),
        ('Metadata', {
            'fields': ('id', 'created_at', 'updated_at', 'last_processed'),
            'classes': ('collapse',)
        }),
    )

@admin.register(MonthlyForecast)
class MonthlyForecastAdmin(admin.ModelAdmin):
    list_display = ['station', 'target_year', 'target_month', 'processing_status', 'mean_discharge', 'total_energy_mwh', 'mean_energy_mwh', 'total_daily_forecasts', 'created_at']
    list_filter = ['processing_status', 'target_year', 'target_month', 'created_at']
    search_fields = ['station__name', 'station__station_id']
    readonly_fields = ['created_at', 'updated_at']
    raw_id_fields = ['station']
    
    fieldsets = (
        ('Forecast Info', {
            'fields': ('station', 'target_year', 'target_month')
        }),
        ('Discharge Statistics', {
            'fields': ('mean_discharge', 'min_discharge', 'max_discharge', 'std_discharge')
        }),
        ('Energy Statistics', {
            'fields': ('total_energy_mwh', 'mean_energy_mwh', 'min_energy_mwh', 'max_energy_mwh', 'std_energy_mwh'),
            'classes': ('wide',)
        }),
        ('Metadata', {
            'fields': ('total_daily_forecasts', 'rolling_window_days', 'prediction_confidence')
        }),
        ('Uncertainty', {
            'fields': ('uncertainty_band_lower', 'uncertainty_band_upper')
        }),
        ('Processing', {
            'fields': ('processing_status', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(PipelineRun)
class PipelineRunAdmin(admin.ModelAdmin):
    list_display = ['run_type', 'station', 'target_date', 'status', 'scheduled_time', 'duration_seconds', 'processed_records', 'error_count']
    list_filter = ['run_type', 'status', 'scheduled_time', 'station']
    search_fields = ['station__name', 'station__station_id']
    date_hierarchy = 'scheduled_time'
    readonly_fields = ['id', 'duration_seconds', 'created_at']
    raw_id_fields = ['station']
    
    fieldsets = (
        ('Run Info', {
            'fields': ('run_type', 'station', 'target_date')
        }),
        ('Status & Timing', {
            'fields': ('status', 'scheduled_time', 'started_at', 'completed_at', 'duration_seconds')
        }),
        ('Results', {
            'fields': ('processed_records', 'error_count', 'output_files')
        }),
        ('Configuration & Logs', {
            'fields': ('parameters', 'log_messages'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('id', 'created_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(DHMMeteoStation)
class DHMMeteoStationAdmin(admin.ModelAdmin):
    list_display = ['name', 'variable_type', 'seriesid', 'humidity_seriesid',
                    'wind_speed_seriesid', 'wind_dir_seriesid', 'created_at']
    list_filter  = ['variable_type']
    search_fields = ['name']
    filter_horizontal = ['hydro_stations']
    readonly_fields = ['created_at']

    fieldsets = (
        ('Station Info', {
            'fields': ('name', 'variable_type', 'hydro_stations'),
        }),
        ('DHM Series IDs', {
            'fields': ('seriesid', 'humidity_seriesid', 'wind_speed_seriesid', 'wind_dir_seriesid'),
            'description': 'seriesid for rainfall/temperature; humidity and wind use surface-observation.',
        }),
        ('Location (optional)', {
            'fields': ('latitude', 'longitude', 'elevation_m'),
            'classes': ('collapse',),
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )


@admin.register(DHMMeteoRecord)
class DHMMeteoRecordAdmin(admin.ModelAdmin):
    list_display = [
        'meteo_station', 'timestamp',
        'rainfall_mm',
        'temp_avg_c', 'rh_avg',
        'wind_speed_avg_ms', 'wind_dir_avg_deg',
        'quality_flag',
    ]
    list_filter  = ['meteo_station', 'quality_flag', 'data_source', 'timestamp']
    search_fields = ['meteo_station__name']
    date_hierarchy = 'timestamp'
    readonly_fields = ['created_at']
    raw_id_fields = ['meteo_station']

    fieldsets = (
        ('Source', {
            'fields': ('meteo_station', 'timestamp', 'quality_flag', 'data_source'),
        }),
        ('Rainfall', {
            'fields': ('rainfall_mm',),
        }),
        ('Temperature (deg C)', {
            'fields': ('temp_avg_c', 'temp_max_c', 'temp_min_c'),
        }),
        ('Relative Humidity (%)', {
            'fields': ('rh_avg', 'rh_max', 'rh_min'),
        }),
        ('Wind Speed (m/s)', {
            'fields': ('wind_speed_avg_ms', 'wind_speed_max_ms', 'wind_speed_min_ms'),
        }),
        ('Wind Direction (deg)', {
            'fields': ('wind_dir_avg_deg', 'wind_dir_max_deg', 'wind_dir_min_deg'),
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',),
        }),
    )
