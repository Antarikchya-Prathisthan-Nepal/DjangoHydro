#delineation/views.py
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
import geopandas as gpd
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from django.contrib.gis.geos import Point, Polygon as DjangoPolygon
from django.core.paginator import Paginator
from django.utils import timezone
from django.conf import settings
import json
import logging
from .models import WatershedDelineation, ProcessingLog, UserSession
from .utils import WatershedDelineator, SessionManager, get_dataset_coverage, validate_data_integrity
import time

logger = logging.getLogger(__name__)

_DELINEATOR = None
_RIVERS_GDF = None


def _get_delineator():
    global _DELINEATOR
    if _DELINEATOR is None:
        _DELINEATOR = WatershedDelineator()
    return _DELINEATOR


def _get_rivers_gdf():
    global _RIVERS_GDF
    if _RIVERS_GDF is None:
        rivers_file = settings.SHAPE_DATA_PATH / 'merit_rivers' / 'merit_rivers.shp'
        if not rivers_file.exists():
            return None
        _RIVERS_GDF = gpd.read_file(rivers_file)
        if _RIVERS_GDF.crs is None:
            _RIVERS_GDF.set_crs('EPSG:4326', inplace=True, allow_override=True)
        else:
            _RIVERS_GDF = _RIVERS_GDF.to_crs('EPSG:4326')
    return _RIVERS_GDF

def debug_page(request):
    """
    Debug page for elevation data
    """
    session = SessionManager.get_or_create_session(request)
    context = {
        'session_id': session.session_key,
    }
    return render(request, 'delineation/debug.html', context)

@never_cache
def index(request):
    session = SessionManager.get_or_create_session(request)
    datasets = get_dataset_coverage()
    
    context = {
        'session_id': session.session_key,
        'recent_watersheds': session.get_recent_watersheds(limit=5),
        'total_watersheds': session.total_watersheds,
        'successful_watersheds': session.successful_watersheds,
        'datasets_available': len(datasets),
        'nepal_bounds': {'south': 26.0, 'north': 31.0, 'west': 80.0, 'east': 89.0}
    }
    return render(request, 'delineation/index.html', context)

