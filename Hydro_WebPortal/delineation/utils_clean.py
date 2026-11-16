#delineation/utils.py
import geopandas as gpd
import pandas as pd
import numpy as np
import math
import time
import logging
from shapely.geometry import Point, Polygon, MultiPolygon, box
from shapely import ops
from pysheds.grid import Grid
from django.conf import settings
import pyproj
from .fast_dissolve import buffer, close_holes, dissolve_geopandas
from .merit_detailed import split_catchment, get_largest
from django.utils import timezone

logger = logging.getLogger(__name__)

class SessionManager:
    @staticmethod
    def get_or_create_session(request):
        from .models import UserSession
        session_key = request.session.session_key
        if not session_key:
            request.session.create()
            session_key = request.session.session_key
        ip_address = request.META.get('REMOTE_ADDR', '')
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        session, created = UserSession.objects.get_or_create(
            session_key=session_key,
            defaults={'ip_address': ip_address, 'user_agent': user_agent}
        )
        session.last_activity = timezone.now()
        session.save()
        return session

    @staticmethod
    def update_session_stats(session_key, success):
        from .models import UserSession
        session = UserSession.objects.get(session_key=session_key)
        session.total_watersheds += 1
        if success:
            session.successful_watersheds += 1
        session.last_activity = timezone.now()
        session.save()

def get_dataset_coverage():
    datasets = []
    for basin in range(11, 92):  # MERIT-Hydro basins
        catchments_file = settings.SHAPE_DATA_PATH / 'merit_catchments' / f'cat_pfaf_{basin}_MERIT_Hydro_v07_Basins_v01.shp'
        rivers_file = settings.SHAPE_DATA_PATH / 'merit_rivers' / f'riv_pfaf_{basin}_MERIT_Hydro_v07_Basins_v01.shp'
        flowdir_file = settings.RASTER_DATA_PATH / 'flowdir_basins' / f'flowdir{basin}.tif'
        accum_file = settings.RASTER_DATA_PATH / 'accum_basins' / f'accum{basin}.tif'
        datasets.append({
            'basin': basin,
            'catchments': str(catchments_file) if catchments_file.exists() else None,
            'rivers': str(rivers_file) if rivers_file.exists() else None,
            'flowdir': str(flowdir_file) if flowdir_file.exists() else None,
            'accum': str(accum_file) if accum_file.exists() else None
        })
    return datasets

def validate_data_integrity():
    datasets = get_dataset_coverage()
    errors, warnings = [], []
    valid = True
    datasets_checked = 0
    for dataset in datasets:
        datasets_checked += 1
        if not all([dataset['catchments'], dataset['rivers'], dataset['flowdir'], dataset['accum']]):
            valid = False
            errors.append(f"Missing data for basin {dataset['basin']}")
    return {'valid': valid, 'errors': errors, 'warnings': warnings, 'datasets_checked': datasets_checked}

def get_area_mghydro_style(poly):
    """mghydro's equal-area projection method for accurate area calculation"""
    # Use modern pyproj syntax to avoid deprecation warnings
    from pyproj import Transformer
    
    # Create coordinate reference systems
    src_crs = pyproj.CRS('EPSG:4326')
    dst_crs = pyproj.CRS(proj='aea', lat_1=poly.bounds[1], lat_2=poly.bounds[3])
    
    # Create transformer
    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    
    # Transform the polygon
    projected_poly = ops.transform(transformer.transform, poly)
    return projected_poly.area / 1e6  # Convert to km²

def get_area(poly: Polygon) -> float:
    """Redirects to get_area_mghydro_style for consistency"""
    return get_area_mghydro_style(poly)