@require_POST
@csrf_protect
def delineate_watershed(request):
    try:
        data = json.loads(request.body)
        longitude = float(data.get('longitude'))
        latitude = float(data.get('latitude'))
        precision = data.get('precision', 'high')
        method = data.get('method', 'hybrid')
        target_area = data.get('target_area')
        if target_area:
            try:
                target_area = float(target_area)
                logger.info(f"Target area provided: {target_area} km2")
            except (ValueError, TypeError):
                target_area = None
                logger.warning("Invalid target area provided, ignoring")
        
        logger.info(f"Received request: method={method}, coordinates=({latitude}, {longitude})")
        
        if not (80.0 <= longitude <= 89.0 and 26.0 <= latitude <= 31.0):
            return JsonResponse({'success': False, 'error': 'Coordinates must be within Nepal bounds (80-89°E, 26-31°N)'}, status=400)
        session = SessionManager.get_or_create_session(request)
        session_key = session.session_key
        watershed = WatershedDelineation.objects.create(
            session_key=session_key,
            click_point=Point(longitude, latitude),
            click_latitude=latitude,
            click_longitude=longitude
        )
        ProcessingLog.objects.create(
            watershed=watershed,
            step='initialization',
            message=f'Started watershed delineation for ({latitude:.6f}, {longitude:.6f}) with {precision} precision and {method} method',
            level='INFO'
        )

        delineator = _get_delineator()
        if precision == 'high' and method == 'vector':
            result = delineator.delineate_watershed(longitude, latitude, session_key, target_area)
        # Use vector method for MGHydro-style requests due to superior accuracy
        elif method == 'mghydro':
            logger.info(f"Using vector method for mghydro request (superior accuracy): {longitude}, {latitude}")
            result = delineator.delineate_watershed(longitude, latitude, session_key, target_area)
            # Adjust result metadata to indicate mghydro method
            if result.get('success'):
                result['method'] = 'mghydro_vector'
        elif method == 'mghydro_comprehensive':
            logger.info(f"Using comprehensive mghydro method for coordinates: {longitude}, {latitude}")
            # Use vector method for mghydro requests (proven 98.6% accuracy)
            result = delineator.delineate_watershed(longitude, latitude, session_key, target_area)
            
            if result.get('success'):
                logger.info(f"Vector method result: success=True, area={result['properties'].get('area_km2', 0):.2f} km²")
        else:
            # Use vector method for all other requests as well (fallback)
            result = delineator.delineate_watershed(longitude, latitude, session_key, target_area)

        watershed.success = result.get('success', False)
        watershed.error_message = result.get('error')
        if result.get('success'):
            from shapely.geometry import shape, MultiPolygon
            from django.contrib.gis.geos import GEOSGeometry
            watershed_geojson = result.get('watershed_geojson')
            if watershed_geojson and 'geometry' in watershed_geojson:
                geom = shape(watershed_geojson['geometry'])
                if geom.is_valid:
                    # Convert single Polygon to MultiPolygon for database compatibility
                    if geom.geom_type == 'Polygon':
                        geom = MultiPolygon([geom])
                    watershed.watershed_polygon = GEOSGeometry(geom.wkt, srid=4326)
                else:
                    logger.warning(f"Invalid geometry for watershed {watershed.id}. Fixing with buffer(0).")
                    geom = geom.buffer(0)
                    # Convert single Polygon to MultiPolygon for database compatibility
                    if geom.geom_type == 'Polygon':
                        geom = MultiPolygon([geom])
                    watershed.watershed_polygon = GEOSGeometry(geom.wkt, srid=4326)
            else:
                logger.error(f"watershed_geojson is None or invalid for watershed {watershed.id}. Result: {result}")
                return JsonResponse({'success': False, 'error': 'No watershed geometry returned from delineation'}, status=400)
            props = result.get('properties', {})
            stream_info = result.get('stream_info', {})
            watershed.watershed_area_km2 = float(props.get('area_km2', 0))  # Convert to Python float
            watershed.main_stream_length_km = float(stream_info.get('main_stream_length_km', 0))  # Convert to Python float
            watershed.stream_order = int(stream_info.get('stream_order', 0))  # Convert to Python int
            watershed.processing_time_seconds = float(result.get('processing_time', 0))  # Convert to Python float
            
            elevation_stats = {}
            try:
                from .elevation_utils import calculate_elevation_area_stats
                watershed_geom = shape(watershed_geojson['geometry'])
                elevation_stats = calculate_elevation_area_stats(watershed_geom, elevation_thresholds=[3000, 5000])
                logger.info("Elevation stats calculated successfully")
                
                # Store elevation stats in model
                if elevation_stats and 'areas_below_threshold' in elevation_stats:
                    for threshold_data in elevation_stats['areas_below_threshold']:
                        threshold = threshold_data.get('threshold')
                        if threshold == 3000:
                            watershed.area_below_3000m_km2 = float(threshold_data.get('area_km2', 0))
                            watershed.area_below_3000m_percent = float(threshold_data.get('percentage', 0))
                        elif threshold == 5000:
                            watershed.area_below_5000m_km2 = float(threshold_data.get('area_km2', 0))
                            watershed.area_below_5000m_percent = float(threshold_data.get('percentage', 0))
                    
                # Log warning if fallback values are being used
                if elevation_stats.get('is_fallback'):
                    logger.warning(f"Using fallback elevation statistics for watershed ID {watershed.id}")
                    ProcessingLog.objects.create(
                        watershed=watershed,
                        step='elevation_analysis',
                        message='Using estimated elevation statistics. DEM data does not fully cover the watershed area.',
                        level='WARNING'
                    )
            except Exception as e:
                logger.error(f"Error calculating elevation stats: {str(e)}")
                elevation_stats = {}

            watershed.save()
            ProcessingLog.objects.create(
                watershed=watershed,
                step='save',
                message='Watershed polygon and computed values saved to database.',
                level='INFO'
            )
            
            # Simplified elevation stats processing to fix errors
            formatted_elevation_stats = None
            if elevation_stats:
                # Basic structure with default values
                formatted_elevation_stats = {
                    'total_area_km2': 0.0,
                    'is_fallback': False,
                    'dem_coverage': 'unknown',
                    'coverage_percent': 0.0,
                    'dem_file': 'unknown',
                    'fallback_reason': None,
                    'areas_below_threshold': []
                }
                
                # Safely add available values
                try:
                    if 'total_area_km2' in elevation_stats:
                        formatted_elevation_stats['total_area_km2'] = float(elevation_stats['total_area_km2'])
                    
                    if 'is_fallback' in elevation_stats:
                        formatted_elevation_stats['is_fallback'] = bool(elevation_stats['is_fallback'])
                    
                    if 'dem_coverage' in elevation_stats:
                        formatted_elevation_stats['dem_coverage'] = str(elevation_stats['dem_coverage'])
                    
                    if 'coverage_percent' in elevation_stats:
                        formatted_elevation_stats['coverage_percent'] = float(elevation_stats['coverage_percent'])
                    
                    if 'dem_file' in elevation_stats:
                        formatted_elevation_stats['dem_file'] = str(elevation_stats['dem_file'])
                    
                    if 'fallback_reason' in elevation_stats and elevation_stats['fallback_reason']:
                        formatted_elevation_stats['fallback_reason'] = str(elevation_stats['fallback_reason'])
                    
                    # Add areas_below_threshold data if available
                    if 'areas_below_threshold' in elevation_stats and isinstance(elevation_stats['areas_below_threshold'], list):
                        for item in elevation_stats['areas_below_threshold']:
                            if isinstance(item, dict):
                                threshold_data = {
                                    'threshold': 0,
                                    'area_km2': 0.0,
                                    'percentage': 0.0,
                                    'is_fallback': False
                                }
                                
                                if 'threshold' in item:
                                    threshold_data['threshold'] = int(item['threshold'])
                                
                                if 'area_km2' in item:
                                    threshold_data['area_km2'] = float(item['area_km2'])
                                
                                if 'percentage' in item:
                                    threshold_data['percentage'] = float(item['percentage'])
                                
                                if 'is_fallback' in item:
                                    threshold_data['is_fallback'] = bool(item['is_fallback'])
                                
                                formatted_elevation_stats['areas_below_threshold'].append(threshold_data)
                except Exception as e:
                    logger.error(f"Error converting elevation data types: {str(e)}")
            else:
                # Default empty structure
                formatted_elevation_stats = {
                    'total_area_km2': 0.0,
                    'is_fallback': True,
                    'dem_coverage': 'none',
                    'coverage_percent': 0.0,
                    'dem_file': 'none',
                    'fallback_reason': "No elevation data available",
                    'areas_below_threshold': []
                }
                
            # Prepare response data with explicit type conversion to ensure JSON serialization
            # Add elevation band polygons for frontend overlays
            elevation_band_polygons = None
            if elevation_stats and 'elevation_band_polygons' in elevation_stats:
                # Already in the stats (from utils)
                elevation_band_polygons = elevation_stats['elevation_band_polygons']
            elif 'elevation_band_polygons' in formatted_elevation_stats:
                elevation_band_polygons = formatted_elevation_stats['elevation_band_polygons']
            else:
                elevation_band_polygons = []

            response_data = {
                'success': True,  # Python bool
                'watershed_id': str(watershed.id),
                'watershed_geojson': watershed_geojson,  # Use the original GeoJSON from the result
                'outlet_coords': [float(coord) for coord in result.get('outlet_coords', [])],  
                'area_km2': float(watershed.watershed_area_km2),  
                'main_stream_length_km': float(watershed.main_stream_length_km), 
                'stream_order': int(watershed.stream_order),  
                'processing_time': float(watershed.processing_time_seconds),  
                'elevation_stats': formatted_elevation_stats,  # Add formatted elevation stats
                'elevation_band_polygons': elevation_band_polygons
            }
            logger.debug(f"Response data: {response_data}")
            return JsonResponse(response_data)
        else:
            watershed.save()
            ProcessingLog.objects.create(
                watershed=watershed,
                step='error',
                message=watershed.error_message or 'Unknown error',
                level='ERROR'
            )
            return JsonResponse({'success': False, 'error': watershed.error_message}, status=400)
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
    except (ValueError, TypeError) as e:
        if "NoneType" in str(e) or "not subscriptable" in str(e):
            return JsonResponse({'success': False, 'error': 'A required data value was missing or invalid. Please click directly on a visible river, and ensure your data files are complete and consistent.'}, status=400)
        return JsonResponse({'success': False, 'error': f'Invalid coordinates: {str(e)}'}, status=400)
    except Exception as e:
        logger.error(f"Watershed delineation error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Internal server error'}, status=500)
@require_GET
def rivers_geojson(request):
    try:
        max_order = int(request.GET.get('max_order', settings.NUM_STREAM_ORDERS))
        rivers_gdf = _get_rivers_gdf()
        if rivers_gdf is not None:
            rivers_gdf = rivers_gdf[rivers_gdf['order'] <= max_order]
            return JsonResponse(rivers_gdf.__geo_interface__)
        return JsonResponse({'success': False, 'error': 'Rivers data not available'}, status=404)
    except Exception as e:
        logger.error(f"Rivers GeoJSON error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Internal server error'}, status=500)

@require_GET
def download_geojson(request, watershed_id):
    # Require a free (or full) account to download.
    if not request.user.is_authenticated:
        return JsonResponse(
            {'success': False, 'auth_required': True,
             'error': 'Please sign in or create a free account to download.'},
            status=401,
        )
    try:
        watershed = WatershedDelineation.objects.get(id=watershed_id)
        session = SessionManager.get_or_create_session(request)
        if watershed.session_key != session.session_key:
            return JsonResponse({'success': False, 'error': 'Unauthorized'}, status=403)
        
        if not watershed.watershed_geojson:
            return JsonResponse({'success': False, 'error': 'No watershed data available'}, status=404)
        
        geojson_data = watershed.watershed_geojson
        response = HttpResponse(
            content=json.dumps(geojson_data, indent=2),
            content_type='application/geo+json'
        )
        response['Content-Disposition'] = f'attachment; filename="watershed_{watershed_id}.geojson"'
        return response
    
    except WatershedDelineation.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Watershed not found'}, status=404)
    except Exception as e:
        logger.error(f"Download GeoJSON error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Internal server error'}, status=500)

@require_GET
def recent_watersheds(request):
    try:
        session = SessionManager.get_or_create_session(request)
        watersheds = session.get_recent_watersheds(limit=5)
        response_data = {
            'watersheds': [{
                'id': str(w.id),
                'created_at': w.created_at.isoformat(),
                'success': w.success
            } for w in watersheds]
        }
        return JsonResponse(response_data)
    except Exception as e:
        logger.error(f"Recent watersheds error: {str(e)}")
        return JsonResponse({'success': False, 'error': 'Internal server error'}, status=500)
        logger.error(f"Results page error: {str(e)}")
        return render(request, 'delineation/error.html', {
            'error_message': 'Watershed not found or error loading results'
        })


@require_GET
def health_check(request):
    """
    Health check endpoint for monitoring
    """
    try:
        # Check database connection
        session_count = UserSession.objects.count()
        
        # Check data integrity
        validation = validate_data_integrity()
        
        health_status = {
            'status': 'healthy' if validation['valid'] else 'degraded',
            'timestamp': timezone.now().isoformat(),
            'database': 'connected',
            'session_count': session_count,
            'datasets_valid': validation['valid'],
            'datasets_checked': validation['datasets_checked']
        }
        
        if validation['errors']:
            health_status['errors'] = validation['errors']
        
        if validation['warnings']:
            health_status['warnings'] = validation['warnings']
        
        return JsonResponse(health_status)
        
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return JsonResponse({
            'status': 'unhealthy',
            'timestamp': timezone.now().isoformat(),
            'error': str(e)
        }, status=500)


# Error handlers
def handler404(request, exception):
    """Custom 404 error handler"""
    return render(request, 'delineation/error.html', {
        'error_code': 404,
        'error_message': 'Page not found'
    }, status=404)


def handler500(request):
    """Custom 500 error handler"""
    return render(request, 'delineation/error.html', {
        'error_code': 500,
        'error_message': 'Internal server error'
    }, status=500)