class WatershedDelineator:
    def __init__(self):
        self.megabasins_gdf = gpd.read_file(settings.SHAPE_DATA_PATH / 'basins_level2' / 'merit_hydro_vect_level2.shp')
        self.megabasins_gdf.set_crs('EPSG:4326', inplace=True, allow_override=True)

    def load_gdf(self, geotype: str, basin: int) -> gpd.GeoDataFrame:
        directory = settings.SHAPE_DATA_PATH / ('merit_catchments' if geotype == 'catchments' else 'merit_rivers')
        shapefile = directory / f'{"cat" if geotype == "catchments" else "riv"}_pfaf_{basin}_MERIT_Hydro_v07_Basins_v01.shp'
        if not shapefile.exists():
            raise FileNotFoundError(f"Shapefile not found: {shapefile}")
        gdf = gpd.read_file(shapefile)
        gdf.set_index('COMID', inplace=True)
        gdf.set_crs('EPSG:4326', inplace=True, allow_override=True)
        return gdf

    def addnode(self, B: list, node: int, rivers_gdf: gpd.GeoDataFrame):
        node = int(node)
        if node not in rivers_gdf.index:
            logger.warning(f"Node {node} not found in rivers_gdf index. Skipping. Sample of rivers_gdf index: {list(rivers_gdf.index)[:20]}")
            logger.warning(f"Type of node: {type(node)}, rivers_gdf index dtype: {rivers_gdf.index.dtype}")
            return
        B.append(node)
        for up in ['up1', 'up2', 'up3', 'up4']:
            try:
                up_id = int(rivers_gdf.loc[node, up])
            except KeyError:
                logger.warning(f"Node {node} not found in rivers_gdf index when accessing {up}.")
                continue
            except Exception as e:
                logger.warning(f"Error accessing {up} for node {node}: {e}")
                continue
            if up_id != 0:
                if up_id in rivers_gdf.index:
                    self.addnode(B, up_id, rivers_gdf)
                else:
                    logger.warning(f"Upstream ID {up_id} for node {node} not found in rivers_gdf index. Skipping.")

    def find_nearest_river(self, point, rivers_gdf):
        # Find the nearest river segment to the clicked point
        distances = rivers_gdf.geometry.distance(point)
        min_dist = distances.min()
        nearest_idx = distances.idxmin()
        nearest_comid = nearest_idx  # Index is COMID
        return nearest_comid, min_dist

    def delineate_watershed(self, longitude: float, latitude: float, session_key: str, area_reported=None):
        start_time = time.time()
        result = {'success': False, 'processing_time': 0, 'method': 'high'}
        try:
            point = Point(longitude, latitude)
            point_gdf = gpd.GeoDataFrame(geometry=[point], crs='EPSG:4326')
            # Find basin
            basin_gdf = gpd.sjoin(point_gdf, self.megabasins_gdf, how='left', predicate='intersects')
            if basin_gdf['BASIN'].iloc[0] is None:
                result['error'] = 'Point not located in any Level 2 basin'
                return result
            basin = int(basin_gdf['BASIN'].iloc[0])
            catchments_gdf = self.load_gdf('catchments', basin)
            rivers_gdf = self.load_gdf('rivers', basin)
            
            # Enhanced catchment selection with area matching (if area_reported provided)
            terminal_comid = None
            
            # Find terminal catchment
            gages_joined = gpd.sjoin(point_gdf, catchments_gdf, how='left', predicate='intersects')
            if gages_joined['COMID'].iloc[0] is None:
                # Try snapping to nearest river
                nearest_comid, min_dist = self.find_nearest_river(point, rivers_gdf)
                logger.info(f"Snapping to nearest river: COMID={nearest_comid}, min_dist={min_dist}")
                # Accept if within 0.01 degrees (~1km), adjust as needed
                if min_dist > 0.01:
                    result['error'] = f"Click is too far from any river (min distance: {min_dist:.3f} deg)"
                    return result
                terminal_comid = nearest_comid
            else:
                initial_comid = int(gages_joined['COMID'].iloc[0])
                
                # If area_reported provided, try to find better match
                if area_reported:
                    initial_uparea = rivers_gdf.loc[initial_comid, 'uparea'] if initial_comid in rivers_gdf.index else 0
                    area_diff = abs((initial_uparea - area_reported) / area_reported) if area_reported > 0 else 1
                    
                    if area_diff > 0.3:  # 30% difference triggers search
                        logger.info(f"Area mismatch: initial={initial_uparea:.0f} vs target={area_reported:.0f} km²")
                        # Search nearby for better area match (simplified version)
                        search_buffer = point.buffer(0.05)  # 5km search radius
                        nearby_catchments = catchments_gdf[catchments_gdf.intersects(search_buffer)]
                        
                        best_comid = initial_comid
                        best_diff = area_diff
                        
                        for comid in nearby_catchments.index:
                            if comid in rivers_gdf.index:
                                river_uparea = rivers_gdf.loc[comid, 'uparea']
                                candidate_diff = abs((river_uparea - area_reported) / area_reported)
                                if candidate_diff < best_diff:
                                    best_diff = candidate_diff
                                    best_comid = comid
                        
                        if best_comid != initial_comid:
                            logger.info(f"Found better area match: COMID {best_comid} with {best_diff*100:.1f}% difference")
                            terminal_comid = best_comid
                        else:
                            terminal_comid = initial_comid
                    else:
                        terminal_comid = initial_comid
                else:
                    terminal_comid = initial_comid
            catchment_poly = catchments_gdf.loc[terminal_comid].geometry
            bSingleCatchment = True
            # High-resolution delineation
            split_poly, lat_snap, lng_snap = split_catchment(session_key, basin, latitude, longitude, catchment_poly, bSingleCatchment)
            if split_poly is None:
                result['error'] = 'Failed to perform detailed delineation'
                return result
            # Collect upstream catchments
            B = []
            self.addnode(B, terminal_comid, rivers_gdf)
            subbasins_gdf = catchments_gdf.loc[B]
            subbasins_gdf.loc[terminal_comid, 'geometry'] = split_poly
            # Dissolve and clean
            watershed_gs = dissolve_geopandas(subbasins_gdf)
            if watershed_gs is None or watershed_gs.empty:
                logger.error(f"Dissolve operation returned None or empty GeoSeries. subbasins_gdf: {subbasins_gdf}")
                result['error'] = "Failed to dissolve subbasins. The input data may be invalid or empty."
                return result
            if settings.FILL:
                area_max = settings.FILL_THRESHOLD * settings.PIXEL_AREA
                watershed_gs = watershed_gs.geometry.apply(lambda p: close_holes(p, area_max))
            watershed_poly = get_largest(watershed_gs.iloc[0])
            # Check watershed_poly before using it
            if watershed_poly is None:
                logger.error(f"watershed_poly is None after get_largest. watershed_gs.iloc[0]: {watershed_gs.iloc[0]}")
                result['error'] = "Watershed polygon is missing. The dissolved geometry may be invalid."
                return result
            logger.debug(f"watershed_poly type: {type(watershed_poly)}, value: {watershed_poly}")
            from shapely.geometry.base import BaseGeometry
            if not isinstance(watershed_poly, BaseGeometry):
                logger.error(f"watershed_poly is not a valid geometry. Type: {type(watershed_poly)}, value: {watershed_poly}")
                result['error'] = "Watershed polygon is not a valid geometry object."
                return result
            area_km2 = get_area_mghydro_style(watershed_poly)
            stream_info = {
                'main_stream_length_km': rivers_gdf.loc[terminal_comid, 'lengthkm'] if 'lengthkm' in rivers_gdf else None,
                'stream_order': rivers_gdf.loc[terminal_comid, 'order'] if 'order' in rivers_gdf else None
            }
            result.update({
                'success': True,
                'watershed_polygon': watershed_poly,
                'properties': {
                    'area_km2': area_km2
                },
                'stream_info': stream_info,
                'outlet_coords': [lng_snap, lat_snap],
                'processing_time': time.time() - start_time
            })
        except Exception as e:
            logger.error(f"Delineation error: {str(e)}")
            result['success'] = False
            result['error'] = str(e)
        
        return result
