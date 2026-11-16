"""
Utilities for ERA5 data download and processing
Integrated with proven surface/pressure download logic
"""
import os
import requests
import numpy as np
import pandas as pd
from datetime import datetime, timedelta, date
from django.conf import settings
from django.utils import timezone
from .models import ERA5Data, DischargeStation, PipelineRun
import logging, zipfile

try:
    import xarray as xr
except ImportError:
    xr = None
try:
    import cdsapi
except ImportError:
    cdsapi = None
try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

logger = logging.getLogger(__name__)

class ERA5Downloader:
    def __init__(self, simulate_mode=False, *args, **kwargs):
        self.simulate_mode = simulate_mode
        self.model_features = ['t2m', 'u10', 'v10', 'tp', 'q', 'swvl1']
        self.surface_variables = [
            '2m_temperature',
            '10m_u_component_of_wind',
            '10m_v_component_of_wind',
            'total_precipitation',
            'volumetric_soil_water_layer_1'    # soil moisture (0-7cm depth)
        ]
        self.pressure_variables = ['specific_humidity']
        self.era5_delay_days = 7
        self.min_data_completeness = 0.9
        self.debug_mode = True
        self.max_retries = kwargs.get('max_retries', 3)
        self.retry_delay = kwargs.get('retry_delay', 10)
        self.surface_only = False
        # Try to load CDS API key from environment variable
        self.api_key = os.environ.get('CDSAPI_KEY')
        # If not found, try to load from .cdsapirc file in home directory
        if not self.api_key:
            cdsa_path = os.path.expanduser('~/.cdsapirc')
            if os.path.exists(cdsa_path):
                with open(cdsa_path, 'r') as f:
                    for line in f:
                        if 'key:' in line:
                            self.api_key = line.split('key:')[1].strip()
                            break
        if not self.api_key:
            self.api_key = None
        if cdsapi:
            try:
                self.cds_client = cdsapi.Client()
            except Exception:
                self.cds_client = None
        else:
            self.cds_client = None

    def calculate_cell_weights(self, lats, lons, catchment_polygon):
        """
        Calculate area-overlap weights for each ERA5 grid cell against the catchment polygon.

        For each grid cell, the weight is proportional to the intersection area with the
        catchment polygon. Weights are normalized to sum to 1, so a weighted sum over
        all cells gives the catchment-average value for any variable.

        Args:
            lats: 1D array of latitude values from the NetCDF file
            lons: 1D array of longitude values from the NetCDF file
            catchment_polygon: Django GEOSGeometry (MultiPolygon) from station.catchment_polygon

        Returns:
            2D numpy array (len(lats) x len(lons)) with normalized weights,
            or None if shapely is unavailable, no intersection exists, or catchment_polygon is None.
        """
        if catchment_polygon is None:
            return None

        try:
            from shapely.geometry import box as shapely_box
            from shapely import wkt as shapely_wkt

            # Convert Django GEOSGeometry → Shapely geometry via WKT
            shapely_catchment = shapely_wkt.loads(catchment_polygon.wkt)

            lat_res = abs(float(lats[1] - lats[0])) if len(lats) > 1 else 0.1
            lon_res = abs(float(lons[1] - lons[0])) if len(lons) > 1 else 0.1

            weights = np.zeros((len(lats), len(lons)))

            for i, lat in enumerate(lats):
                for j, lon in enumerate(lons):
                    # Build the bounding box for this grid cell
                    cell = shapely_box(
                        float(lon) - lon_res / 2,
                        float(lat) - lat_res / 2,
                        float(lon) + lon_res / 2,
                        float(lat) + lat_res / 2
                    )
                    if cell.intersects(shapely_catchment):
                        intersection = cell.intersection(shapely_catchment)
                        weights[i, j] = intersection.area

            total = weights.sum()
            if total > 0:
                weights = weights / total
                n_cells = (weights > 0).sum()
                logger.info(f"Catchment weights computed: {n_cells} grid cells intersect catchment (total weight={total:.6f})")
                return weights
            else:
                logger.warning("No ERA5 grid cells intersect catchment polygon — falling back to nearest-point extraction")
                return None

        except ImportError:
            logger.warning("shapely not installed — falling back to nearest-point extraction")
            return None
        except Exception as e:
            logger.warning(f"Error computing catchment weights: {e} — falling back to nearest-point extraction")
            return None

    def preprocess_and_merge_netcdf_files(self, surface_file, pressure_file, station_lat, station_lon,
                                          catchment_polygon=None):
        """
        Preprocess NetCDF files: unzip, aggregate hourly→daily, apply catchment-weighted spatial
        averaging (or nearest-point fallback), interpolate and merge pressure data.

        When catchment_polygon is provided:
          - Temporal aggregation over full spatial grid (keep lat/lon dims)
          - Pressure data interpolated to surface grid resolution
          - Area-weighted spatial average over catchment cells → one scalar per day

        When catchment_polygon is None:
          - Nearest-point extraction at (station_lat, station_lon)

        Returns merged daily DataFrame with columns: valid_time, t2m, u10, v10, tp, swvl1 (if present), q (if present)
        """
        import tempfile
        import shutil
        logger.info(
            f"[preprocess_and_merge_netcdf_files] surface_file: {surface_file}, "
            f"pressure_file: {pressure_file}, lat: {station_lat}, lon: {station_lon}, "
            f"catchment_polygon: {'yes' if catchment_polygon else 'no'}"
        )

        # Step 1: Unzip if needed
        def _unzip_if_needed(nc_path):
            if zipfile.is_zipfile(nc_path):
                with zipfile.ZipFile(nc_path, 'r') as zip_ref:
                    nc_names = [n for n in zip_ref.namelist() if n.endswith('.nc')]
                    inner = nc_names[0] if nc_names else 'data_0.nc'
                    with tempfile.NamedTemporaryFile(suffix='.nc', delete=False) as tmp_nc:
                        tmp_path = tmp_nc.name
                    with zip_ref.open(inner) as src, open(tmp_path, 'wb') as dst:
                        dst.write(src.read())
                    return tmp_path
            return nc_path

        surface_nc = _unzip_if_needed(surface_file) if surface_file else None
        pressure_nc = _unzip_if_needed(pressure_file) if pressure_file else None
        logger.info(f"[preprocess_and_merge_netcdf_files] surface_nc: {surface_nc}, pressure_nc: {pressure_nc}")

        ds_land = xr.open_dataset(surface_nc, engine='netcdf4') if surface_nc else None
        if ds_land is None:
            logger.error("[preprocess_and_merge_netcdf_files] No surface dataset available")
            return pd.DataFrame()

        lats = ds_land.latitude.values
        lons = ds_land.longitude.values
        logger.info(f"[preprocess_and_merge_netcdf_files] ds_land vars: {list(ds_land.data_vars)}")

        # Step 2: Compute catchment weights (returns None if no polygon or no intersection)
        weights = self.calculate_cell_weights(lats, lons, catchment_polygon)

        # Step 3: Temporal aggregation (surface)
        ds_land_daily = xr.Dataset()
        for var in ds_land.data_vars:
            logger.info(f"[preprocess_and_merge_netcdf_files] Aggregating surface variable: {var}")
            try:
                if var == 'tp':
                    ds_land_daily[var] = ds_land[var].resample(valid_time='1D').sum()
                else:
                    ds_land_daily[var] = ds_land[var].resample(valid_time='1D').mean()
            except Exception as e:
                logger.error(f"[preprocess_and_merge_netcdf_files] Error aggregating {var}: {e}")

        # Step 4: Spatial reduction (surface)
        if weights is not None:
            logger.info(f"[preprocess_and_merge_netcdf_files] Catchment-weighted aggregation ({(weights > 0).sum()} cells)")
            weights_da = xr.DataArray(
                weights,
                coords={'latitude': ds_land.latitude, 'longitude': ds_land.longitude},
                dims=['latitude', 'longitude']
            )
            agg_ds = xr.Dataset()
            for var in ds_land_daily.data_vars:
                agg_ds[var] = (ds_land_daily[var] * weights_da).sum(dim=['latitude', 'longitude'])
            df_land = agg_ds.to_dataframe().reset_index()
        else:
            logger.info(f"[preprocess_and_merge_netcdf_files] Nearest-point fallback at ({station_lat}, {station_lon})")
            point_ds = xr.Dataset()
            for var in ds_land_daily.data_vars:
                point_ds[var] = ds_land_daily[var].sel(
                    latitude=station_lat, longitude=station_lon, method='nearest'
                )
            df_land = point_ds.to_dataframe().reset_index()

        logger.info(f"[preprocess_and_merge_netcdf_files] df_land head:\n{df_land.head()}")
        ds_land.close()

        # Step 5: Pressure data (q) — interpolate to surface grid then aggregate
        df_q = None
        if pressure_nc:
            ds_q = xr.open_dataset(pressure_nc, engine='netcdf4')
            logger.info(f"[preprocess_and_merge_netcdf_files] ds_q vars: {list(ds_q.data_vars)}")
            var_name = (
                'q' if 'q' in ds_q.data_vars
                else 'specific_humidity' if 'specific_humidity' in ds_q.data_vars
                else None
            )
            if var_name:
                logger.info(f"[preprocess_and_merge_netcdf_files] Sample {var_name} values: {ds_q[var_name].values.flatten()[:10]}")
                if weights is not None:
                    # Interpolate pressure grid → surface grid, then apply same weights
                    # Use DataArrays with explicit coordinate values so xarray can align
                    # them correctly with weights_da (which uses ds_land.latitude coords)
                    lat_da = xr.DataArray(lats, coords={'latitude': lats}, dims=['latitude'])
                    lon_da = xr.DataArray(lons, coords={'longitude': lons}, dims=['longitude'])
                    q_interp = ds_q[var_name].interp(
                        latitude=lat_da,
                        longitude=lon_da,
                        method='linear'
                    )
                    q_daily = q_interp.resample(valid_time='1D').mean()
                    q_agg = (q_daily * weights_da).sum(dim=['latitude', 'longitude'])
                    df_q = q_agg.to_dataframe(name='q').reset_index()
                    logger.info(f"[preprocess_and_merge_netcdf_files] Pressure catchment-weighted aggregation applied")
                else:
                    q_point = ds_q[var_name].sel(
                        latitude=station_lat, longitude=station_lon, method='nearest'
                    )
                    q_daily = q_point.resample(valid_time='1D').mean()
                    df_q = q_daily.to_dataframe(name='q').reset_index()
                    logger.info(f"[preprocess_and_merge_netcdf_files] Pressure nearest-point fallback applied")
            else:
                logger.warning("[preprocess_and_merge_netcdf_files] 'q'/'specific_humidity' not found in pressure file!")
            ds_q.close()

        # Step 6: Merge on valid_time
        if df_q is not None and 'q' in df_q.columns:
            merged = pd.merge(df_land, df_q[['valid_time', 'q']], on='valid_time', how='inner')
            logger.info(f"[preprocess_and_merge_netcdf_files] Merged df head:\n{merged.head()}")
        else:
            merged = df_land.copy()
            logger.warning(f"[preprocess_and_merge_netcdf_files] No pressure data merged.")

        # Step 7: Clean up temp files
        for f in [surface_nc, pressure_nc]:
            if f and f not in [surface_file, pressure_file] and os.path.exists(f):
                try:
                    os.unlink(f)
                except Exception:
                    pass

        # Final: normalise valid_time and drop rows without required features
        try:
            merged['valid_time'] = pd.to_datetime(merged['valid_time'], errors='coerce')
        except Exception as e:
            logger.error(f"[preprocess_and_merge_netcdf_files] Error parsing valid_time: {e}")
        merged = merged.dropna(subset=['valid_time'])
        if pd.api.types.is_datetime64_any_dtype(merged['valid_time']):
            merged['valid_time'] = merged['valid_time'].dt.date
        else:
            logger.error("valid_time column is not datetime after conversion!")
        feature_cols = ['t2m', 'u10', 'v10', 'tp']
        if 'q' in merged.columns:
            feature_cols.append('q')
        if 'swvl1' in merged.columns:
            feature_cols.append('swvl1')
        merged = merged.dropna(subset=feature_cols, how='all')
        logger.info(f"[preprocess_and_merge_netcdf_files] Final merged df head:\n{merged.head()}")
        return merged
    def download_for_area(self, area, start_date, end_date, variables=None, station=None):
        """
        Download ERA5 data for a specific area [North, West, South, East] using the same logic as management command.
        If station is provided, use download_era5_data for full database update and file handling.
        """
        if self.simulate_mode:
            center_lat = (area[0] + area[2]) / 2
            center_lon = (area[1] + area[3]) / 2
            return self._simulate_coordinate_data(center_lat, center_lon, start_date, end_date, variables)
        if not self.api_key:
            raise Exception("No CDS API key found. Real ERA5 data download requires valid API key.")
        if station is not None:
            # Use the same logic as management command
            return self.download_era5_data(station, start_date, end_date)
        # Fallback: legacy logic if no station object
        if variables is None:
            variables = self.surface_variables + self.pressure_variables
        surface_vars = [var for var in variables if var in self.surface_variables]
        pressure_vars = [var for var in variables if var in self.pressure_variables]
        combined_data = {}
        if surface_vars:
            surface_data = self._download_surface_data_for_area(area, start_date, end_date, surface_vars)
            combined_data.update(surface_data)
        if pressure_vars:
            pressure_data = self._download_pressure_data_for_area(area, start_date, end_date, pressure_vars)
            combined_data.update(pressure_data)
        return combined_data
    
    def download_for_coordinates(self, latitude, longitude, start_date, end_date, variables=None):
        """
        Download ERA5 data for specific coordinates and date range
        """
        if self.simulate_mode:
            return self._simulate_coordinate_data(latitude, longitude, start_date, end_date, variables)
        
        if not self.api_key:
            raise Exception("No CDS API key found. Real ERA5 data download requires valid API key.")
        
        if variables is None:
            variables = self.surface_variables + self.pressure_variables
        
        area = [
            latitude + self.bbox_buffer,
            longitude - self.bbox_buffer,
            latitude - self.bbox_buffer,
            longitude + self.bbox_buffer
        ]
        
        return self._download_and_process_daily_era5(area, start_date, end_date, variables, latitude, longitude)
    
    def _download_and_process_daily_era5(self, area, start_date, end_date, variables,
                                          latitude, longitude, catchment_polygon=None):
        """
        Download and process ERA5 data for a date range in batches
        """
        try:
            all_data = {}
            surface_vars = [var for var in variables if var in self.surface_variables]
            pressure_vars = [var for var in variables if var in self.pressure_variables]
            
            # Batch by months to reduce API calls
            date_ranges = pd.date_range(start=start_date, end=end_date, freq='ME')
            if date_ranges[-1] < end_date:
                date_ranges = date_ranges.append(pd.Index([end_date]))
            
            progress = tqdm(date_ranges[:-1], desc="Processing ERA5 months") if tqdm else date_ranges[:-1]
            for start in progress:
                batch_end = min(start + pd.offsets.MonthEnd(0), end_date)
                if start > batch_end:
                    continue
                
                logger.info(f"Processing ERA5 data from {start} to {batch_end}")
                
                surface_file = None
                if surface_vars:
                    surface_file = self._download_single_day_surface(area, start, batch_end, surface_vars)
                
                pressure_file = None
                if pressure_vars:
                    pressure_file = self._download_single_day_pressure(area, start, batch_end, pressure_vars)
                
                day_data = self._process_daily_era5_data(
                    surface_file=surface_file,
                    pressure_file=pressure_file,
                    start_date=start,
                    end_date=batch_end,
                    station_lat=latitude,
                    station_lon=longitude,
                    catchment_polygon=catchment_polygon
                )
                
                all_data.update(day_data)
                
                if surface_file:
                    os.unlink(surface_file)
                if pressure_file:
                    os.unlink(pressure_file)
            
            return all_data
            
        except Exception as e:
            logger.error(f"Error in daily ERA5 download and processing: {e}")
            raise
    
    # Mapping from short model-feature names to the long names required by the
    # ERA5-Land CDS API.  Pressure-level variables (e.g. 'q', 'specific_humidity')
    # are intentionally excluded — they are fetched separately via
    # _download_single_day_pressure().
    _SURFACE_SHORT_TO_LONG = {
        't2m':   '2m_temperature',
        'u10':   '10m_u_component_of_wind',
        'v10':   '10m_v_component_of_wind',
        'tp':    'total_precipitation',
        'swvl1': 'volumetric_soil_water_layer_1',
    }
    # The set of valid long names accepted by the ERA5-Land API (for pass-through).
    _SURFACE_LONG_NAMES = set(_SURFACE_SHORT_TO_LONG.values())
    # Pressure-level variable names (short and long) — excluded from surface requests.
    _PRESSURE_VARS = {'q', 'specific_humidity'}

    def _download_single_day_surface(self, area, start_date, end_date, variables):
        """Download surface data for a date range.

        Accepts ``variables`` as either short names (e.g. 't2m', 'swvl1') or
        long names (e.g. '2m_temperature', 'volumetric_soil_water_layer_1').
        Pressure-level variables ('q', 'specific_humidity') are silently skipped
        because they are downloaded separately via _download_single_day_pressure().
        """
        try:
            year_list = sorted(set(pd.date_range(start_date, end_date).year))
            month_list = sorted(set(pd.date_range(start_date, end_date).month))
            day_list = sorted(set(pd.date_range(start_date, end_date).day))
            hours = [f"{h:02d}:00" for h in range(24)]

            # Normalise to long names, skipping pressure-level variables.
            surface_long_vars = []
            for v in variables:
                if v in self._PRESSURE_VARS:
                    continue  # handled by _download_single_day_pressure
                if v in self._SURFACE_SHORT_TO_LONG:
                    surface_long_vars.append(self._SURFACE_SHORT_TO_LONG[v])
                elif v in self._SURFACE_LONG_NAMES:
                    surface_long_vars.append(v)
                # unknown names are silently skipped

            if not surface_long_vars:
                raise ValueError(
                    f"No valid surface variables found in {variables}. "
                    f"Expected short names {list(self._SURFACE_SHORT_TO_LONG.keys())} "
                    f"or long names {sorted(self._SURFACE_LONG_NAMES)}."
                )

            request = {
                "variable": surface_long_vars,
                "year": [str(y) for y in year_list],
                "month": [f"{m:02d}" for m in month_list],
                "day": [f"{d:02d}" for d in day_list],
                "time": hours,
                "data_format": "netcdf",
                "area": area,
            }
            
            if self.cds_client is None:
                raise RuntimeError(
                    "CDS API client is not initialised. "
                    "Create C:\\Users\\<you>\\.cdsapirc with:\n"
                    "  url: https://cds.climate.copernicus.eu/api\n"
                    "  key: <your-api-key>\n"
                    "or set the CDSAPI_KEY environment variable."
                )

            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.nc', delete=False) as tmp_file:
                tmp_filename = tmp_file.name
            
            retry_count = 0
            while retry_count < self.max_retries:
                try:
                    logger.info(f"Downloading surface data for {start_date} to {end_date} to: {tmp_filename}")
                    self.cds_client.retrieve("reanalysis-era5-land", request, tmp_filename)
                    file_size = os.path.getsize(tmp_filename)
                    logger.info(f"Downloaded surface file size: {file_size} bytes")
                    return tmp_filename
                except Exception as e:
                    retry_count += 1
                    if retry_count >= self.max_retries:
                        raise e
                    logger.warning(f"Surface download attempt {retry_count} failed, retrying in {self.retry_delay}s...")
                    import time
                    time.sleep(self.retry_delay)
                    
        except Exception as e:
            logger.error(f"Error downloading surface data for {start_date} to {end_date}: {e}")
            raise
    
    def _download_single_day_pressure(self, station, start_date, end_date, variables):
        """Download pressure data for a date range"""
        try:
            year_list = sorted(set(pd.date_range(start_date, end_date).year))
            month_list = sorted(set(pd.date_range(start_date, end_date).month))
            day_list = sorted(set(pd.date_range(start_date, end_date).day))
            hours = [f"{h:02d}:00" for h in range(24)]

            # Use station's era5_download_area (respects custom area or auto-generates from location)
            area = station.era5_download_area
            logger.info(f"Pressure download area for {station.name}: {area}")

            request = {
                "product_type": "reanalysis",
                "variable": variables,
                "pressure_level": ["925"],
                "year": [str(y) for y in year_list],
                "month": [f"{m:02d}" for m in month_list],
                "day": [f"{d:02d}" for d in day_list],
                "time": hours,
                "data_format": "netcdf",
                "area": area,
                "grid": [0.1, 0.1],   # 0.1° x 0.1° grid resolution
            }
            
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.nc', delete=False) as tmp_file:
                tmp_filename = tmp_file.name
            
            retry_count = 0
            while retry_count < self.max_retries:
                try:
                    logger.info(f"Downloading pressure data for {start_date} to {end_date} to: {tmp_filename}")
                    self.cds_client.retrieve("reanalysis-era5-pressure-levels", request, tmp_filename)
                    file_size = os.path.getsize(tmp_filename)
                    logger.info(f"Downloaded pressure file size: {file_size} bytes")
                    return tmp_filename
                except Exception as e:
                    retry_count += 1
                    if retry_count >= self.max_retries:
                        raise e
                    logger.warning(f"Pressure download attempt {retry_count} failed, retrying in {self.retry_delay}s...")
                    import time
                    time.sleep(self.retry_delay)
                    
        except Exception as e:
            logger.error(f"Error downloading pressure data for {start_date} to {end_date}: {e}")
            raise


    def _process_daily_era5_data(self, surface_file, pressure_file, start_date, end_date,
                                   station_lat, station_lon, catchment_polygon=None):
        """
        Process ERA5 data: extract ZIP, aggregate hourly→daily, apply catchment-weighted
        spatial averaging (or nearest-point fallback), merge surface + pressure variables.

        When catchment_polygon is provided:
          - Step 1: Aggregate full spatial grid hourly → daily (keep lat/lon dims)
          - Step 2: Interpolate pressure data to surface grid resolution
          - Step 3: Apply area-weighted spatial average over catchment cells → scalar per day

        When catchment_polygon is None (fallback):
          - Select nearest grid point to station coordinates, then aggregate hourly → daily
        """
        if not xr:
            raise ImportError("xarray is required for ERA5 processing")

        try:
            import zipfile
            import tempfile

            # Helper: normalise time coordinate name
            def _normalize_time(ds):
                if "valid_time" in ds.coords and "time" not in ds.coords:
                    ds = ds.rename({"valid_time": "time"})
                if not np.issubdtype(ds["time"].dtype, np.datetime64):
                    ds["time"] = pd.to_datetime(ds["time"].values)
                return ds

            # Unzip surface file if needed
            if surface_file and zipfile.is_zipfile(surface_file):
                logger.info(f"Extracting surface ZIP: {surface_file}")
                with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as tmp_surface:
                    extracted_surface_file = tmp_surface.name
                with zipfile.ZipFile(surface_file, "r") as zip_ref:
                    nc_names = [n for n in zip_ref.namelist() if n.endswith(".nc")]
                    if not nc_names:
                        logger.error(f"No .nc file found in surface ZIP: {surface_file}")
                        return {}
                    if len(nc_names) == 1:
                        with zip_ref.open(nc_names[0]) as src, open(extracted_surface_file, "wb") as dst:
                            dst.write(src.read())
                    else:
                        # Multiple nc files in ZIP (CDS split by month or day-group).
                        # Extract all, concatenate along the time dimension, save as one file.
                        logger.warning(
                            f"Surface ZIP contains {len(nc_names)} nc files — concatenating: {nc_names}"
                        )
                        import io
                        ds_parts = []
                        for nc_name in sorted(nc_names):
                            with zip_ref.open(nc_name) as src:
                                data_bytes = src.read()
                            # Write to a temp file so xarray can open it with netcdf4 engine
                            with tempfile.NamedTemporaryFile(suffix=".nc", delete=False) as part_tmp:
                                part_tmp.write(data_bytes)
                                part_path = part_tmp.name
                            try:
                                ds_part = xr.open_dataset(part_path, engine="netcdf4")
                                ds_part = _normalize_time(ds_part)
                                ds_parts.append(ds_part)
                            except Exception as e:
                                logger.warning(f"Could not open part {nc_name}: {e}")
                            finally:
                                try:
                                    os.unlink(part_path)
                                except Exception:
                                    pass
                        if not ds_parts:
                            logger.error("No valid nc parts found in surface ZIP")
                            return {}

                        # CDS splits ZIP files in two ways:
                        #   (a) By time  — each part covers different dates (cross-month request)
                        #   (b) By variable — each part covers the same dates but different vars
                        # Detect by checking whether the time axes overlap.
                        all_times = [set(ds["time"].values.tolist()) for ds in ds_parts]
                        times_overlap = len(all_times[0].intersection(*all_times[1:])) > 0 if len(all_times) > 1 else False

                        if times_overlap:
                            # Variable-split: merge datasets (combines variables side-by-side).
                            # Use compat='override' to ignore metadata-only conflicts (e.g. 'expver').
                            logger.warning(
                                f"ZIP parts share the same time axis — merging variables from {len(ds_parts)} parts"
                            )
                            merged_ds = xr.merge(ds_parts, join="inner", compat="override")
                        else:
                            # Time-split: concatenate along time axis
                            merged_ds = xr.concat(ds_parts, dim="time")

                        # Ensure monotonic time index (required by resample).
                        merged_ds = merged_ds.sortby("time")
                        # Drop duplicate timestamps if any remain.
                        _, unique_idx = np.unique(merged_ds["time"].values, return_index=True)
                        if len(unique_idx) < len(merged_ds["time"]):
                            logger.warning(
                                f"Dropping {len(merged_ds['time']) - len(unique_idx)} "
                                "duplicate time steps after ZIP merge"
                            )
                            merged_ds = merged_ds.isel(time=unique_idx)
                        merged_ds.to_netcdf(extracted_surface_file)
                        for ds_part in ds_parts:
                            ds_part.close()
            else:
                extracted_surface_file = surface_file

            logger.info(f"Loading surface data from: {extracted_surface_file}")

            with xr.open_dataset(extracted_surface_file, engine="netcdf4") as ds_land:
                ds_land = _normalize_time(ds_land)

                lats = ds_land.latitude.values
                lons = ds_land.longitude.values

                # Compute catchment weights (returns None if no polygon / no intersection)
                weights = self.calculate_cell_weights(lats, lons, catchment_polygon)

                if weights is not None:
                    # ── Catchment-weighted path ──────────────────────────────────────
                    logger.info(f"Using catchment-weighted aggregation ({(weights > 0).sum()} cells)")
                    weights_da = xr.DataArray(
                        weights,
                        coords={"latitude": ds_land.latitude, "longitude": ds_land.longitude},
                        dims=["latitude", "longitude"]
                    )

                    # Temporal aggregation first (keep spatial dims)
                    ds_land_daily = xr.Dataset()
                    for var in ds_land.data_vars:
                        if var == "tp":
                            ds_land_daily[var] = ds_land[var].resample(time="1D").sum()
                        else:
                            ds_land_daily[var] = ds_land[var].resample(time="1D").mean()

                    # Weighted spatial aggregation → one scalar per variable per day
                    ds_land_agg = xr.Dataset()
                    for var in ds_land_daily.data_vars:
                        ds_land_agg[var] = (ds_land_daily[var] * weights_da).sum(
                            dim=["latitude", "longitude"]
                        )

                    df_land = ds_land_agg.to_dataframe().reset_index()
                    logger.info(f"Surface variables after catchment aggregation: {list(ds_land_agg.data_vars)}")

                    # ── Pressure data: interpolate to surface grid, then apply same weights
                    ds_q_daily = None
                    if pressure_file:
                        logger.info(f"Loading pressure data from: {pressure_file}")
                        with xr.open_dataset(pressure_file, engine="netcdf4") as ds_q:
                            ds_q = _normalize_time(ds_q)
                            var_name = (
                                "q" if "q" in ds_q.data_vars
                                else "specific_humidity" if "specific_humidity" in ds_q.data_vars
                                else None
                            )
                            if var_name:
                                # Interpolate pressure grid → surface grid resolution
                                q_interp = ds_q[var_name].interp(
                                    latitude=ds_land.latitude,
                                    longitude=ds_land.longitude,
                                    method="linear"
                                )
                                logger.info(f"Interpolated pressure to surface grid ({len(lats)}×{len(lons)})")
                                q_daily = q_interp.resample(time="1D").mean()
                                q_agg = (q_daily * weights_da).sum(dim=["latitude", "longitude"])
                                ds_q_daily = q_agg.to_dataset(name="q")
                            else:
                                logger.warning("No 'q' or 'specific_humidity' in pressure file")

                else:
                    # ── Nearest-point fallback ──────────────────────────────────────
                    logger.info(f"No catchment polygon — using nearest-point at ({station_lat}, {station_lon})")
                    ds_land_point = ds_land.sel(
                        latitude=station_lat, longitude=station_lon, method="nearest"
                    )
                    logger.info(f"Surface variables at nearest point: {list(ds_land_point.data_vars)}")
                    for var in ds_land_point.data_vars:
                        logger.info(f"  {var}: {ds_land_point[var].values.flatten()[:5]}")

                    ds_land_daily = xr.Dataset()
                    for var in ds_land_point.data_vars:
                        if var == "tp":
                            ds_land_daily[var] = ds_land_point[var].resample(time="1D").sum()
                        else:
                            ds_land_daily[var] = ds_land_point[var].resample(time="1D").mean()

                    df_land = ds_land_daily.to_dataframe().reset_index()

                    # Pressure: nearest point
                    ds_q_daily = None
                    if pressure_file:
                        logger.info(f"Loading pressure data from: {pressure_file}")
                        with xr.open_dataset(pressure_file, engine="netcdf4") as ds_q:
                            ds_q = _normalize_time(ds_q)
                            var_name = (
                                "q" if "q" in ds_q.data_vars
                                else "specific_humidity" if "specific_humidity" in ds_q.data_vars
                                else None
                            )
                            if var_name:
                                q_point = ds_q[var_name].sel(
                                    latitude=station_lat, longitude=station_lon, method="nearest"
                                )
                                q_daily_arr = q_point.resample(time="1D").mean()
                                ds_q_daily = q_daily_arr.to_dataset(name="q")
                            else:
                                logger.warning("No 'q' or 'specific_humidity' in pressure file")

                # ── Merge surface + pressure DataFrames ─────────────────────────
                if ds_q_daily is not None:
                    df_q = ds_q_daily.to_dataframe().reset_index()
                    merged = pd.merge(df_land, df_q[["time", "q"]], on="time", how="inner")
                    logger.info(f"Merged pressure (q) data: {len(merged)} rows")
                else:
                    merged = df_land.copy()

                merged["time"] = pd.to_datetime(merged["time"], errors="coerce")
                merged = merged.dropna(subset=["time"])
                merged["date"] = merged["time"].dt.date

                result_data = {}
                for _, row in merged.iterrows():
                    date_str = row["date"].strftime("%Y-%m-%d")
                    logger.info(
                        f"[{date_str}] t2m={row.get('t2m')}, tp={row.get('tp')}, "
                        f"u10={row.get('u10')}, v10={row.get('v10')}, "
                        f"q={row.get('q')}, swvl1={row.get('swvl1')}"
                    )
                    specific_humidity_value = float(row["q"]) if "q" in row and not pd.isna(row["q"]) else None
                    soil_moisture_value = float(row["swvl1"]) if "swvl1" in row and not pd.isna(row["swvl1"]) else None
                    data = {
                        "temperature_2m": float(row["t2m"]) if "t2m" in row and not pd.isna(row["t2m"]) else None,
                        "total_precipitation": float(row["tp"]) if "tp" in row and not pd.isna(row["tp"]) else None,
                        "u_component_10m": float(row["u10"]) if "u10" in row and not pd.isna(row["u10"]) else None,
                        "v_component_10m": float(row["v10"]) if "v10" in row and not pd.isna(row["v10"]) else None,
                        "specific_humidity": specific_humidity_value,
                        "soil_moisture": soil_moisture_value,
                        "is_complete": True,
                    }
                    if all(v is None or v == 0.0 for v in list(data.values())[:-1]):
                        logger.warning(f"All values zero/null for {date_str}")
                        data["is_complete"] = False
                    result_data[date_str] = data

            if extracted_surface_file != surface_file:
                os.unlink(extracted_surface_file)

            mode = "catchment-weighted" if weights is not None else "nearest-point"
            logger.info(f"Processed {len(result_data)} days [{mode}] for {start_date}->{end_date}")
            return result_data

        except Exception as e:
            import traceback as _tb
            logger.error(
                f"Error in ERA5 processing for {start_date}->{end_date}: {e}\n"
                + _tb.format_exc()
            )
            return self._process_netcdf_file_simple(surface_file or pressure_file, start_date, end_date)


    def _process_netcdf_file_simple(self, filename, start_date, end_date):
                """Process NetCDF file and extract daily data for date range"""
                if not xr:
                    raise ImportError("xarray is required for ERA5 processing")
                
                try:
                    import zipfile
                    import glob
                    import tempfile
                    
                    actual_nc_file = filename
                    if zipfile.is_zipfile(filename):
                        logger.info(f"Downloaded file is a ZIP, extracting...")
                        with zipfile.ZipFile(filename, 'r') as zip_ref:
                            extract_dir = tempfile.mkdtemp()
                            zip_ref.extractall(extract_dir)
                            nc_files = glob.glob(os.path.join(extract_dir, "*.nc"))
                            if nc_files:
                                actual_nc_file = nc_files[0]
                                logger.info(f"Found NetCDF file: {actual_nc_file}")
                            else:
                                raise ValueError("No NetCDF file found in downloaded ZIP")
                    
                    if not os.path.exists(actual_nc_file):
                        raise FileNotFoundError(f"NetCDF file not found: {actual_nc_file}")
                    
                    file_size = os.path.getsize(actual_nc_file)
                    if file_size == 0:
                        raise ValueError(f"Downloaded NetCDF file is empty: {actual_nc_file}")
                    
                    logger.info(f"Processing NetCDF file: {actual_nc_file} (size: {file_size} bytes)")
                    
                    try:
                        ds = xr.open_dataset(actual_nc_file, engine='netcdf4')
                        logger.info("Successfully opened with netcdf4 engine")
                    except:
                        try:
                            ds = xr.open_dataset(actual_nc_file, engine='h5netcdf')
                            logger.info("Successfully opened with h5netcdf engine")
                        except:
                            ds = xr.open_dataset(actual_nc_file)
                            logger.info("Successfully opened with default engine")
                    
                    result_data = {}
                    time_dim = next((dim for dim in ds.dims if 'time' in dim.lower()), None)
                    if time_dim is None:
                        raise ValueError(f"No time dimension found in dataset. Available dimensions: {list(ds.dims.keys())}")
                    
                    logger.info(f"Using time dimension: {time_dim}")
                    
                    time_slice = ds.sel({time_dim: slice(start_date, end_date)})
                    if self.debug_mode:
                        logger.debug(f"Time slice data: {time_slice[time_dim].values}")
                    
                    for var_name in ds.data_vars:
                        if var_name in ['t2m', 'u10', 'v10', 'tp', 'q']:
                            var_data = time_slice[var_name].mean(dim=['latitude', 'longitude'])
                            if self.debug_mode:
                                logger.debug(f"Processed {var_name} values: {var_data.values}")
                            
                            hourly_data = {}
                            time_values = getattr(var_data, time_dim).values
                            for i, time_val in enumerate(time_values):
                                dt = pd.to_datetime(time_val)
                                date_str = dt.strftime('%Y-%m-%d')
                                if date_str not in result_data:
                                    result_data[date_str] = {}
                                result_data[date_str][var_name] = float(var_data.values[i]) if not np.isnan(var_data.values[i]) else None
                            
                            if all(v is None or v == 0.0 for d in result_data.values() for v in d.values()):
                                logger.warning(f"Invalid data for {var_name}: all values zero/null")
                    
                    ds.close()
                    
                    if actual_nc_file != filename and 'temp' in actual_nc_file:
                        import shutil
                        shutil.rmtree(os.path.dirname(actual_nc_file))
                        logger.info("Cleaned up extracted temporary files")
                    
                    return result_data
                    
                except Exception as e:
                    logger.error(f"Error processing NetCDF file {filename}: {e}")
                    raise        
    
    def _simulate_coordinate_data(self, latitude, longitude, start_date, end_date, variables=None):
        """Generate simulated ERA5 data for specific coordinates"""
        if variables is None:
            variables = self.surface_variables + self.pressure_variables
        
        result_data = {}
        total_days = (end_date - start_date).days + 1
        
        for date in pd.date_range(start_date, end_date):
            date_str = date.strftime('%Y-%m-%d')
            result_data[date_str] = {}
            for var in variables:
                if var == '2m_temperature':
                    day_of_year = date.timetuple().tm_yday
                    seasonal_temp = 15 + 10 * np.sin(2 * np.pi * day_of_year / 365)
                    noise = np.random.normal(0, 2)
                    result_data[date_str][var] = seasonal_temp + noise
                elif var == 'total_precipitation':
                    result_data[date_str][var] = max(0, np.random.exponential(0.5) if np.random.random() < 0.1 else 0)
                elif var in ['10m_u_component_of_wind', '10m_v_component_of_wind']:
                    result_data[date_str][var] = np.random.normal(0, 3)
                elif var == 'specific_humidity':
                    day_of_year = date.timetuple().tm_yday
                    seasonal_humidity = 0.008 + 0.004 * np.sin(2 * np.pi * day_of_year / 365)
                    result_data[date_str][var] = max(0.001, seasonal_humidity + np.random.normal(0, 0.001))
                elif var == 'volumetric_soil_water_layer_1':
                    day_of_year = date.timetuple().tm_yday
                    # Soil moisture: higher in wet season, lower in dry season (range 0.1-0.4)
                    seasonal_sm = 0.25 + 0.15 * np.sin(2 * np.pi * (day_of_year + 30) / 365)
                    result_data[date_str][var] = float(np.clip(seasonal_sm + np.random.normal(0, 0.02), 0.05, 0.5))
        
        logger.info(f"Generated simulated ERA5 data for coordinates ({latitude}, {longitude})")
        return result_data
    
    def download_era5_data(self, station, start_date, end_date):
        """
        Download ERA5 data for a station and date range
        """
        if self.simulate_mode:
            return self._simulate_era5_data(station, start_date, end_date)
        
        try:
            if not self.api_key:
                raise Exception("No CDS API key found.")
            
            base_dir = os.path.join(settings.MEDIA_ROOT, 'era5_data', station.station_id)
            surface_dir = os.path.join(base_dir, 'surface')
            pressure_dir = os.path.join(base_dir, 'pressure')
            
            os.makedirs(surface_dir, exist_ok=True)
            os.makedirs(pressure_dir, exist_ok=True)
            
            surface_success = self._download_surface_data(station, start_date, end_date, surface_dir)
            pressure_success = self._download_pressure_data(station, start_date, end_date, pressure_dir)
            
            if surface_success and pressure_success:
                return self._process_and_merge_data(station, start_date, end_date, surface_dir, pressure_dir)
            else:
                logger.error(f"Failed to download ERA5 data for {station.name}")
                return False
                
        except Exception as e:
            logger.error(f"Error downloading ERA5 data: {e}")
            return False
    
    def _download_surface_data_for_area(self, area, start_date, end_date, variables):
        """Download surface data for a specific area"""
        try:
            variable_mapping = {
                '2m_temperature': '2m_temperature',
                'total_precipitation': 'total_precipitation', 
                '10m_u_component_of_wind': '10m_u_component_of_wind',
                '10m_v_component_of_wind': '10m_v_component_of_wind'
            }
            
            era5_variables = [variable_mapping[var] for var in variables if var in variable_mapping]
            if not era5_variables:
                logger.warning(f"No valid surface variables found in {variables}")
                return {}
            
            date_list = pd.date_range(start=start_date, end=end_date, freq='D').strftime('%Y-%m-%d').tolist()
            request = {
                "variable": era5_variables,
                "year": sorted(list(set([d.split('-')[0] for d in date_list]))),
                "month": sorted(list(set([d.split('-')[1] for d in date_list]))),
                "day": sorted(list(set([d.split('-')[2] for d in date_list]))),
                "time": [f"{h:02d}:00" for h in range(24)],
                "data_format": "netcdf",
                "area": area,
            }
            
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.nc', delete=False) as tmp_file:
                tmp_filename = tmp_file.name
            
            retry_count = 0
            while retry_count < self.max_retries:
                try:
                    self.cds_client.retrieve("reanalysis-era5-land", request, tmp_filename)
                    break
                except Exception as e:
                    retry_count += 1
                    if retry_count >= self.max_retries:
                        raise e
                    logger.warning(f"Surface download attempt {retry_count} failed, retrying in {self.retry_delay}s...")
                    import time
                    time.sleep(self.retry_delay)
            
            result_data = self._process_netcdf_file_simple(tmp_filename, start_date, end_date)
            os.unlink(tmp_filename)
            return result_data
            
        except Exception as e:
            logger.error(f"Error downloading surface data for area {area}: {e}")
            raise
    
    def _download_pressure_data_for_area(self, area, start_date, end_date, variables):
        """Download pressure level data for a specific area"""
        try:
            variable_mapping = {
                'specific_humidity': 'specific_humidity'
            }
            
            era5_variables = [variable_mapping[var] for var in variables if var in variable_mapping]
            if not era5_variables:
                logger.warning(f"No valid pressure variables found in {variables}")
                return {}
            
            date_list = pd.date_range(start=start_date, end=end_date, freq='D').strftime('%Y-%m-%d').tolist()
            request = {
                "product_type": "reanalysis",
                "variable": era5_variables,
                "pressure_level": ["925"],
                "year": sorted(list(set([d.split('-')[0] for d in date_list]))),
                "month": sorted(list(set([d.split('-')[1] for d in date_list]))),
                "day": sorted(list(set([d.split('-')[2] for d in date_list]))),
                "time": [f"{h:02d}:00" for h in range(24)],
                "data_format": "netcdf",
                "area": area,
                "grid": [0.1, 0.1],   # 0.1° x 0.1° grid resolution
            }
            
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.nc', delete=False) as tmp_file:
                tmp_filename = tmp_file.name
            
            retry_count = 0
            while retry_count < self.max_retries:
                try:
                    self.cds_client.retrieve("reanalysis-era5-pressure-levels", request, tmp_filename)
                    break
                except Exception as e:
                    retry_count += 1
                    if retry_count >= self.max_retries:
                        raise e
                    logger.warning(f"Pressure download attempt {retry_count} failed, retrying in {self.retry_delay}s...")
                    import time
                    time.sleep(self.retry_delay)
            
            result_data = self._process_netcdf_file_simple(tmp_filename, start_date, end_date)
            os.unlink(tmp_filename)
            return result_data
            
        except Exception as e:
            logger.error(f"Error downloading pressure data for area {area}: {e}")
            raise

    def _download_surface_data(self, station, start_date, end_date, output_dir):
        """Download surface data using daily batches"""
        try:
            logger.info(f"[DEBUG] Downloading surface data to directory: {os.path.abspath(output_dir)}")
            # Use station.era5_download_area so the area covers the full catchment polygon
            # (priority: admin custom area → catchment polygon bounds → gauge ± 0.5°)
            area = station.era5_download_area
            logger.info(f"Surface download area for {station.name}: {area}")
            progress = tqdm(pd.date_range(start_date, end_date, freq='D'), desc="Downloading surface data") if tqdm else pd.date_range(start_date, end_date, freq='D')
            for day in progress:
                year = str(day.year)
                month = f"{day.month:02d}"
                day_str = f"{day.day:02d}"
                logger.info(f"Requesting surface data for {year}-{month}-{day_str}")
                request = {
                    "variable": [
                        "2m_temperature",
                        "10m_u_component_of_wind",
                        "10m_v_component_of_wind",
                        "total_precipitation",
                        "volumetric_soil_water_layer_1"    # soil moisture (0-7cm depth)
                    ],
                    "year": year,
                    "month": month,
                    "day": [day_str],
                    "time": [f"{h:02d}:00" for h in range(24)],
                    "data_format": "netcdf",
                    "area": area,
                }
                filename = os.path.join(output_dir, f"era5_land_{year}_{month}_{day_str}.nc")
                logger.info(f"[DEBUG] Surface data file path: {os.path.abspath(filename)}")
                if os.path.exists(filename):
                    logger.info(f"Surface data already exists: {filename}")
                else:
                    self.cds_client.retrieve("reanalysis-era5-land", request, filename)
                    logger.info(f"Downloaded surface data: {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Error downloading surface data: {e}")
            return False
    
    def _download_pressure_data(self, station, start_date, end_date, output_dir):
        """Download pressure data using monthly batches"""
        try:
            # Use station's era5_download_area (respects custom area or auto-generates from location)
            area = station.era5_download_area
            logger.info(f"Pressure download area for {station.name}: {area}")

            progress = tqdm(pd.date_range(start_date, end_date, freq='D'), desc="Downloading pressure data") if tqdm else pd.date_range(start_date, end_date, freq='D')
            for day in progress:
                year = str(day.year)
                month = f"{day.month:02d}"
                day_str = f"{day.day:02d}"
                logger.info(f"Requesting specific humidity for {year}-{month}-{day_str} at 925 hPa")
                request = {
                    "product_type": "reanalysis",
                    "variable": ["specific_humidity"],
                    "pressure_level": ["925"],
                    "year": year,
                    "month": month,
                    "day": [day_str],
                    "time": [f"{h:02d}:00" for h in range(24)],
                    "data_format": "netcdf",
                    "area": area,
                    "grid": [0.1, 0.1],   # 0.1° x 0.1° grid resolution
                }
                filename = os.path.join(output_dir, f"era5_q925_{year}_{month}_{day_str}.nc")
                if os.path.exists(filename):
                    logger.info(f"Pressure data already exists: {filename}")
                else:
                    self.cds_client.retrieve("reanalysis-era5-pressure-levels", request, filename)
                    logger.info(f"Downloaded pressure data: {filename}")
            return True
            
        except Exception as e:
            logger.error(f"Error downloading pressure data: {e}")
            return False
    
    def _process_and_merge_data(self, station, start_date, end_date, surface_dir, pressure_dir):
        """Process downloaded NetCDF files and merge into database records"""
        try:
            surface_data = self._process_surface_files(surface_dir, start_date, end_date, station=station)
            pressure_data = self._process_pressure_files(pressure_dir, start_date, end_date, station=station)
            return self._merge_and_save_data(station, surface_data, pressure_data)
            
        except Exception as e:
            logger.error(f"Error processing and merging data: {e}")
            return False
    
    def _process_surface_files(self, surface_dir, start_date, end_date, station=None):
        """
        Process surface ERA5 NetCDF files into daily scalar values per variable.

        When station.catchment_polygon is available: area-weighted spatial average over
        catchment grid cells (hydrologically correct).
        Fallback: nearest-point extraction at station.location coordinates.
        """
        logger.info(f"Processing surface files in: {os.path.abspath(surface_dir)}")
        import zipfile
        import tempfile

        catchment_polygon = station.catchment_polygon if station else None
        station_lat = station.location.y if station and station.location else None
        station_lon = station.location.x if station and station.location else None

        surface_data = {}
        for filename in os.listdir(surface_dir):
            if not (filename.endswith('.nc') and filename.startswith('era5_land_')):
                continue

            filepath = os.path.join(surface_dir, filename)
            logger.info(f"Processing surface file: {os.path.abspath(filepath)}")
            temp_nc_path = None
            try:
                # File validation
                file_size = os.path.getsize(filepath)
                if file_size < 100:
                    logger.error(f"{filename} too small ({file_size} bytes), skipping")
                    continue

                with open(filepath, 'rb') as f:
                    magic = f.read(3)

                if magic == b'PK\x03':
                    # ZIP archive — extract inner .nc file
                    logger.info(f"{filename} is a ZIP archive, extracting...")
                    with zipfile.ZipFile(filepath, 'r') as zip_ref:
                        nc_files = [f for f in zip_ref.namelist() if f.endswith('.nc')]
                        if not nc_files:
                            logger.error(f"No .nc file found in zip: {filename}")
                            continue
                        with zip_ref.open(nc_files[0]) as nc_file:
                            with tempfile.NamedTemporaryFile(suffix='.nc', delete=False) as tmp_nc:
                                tmp_nc.write(nc_file.read())
                                temp_nc_path = tmp_nc.name
                    nc_path = temp_nc_path
                elif magic in [b'CDF', b'NC\x03', b'NC\x02']:
                    nc_path = filepath
                else:
                    logger.error(f"{filename} unrecognised file format (magic={magic}), skipping")
                    continue

                ds = xr.open_dataset(nc_path, engine='netcdf4')

                lats = ds.latitude.values
                lons = ds.longitude.values

                # Compute catchment weights
                weights = self.calculate_cell_weights(lats, lons, catchment_polygon)

                # Temporal aggregation (keep spatial dims)
                daily_ds = xr.Dataset()
                for var in ['t2m', 'u10', 'v10', 'swvl1']:
                    if var in ds.data_vars:
                        daily_ds[var] = ds[var].resample(valid_time='1D').mean()
                if 'tp' in ds.data_vars:
                    daily_ds['tp'] = ds['tp'].resample(valid_time='1D').sum()

                if weights is not None:
                    # ── Catchment-weighted spatial aggregation ─────────────────
                    logger.info(f"Applying catchment-weighted aggregation ({(weights > 0).sum()} cells)")
                    weights_da = xr.DataArray(
                        weights,
                        coords={'latitude': ds.latitude, 'longitude': ds.longitude},
                        dims=['latitude', 'longitude']
                    )
                    agg_ds = xr.Dataset()
                    for var in daily_ds.data_vars:
                        agg_ds[var] = (daily_ds[var] * weights_da).sum(
                            dim=['latitude', 'longitude']
                        )
                    df = agg_ds.to_dataframe().reset_index()

                elif station_lat is not None and station_lon is not None:
                    # ── Nearest-point fallback ─────────────────────────────────
                    logger.info(f"No catchment polygon — nearest point at ({station_lat}, {station_lon})")
                    point_ds = xr.Dataset()
                    for var in daily_ds.data_vars:
                        point_ds[var] = daily_ds[var].sel(
                            latitude=station_lat, longitude=station_lon, method='nearest'
                        )
                    df = point_ds.to_dataframe().reset_index()

                else:
                    # ── Last-resort fallback (no station info) ─────────────────
                    logger.warning("No station location or catchment — using spatial mean")
                    mean_ds = xr.Dataset()
                    for var in daily_ds.data_vars:
                        mean_ds[var] = daily_ds[var].mean(dim=['latitude', 'longitude'])
                    df = mean_ds.to_dataframe().reset_index()

                logger.info(f"Surface dataframe columns: {list(df.columns)}, rows: {len(df)}")

                for _, row in df.iterrows():
                    date_key = row['valid_time'].date()
                    if start_date <= date_key <= end_date:
                        surface_data[date_key] = {
                            't2m': row.get('t2m', np.nan),
                            'u10': row.get('u10', np.nan),
                            'v10': row.get('v10', np.nan),
                            'tp': row.get('tp', np.nan),
                            'swvl1': row.get('swvl1', np.nan)
                        }

                ds.close()

            except Exception as e:
                logger.error(f"Error processing surface file {filename}: {e}")
                try:
                    with open(filepath, 'rb') as f:
                        head = f.read(64)
                    logger.error(f"First 64 bytes of {filename}: {head}")
                except Exception:
                    pass
            finally:
                if temp_nc_path and os.path.exists(temp_nc_path):
                    try:
                        os.unlink(temp_nc_path)
                    except Exception:
                        pass

        logger.info(f"Surface data extracted: {len(surface_data)} days")
        return surface_data
    
    def _process_pressure_files(self, pressure_dir, start_date, end_date, station=None):
        """
        Process pressure ERA5 NetCDF files into daily scalar specific humidity values.

        When station.catchment_polygon is available: area-weighted spatial average.
        Fallback: nearest-point extraction at station.location coordinates.
        """
        catchment_polygon = station.catchment_polygon if station else None
        station_lat = station.location.y if station and station.location else None
        station_lon = station.location.x if station and station.location else None

        pressure_data = {}
        for filename in os.listdir(pressure_dir):
            if not (filename.endswith('.nc') and filename.startswith('era5_q925_')):
                continue
            filepath = os.path.join(pressure_dir, filename)
            try:
                ds = xr.open_dataset(filepath)

                lats = ds.latitude.values
                lons = ds.longitude.values

                # Catchment weights for this pressure grid
                weights = self.calculate_cell_weights(lats, lons, catchment_polygon)

                # Temporal aggregation (keep spatial dims)
                q_daily = ds['q'].resample(valid_time='1D').mean()

                if weights is not None:
                    # Weighted spatial aggregation → catchment-mean q per day
                    weights_da = xr.DataArray(
                        weights,
                        coords={'latitude': ds.latitude, 'longitude': ds.longitude},
                        dims=['latitude', 'longitude']
                    )
                    q_agg = (q_daily * weights_da).sum(dim=['latitude', 'longitude'])
                    df = q_agg.to_dataframe(name='q').reset_index()
                    logger.info(f"Pressure weighted aggregation applied for {filename}")

                elif station_lat is not None and station_lon is not None:
                    # Nearest-point fallback
                    q_point = q_daily.sel(latitude=station_lat, longitude=station_lon, method='nearest')
                    df = q_point.to_dataframe(name='q').reset_index()
                    logger.info(f"Pressure nearest-point fallback for {filename}")

                else:
                    # Last-resort: spatial mean
                    q_mean = q_daily.mean(dim=['latitude', 'longitude'])
                    df = q_mean.to_dataframe(name='q').reset_index()
                    logger.warning(f"Pressure spatial mean fallback for {filename}")

                for _, row in df.iterrows():
                    date_key = row['valid_time'].date()
                    if start_date <= date_key <= end_date:
                        pressure_data[date_key] = row.get('q', np.nan)

                ds.close()
            except Exception as e:
                logger.error(f"Error processing pressure file {filename}: {e}")

        logger.info(f"Pressure data extracted: {len(pressure_data)} days")
        return pressure_data
    
    def _merge_and_save_data(self, station, surface_data, pressure_data):
        """Merge surface and pressure data and save to database"""
        try:
            saved_count = 0
            all_dates = set(surface_data.keys()) | set(pressure_data.keys())
            
            for date_key in all_dates:
                surface_values = surface_data.get(date_key, {})
                t2m = surface_values.get('t2m')
                u10 = surface_values.get('u10')
                v10 = surface_values.get('v10')
                tp = surface_values.get('tp')
                swvl1 = surface_values.get('swvl1')
                q = pressure_data.get(date_key)
                logger.info(f"[save] {date_key}: t2m={t2m}, u10={u10}, v10={v10}, tp={tp}, q={q}, swvl1={swvl1}")
                if all(v is None or np.isnan(v) for v in [t2m, u10, v10, tp, q, swvl1]):
                    logger.warning(f"Skipping {date_key} for {station.name}: all values null/NaN")
                    continue
                era5_record, created = ERA5Data.objects.get_or_create(
                    station=station,
                    date=date_key,
                    defaults={
                        'temperature_2m': t2m if t2m is not None and not np.isnan(t2m) else None,
                        'u_component_10m': u10 if u10 is not None and not np.isnan(u10) else None,
                        'v_component_10m': v10 if v10 is not None and not np.isnan(v10) else None,
                        'total_precipitation': tp if tp is not None and not np.isnan(tp) else None,
                        'specific_humidity': q if q is not None and not np.isnan(q) else None,
                        'soil_moisture': swvl1 if swvl1 is not None and not np.isnan(swvl1) else None,
                        'data_source': 'ERA5_CDS',
                        'download_timestamp': timezone.now(),
                        'processing_status': 'processed',
                        'is_complete': True
                    }
                )
                
                if not created:
                    era5_record.temperature_2m = t2m if t2m is not None and not np.isnan(t2m) else era5_record.temperature_2m
                    era5_record.u_component_10m = u10 if u10 is not None and not np.isnan(u10) else era5_record.u_component_10m
                    era5_record.v_component_10m = v10 if v10 is not None and not np.isnan(v10) else era5_record.v_component_10m
                    era5_record.total_precipitation = tp if tp is not None and not np.isnan(tp) else era5_record.total_precipitation
                    era5_record.specific_humidity = q if q is not None and not np.isnan(q) else era5_record.specific_humidity
                    era5_record.soil_moisture = swvl1 if swvl1 is not None and not np.isnan(swvl1) else era5_record.soil_moisture
                    era5_record.processing_status = 'processed'
                    era5_record.is_complete = True
                    era5_record.save()
                
                saved_count += 1
            
            logger.info(f"Successfully processed and saved {saved_count} ERA5 records for {station.name}")
            return True
            
        except Exception as e:
            logger.error(f"Error merging and saving data: {e}")
            return False
    
    def _simulate_era5_data(self, station, start_date, end_date):
        """Generate simulated ERA5 data for development/testing"""
        try:
            current_date = start_date
            while current_date <= end_date:
                era5_data, created = ERA5Data.objects.get_or_create(
                    station=station,
                    date=current_date,
                    defaults={
                        'temperature_2m': 15 + 10 * np.sin(2 * np.pi * current_date.timetuple().tm_yday / 365) + np.random.normal(0, 3),
                        'total_precipitation': max(0, np.random.exponential(2) + 5 * np.sin(2 * np.pi * (current_date.timetuple().tm_yday + 180) / 365)),
                        'u_component_10m': np.random.normal(0, 5),
                        'v_component_10m': np.random.normal(0, 5),
                        'specific_humidity': max(0.001, 0.01 + 0.005 * np.sin(2 * np.pi * current_date.timetuple().tm_yday / 365) + np.random.normal(0, 0.002)),
                        'soil_moisture': float(np.clip(0.25 + 0.15 * np.sin(2 * np.pi * (current_date.timetuple().tm_yday + 30) / 365) + np.random.normal(0, 0.02), 0.05, 0.5)),
                        'data_source': 'ERA5_Simulated',
                        'download_timestamp': timezone.now(),
                        'is_complete': True,
                        'processing_status': 'validated'
                    }
                )
                current_date += timedelta(days=1)
                
            logger.info(f"Simulated ERA5 data generated for {station.name} from {start_date} to {end_date}")
            return True
            
        except Exception as e:
            logger.error(f"Error generating simulated ERA5 data: {e}")
            return False
    
    def preprocess_sequence_data(self, station, start_date, end_date, use_extended_features=True):
        """Prepare ERA5 sequence data for model input (90-day sequences).

        Args:
            use_extended_features: When True (default) returns a 6-feature vector
                [t2m, u10, v10, tp, q, soil_moisture] using get_extended_feature_vector().
                When False returns the legacy 5-feature vector [t2m, u10, v10, tp, q].
        """
        try:
            era5_records = ERA5Data.objects.filter(
                station=station,
                date__range=[start_date, end_date],
                is_complete=True,
                processing_status__in=['processed', 'validated']
            ).order_by('date')

            if not era5_records.exists():
                raise ValueError(f"No ERA5 data available for station {station.name} between {start_date} and {end_date}")

            sequence_data = []
            for record in era5_records:
                if use_extended_features:
                    daily_features = record.get_extended_feature_vector()
                else:
                    daily_features = record.get_feature_vector()
                if daily_features is None or all(v == 0.0 for v in daily_features):
                    logger.warning(f"Invalid data for {record.date}: all values zero/null")
                    continue
                sequence_data.append(daily_features)

            n_features = 6 if use_extended_features else 5
            logger.info(f"Using {'extended (6-feature)' if use_extended_features else 'legacy (5-feature)'} feature vector for {station.name}")
            
            expected_length = (end_date - start_date).days + 1
            if len(sequence_data) / expected_length < self.min_data_completeness:
                logger.error(f"Insufficient data: {len(sequence_data)}/{expected_length} days")
                raise ValueError("Data completeness below threshold")
            
            # Check for temporal gaps
            dates = [record.date for record in era5_records]
            gaps = [dates[i+1] - dates[i] for i in range(len(dates)-1)]
            max_gap = max((g.days for g in gaps), default=0)
            if max_gap > 3:
                logger.warning(f"Temporal gaps > 3 days detected: max {max_gap} days")
            
            # Validate lead time
            if (date.today() - end_date).days < 45:
                logger.warning(f"Sequence end date {end_date} too recent for 45-day lead time")
            
            sequence_array = np.array(sequence_data)
            if len(sequence_array) != expected_length:
                logger.warning(f"Sequence length mismatch: got {len(sequence_array)}, expected {expected_length}")
                sequence_array = self._interpolate_missing_data(sequence_array, expected_length)
            
            logger.info(f"Preprocessed sequence: {sequence_array.shape} for station {station.name}")
            return sequence_array
            
        except Exception as e:
            logger.error(f"Error preprocessing sequence data: {e}")
            raise
    
    def download_for_station(self, station, start_date, end_date, variables=None):
        """
        Download ERA5 data for a station over a date range
        """
        if not cdsapi:
            raise ImportError("cdsapi is required for ERA5 downloads")

        if not variables:
            variables = self.model_features

        if end_date > date.today() - timedelta(days=self.era5_delay_days):
            raise ValueError(f"Cannot download data beyond {date.today() - timedelta(days=self.era5_delay_days)} (ERA5 delay: {self.era5_delay_days} days)")

        if start_date > end_date:
            raise ValueError(f"Start date {start_date} is after end date {end_date}")

        area = station.era5_download_area
        logger.info(f"Downloading ERA5 data for {station.name} from {start_date} to {end_date}")

        import calendar as _calendar
        data = {}
        current_date = start_date

        import traceback as _traceback
        while current_date <= end_date:
            # Cap chunk at end of current calendar month so the CDS request always covers a
            # single month.  Cross-month requests cause CDS to return a ZIP with separate
            # per-month netCDF files; the extraction code reads only nc_names[0] and silently
            # drops the other months, producing NULL surface values for the skipped dates.
            _last_day = _calendar.monthrange(current_date.year, current_date.month)[1]
            last_day_of_month = current_date.replace(day=_last_day)
            month_end = min(end_date, current_date + timedelta(days=6), last_day_of_month)
            try:
                surface_file = self._download_single_day_surface(area, current_date, month_end, variables)
                pressure_file = None
                if not self.surface_only and any(v in variables for v in ['q', 'specific_humidity']):
                    pressure_file = self._download_single_day_pressure(
                        station, current_date, month_end, variables=['specific_humidity']
                    )
                daily_data = self._process_daily_era5_data(
                    surface_file, pressure_file, current_date, month_end,
                    station.latitude, station.longitude,
                    catchment_polygon=station.catchment_polygon
                )
                if not daily_data:
                    logger.warning(
                        f"Sub-chunk {current_date}->{month_end} returned no data — "
                        "check for ERA5 processing errors above."
                    )
                data.update(daily_data)
            except Exception as _sub_err:
                logger.error(
                    f"Error downloading/processing sub-chunk {current_date}->{month_end}: {_sub_err}\n"
                    + _traceback.format_exc()
                )
                # Continue to next sub-chunk so previously accumulated data is preserved.

            current_date = month_end + timedelta(days=1)

        return data
    
    def _interpolate_missing_data(self, sequence_array, expected_length):
        """Interpolate missing data points in sequence"""
        try:
            from scipy.interpolate import interp1d
            current_length = len(sequence_array)
            if current_length >= expected_length:
                return sequence_array[:expected_length]
            
            x_old = np.arange(current_length)
            x_new = np.linspace(0, current_length - 1, expected_length)
            interpolated_sequence = []
            for feature_idx in range(sequence_array.shape[1]):
                feature_values = sequence_array[:, feature_idx]
                interp_func = interp1d(x_old, feature_values, kind='linear', bounds_error=False, fill_value='extrapolate')
                interpolated_values = interp_func(x_new)
                interpolated_sequence.append(interpolated_values)
            
            result = np.array(interpolated_sequence).T
            logger.info(f"Interpolated sequence from {current_length} to {expected_length} days")
            return result
            
        except ImportError:
            logger.warning("SciPy not available, using simple interpolation")
            return self._simple_interpolate(sequence_array, expected_length)
        except Exception as e:
            logger.error(f"Error interpolating missing data: {e}")
            return self._pad_sequence(sequence_array, expected_length)
    
    def _simple_interpolate(self, sequence_array, expected_length):
        """Simple linear interpolation without scipy"""
        current_length = len(sequence_array)
        if current_length >= expected_length:
            return sequence_array[:expected_length]
        
        result = np.zeros((expected_length, sequence_array.shape[1]))
        for i in range(expected_length):
            old_index = (i * (current_length - 1)) / (expected_length - 1)
            low_idx = int(np.floor(old_index))
            high_idx = min(low_idx + 1, current_length - 1)
            weight = old_index - low_idx
            for feature_idx in range(sequence_array.shape[1]):
                low_val = sequence_array[low_idx, feature_idx]
                high_val = sequence_array[high_idx, feature_idx]
                result[i, feature_idx] = low_val + weight * (high_val - low_val)
        return result
    
    def _pad_sequence(self, sequence_array, expected_length):
        """Pad sequence with last values"""
        current_length = len(sequence_array)
        if current_length >= expected_length:
            return sequence_array[:expected_length]
        
        padding_needed = expected_length - current_length
        last_values = sequence_array[-1:].repeat(padding_needed, axis=0)
        result = np.vstack([sequence_array, last_values])
        return result
    
    def preprocess_sequence_with_dhm_discharge(self, station, start_date, end_date):
        """Build a 7-feature input sequence for the ERA5+CAR pipeline.

        Feature order (must match model training):
            [t2m, u10, v10, tp, q, soil_moisture, Q2_car]

        Q2_car is derived for every day in the window from DHMStage records:
            Q1 = c * (H - a)^b        (rating curve for the reference DHM station)
            Q2 = Q1 * (A2 / A1)       (CAR scaling to this station)

        For days where no DHMStage record exists, the most recent valid Q2 is
        forward-filled.  If no Q2 is available at all (no DHM records), the
        column is filled with 0.0 and a warning is logged.

        Args:
            station: DischargeStation instance (must have rating curve configured)
            start_date: First date of the 90-day input window (date object)
            end_date:   Last date of the 90-day input window (date object)

        Returns:
            np.ndarray of shape (window_days, 7)
        """
        from .models import DHMStage

        # ── 1. ERA5 base (6 features) ─────────────────────────────────────
        era5_records = ERA5Data.objects.filter(
            station=station,
            date__range=[start_date, end_date],
            is_complete=True,
            processing_status__in=['processed', 'validated'],
        ).order_by('date')

        if not era5_records.exists():
            raise ValueError(
                f"No ERA5 data for station {station.name} between {start_date} and {end_date}"
            )

        era5_by_date = {r.date: r.get_extended_feature_vector() for r in era5_records}

        # ── 2. DHM-derived Q2 (1 feature) ─────────────────────────────────
        dhm_records = DHMStage.objects.filter(
            station=station,
            timestamp__date__range=[start_date, end_date],
        ).order_by('timestamp')

        q2_by_date = {}
        for r in dhm_records:
            d = r.timestamp.date()
            # Prefer the stored discharge_q2 (computed at ingest time from the
            # rating curve that was active when the record was saved).  Fall back
            # to on-the-fly computation only if the field is NULL (e.g. old rows
            # inserted before this field existed).
            if r.discharge_q2 is not None:
                q2_by_date[d] = float(r.discharge_q2)
            else:
                q2 = station.compute_discharge_from_stage(r.stage_height)
                if q2 is not None:
                    q2_by_date[d] = float(q2)

        if not q2_by_date:
            logger.warning(
                f"[era5_car] No DHMStage records for {station.name} between "
                f"{start_date} and {end_date}. Q2_car column will be 0.0."
            )

        # ── 3. Assemble day-by-day ─────────────────────────────────────────
        from datetime import timedelta
        all_dates = [
            start_date + timedelta(days=i)
            for i in range((end_date - start_date).days + 1)
        ]

        expected_length = len(all_dates)
        sequence_data = []
        last_q2 = 0.0  # forward-fill seed

        for d in all_dates:
            era5_vec = era5_by_date.get(d)
            if era5_vec is None:
                # Missing ERA5 day — skip (completeness check below will catch it)
                continue

            # Forward-fill Q2 if no DHM record for this day
            if d in q2_by_date:
                last_q2 = q2_by_date[d]

            sequence_data.append(era5_vec + [last_q2])

        if len(sequence_data) / expected_length < self.min_data_completeness:
            raise ValueError(
                f"[era5_car] Insufficient data for {station.name}: "
                f"{len(sequence_data)}/{expected_length} days"
            )

        sequence_array = np.array(sequence_data, dtype=np.float64)

        # Interpolate to exact expected_length if ERA5 gaps caused short sequence
        if len(sequence_array) != expected_length:
            logger.warning(
                f"[era5_car] Sequence length {len(sequence_array)} != {expected_length}; interpolating."
            )
            sequence_array = self._interpolate_missing_data(sequence_array, expected_length)

        logger.info(
            f"[era5_car] Built 7-feature sequence {sequence_array.shape} for {station.name} "
            f"({start_date} → {end_date}). Q2 available for {len(q2_by_date)}/{expected_length} days."
        )
        return sequence_array

    def preprocess_for_model_inference(self, station, start_date, end_date,
                                       training_scaler_path=None, use_extended_features=True):
        """Preprocess input sequence for model inference.

        Dispatches to the correct pipeline based on ``station.prediction_pipeline``:

        * ``'era5_car'``  → :meth:`preprocess_sequence_with_dhm_discharge`
          Returns a 7-feature array [t2m, u10, v10, tp, q, soil_moisture, Q2_car].
          Used for Lower Likhu (and any station with DHM stage data + rating curve).

        * ``'era5_only'`` (default) → :meth:`preprocess_sequence_data`
          Returns a 6-feature array [t2m, u10, v10, tp, q, soil_moisture].
          Used for Mailung (and stations without DHM stage data).

        Args:
            station: DischargeStation instance
            start_date / end_date: Bounds of the 90-day input window
            use_extended_features: Passed to the era5_only branch.
                True (default) → 6-feature; False → legacy 5-feature.
        """
        pipeline = getattr(station, 'prediction_pipeline', 'era5_only')

        if pipeline == 'era5_car':
            logger.info(f"[pipeline=era5_car] {station.name}: assembling 7-feature sequence (ERA5 + CAR Q2)")
            return self.preprocess_sequence_with_dhm_discharge(station, start_date, end_date)

        # Default: era5_only
        logger.info(
            f"[pipeline=era5_only] {station.name}: assembling "
            f"{'6' if use_extended_features else '5'}-feature ERA5 sequence"
        )
        return self.preprocess_sequence_data(station, start_date, end_date,
                                              use_extended_features=use_extended_features)
    
    def download_daily_data(self, station, target_date, fill_gaps=False):
        """Download ERA5 data for a single day or fill gaps"""
        try:
            max_date = date.today() - timedelta(days=self.era5_delay_days)
            if target_date > max_date:
                logger.error(f"Target date {target_date} exceeds maximum allowed date {max_date}")
                return False
            
            logger.info(f"Cron-triggered daily download for {station.name} on {target_date}")
            if fill_gaps:
                status = self.get_download_status(station, target_date - timedelta(days=30), target_date)
                missing_dates = status['missing_dates']
                if missing_dates:
                    logger.info(f"Filling gaps for {station.name}: {missing_dates}")
                    self.download_and_save_era5_data(station, min(missing_dates), max(missing_dates))
            
            if self.simulate_mode:
                logger.info(f"Simulating daily ERA5 data for {station.name} on {target_date}")
                return self._generate_simulated_daily_data(station, target_date)
            
            area = station.era5_download_area
            logger.info(f"Downloading daily ERA5 data for {station.name} on {target_date}")
            
            surface_data = self._download_surface_daily(area, target_date)
            pressure_data = None
            if not self.surface_only:
                pressure_data = self._download_pressure_daily(area, target_date)
            
            daily_data = self._process_daily_data(surface_data, pressure_data, target_date)
            if daily_data:
                self._save_daily_data_to_database(station, target_date, daily_data)
                logger.info(f"Successfully processed daily data for {target_date}")
                
                status = self.get_download_status(station, target_date - timedelta(days=89), target_date)
                if status['complete_days'] < 50:
                    logger.warning(f"Insufficient complete days for {station.name}: {status['complete_days']}/90")
                    return False
                return True
            else:
                logger.error(f"Failed to process daily data for {target_date}")
                return False
                
        except Exception as e:
            logger.error(f"Error downloading daily data for {target_date}: {e}")
            return False
    
    def download_surface_data_only(self, station, target_date):
        """Download only surface data"""
        try:
            original_mode = self.surface_only
            self.surface_only = True
            result = self.download_daily_data(station, target_date)
            self.surface_only = original_mode
            return result
        except Exception as e:
            logger.error(f"Error downloading surface-only data: {e}")
            return False
    
    def download_and_save_era5_data(self, station, start_date, end_date, force=False, days_back=120):
        """Complete download and database save"""
        try:
            logger.info(f"Starting complete ERA5 download for {station.name} from {start_date} to {end_date}")
            if force:
                logger.info(f"Forcing data refresh for {station.name}")
                ERA5Data.objects.filter(station=station, date__range=[start_date, end_date]).delete()
            if days_back:
                start_date = end_date - timedelta(days=days_back - 1)
                logger.info(f"Adjusted start date to {start_date} for {days_back} days back")
            
            max_date = date.today() - timedelta(days=self.era5_delay_days)
            if end_date > max_date:
                logger.warning(f"Adjusting end_date to {max_date} due to ERA5 delay")
                end_date = max_date
            
            if self.simulate_mode:
                return self._simulate_era5_data(station, start_date, end_date)
            
            success_count = 0
            total_days = (end_date - start_date).days + 1
            data = self.download_for_station(station, start_date, end_date)
            
            for date in pd.date_range(start_date, end_date):
                date_str = date.strftime('%Y-%m-%d')
                daily_data = data.get(date_str, {})
                if daily_data.get('is_complete', False) and any(v is not None and v != 0.0 for v in daily_data.values() if v not in [True, False]):
                    ERA5Data.objects.update_or_create(
                        station=station,
                        date=date,
                        defaults={
                            'temperature_2m': daily_data.get('temperature_2m'),
                            'total_precipitation': daily_data.get('total_precipitation'),
                            'u_component_10m': daily_data.get('u_component_10m'),
                            'v_component_10m': daily_data.get('v_component_10m'),
                            'specific_humidity': daily_data.get('specific_humidity'),
                            'soil_moisture': daily_data.get('soil_moisture'),
                            'data_source': 'ERA5_CDS',
                            'download_timestamp': timezone.now(),
                            'processing_status': 'processed',
                            'is_complete': True,
                        }
                    )
                    success_count += 1
                else:
                    logger.warning(f"Skipping database save for {date_str}: incomplete or all-zero data")
            
            success_rate = (success_count / total_days) * 100
            if success_rate < self.min_data_completeness * 100:
                logger.warning(f"Incomplete data: {success_count}/{total_days} days, below {self.min_data_completeness*100}% threshold")
                return False
            logger.info(f"Download complete: {success_count}/{total_days} days ({success_rate:.1f}% success)")
            return success_count > 0
            
        except Exception as e:
            logger.error(f"Error in complete download: {e}")
            return False
    
    def validate_configuration(self):
        """Validate downloader configuration and dependencies"""
        validation = {
            'api_key': self.api_key is not None or self.simulate_mode,
            'dependencies': all([xr, pd, np]),
            'configuration': hasattr(self, 'surface_variables') and hasattr(self, 'model_features'),
            'database': True,
            'errors': []
        }
        
        if not validation['api_key']:
            validation['errors'].append("No API key configured")
        if not validation['dependencies']:
            validation['errors'].append("Missing dependencies: xarray, pandas, or numpy")
        try:
            from .models import ERA5Data
        except Exception as e:
            validation['database'] = False
            validation['errors'].append(f"Database issue: {e}")
        
        return validation
    
    def get_download_status(self, station, start_date, end_date):
        """Get comprehensive download status for a station and date range"""
        try:
            total_days = (end_date - start_date).days + 1
            existing_data = ERA5Data.objects.filter(station=station, date__range=[start_date, end_date])
            complete_data = existing_data.filter(is_complete=True)
            incomplete_data = existing_data.filter(is_complete=False)
            existing_dates = set(existing_data.values_list('date', flat=True))
            all_dates = set(start_date + timedelta(days=i) for i in range(total_days))
            missing_dates = sorted(all_dates - existing_dates)
            
            status = {
                'total_days': total_days,
                'complete_days': complete_data.count(),
                'incomplete_days': incomplete_data.count(),
                'missing_days': len(missing_dates),
                'completion_rate': (complete_data.count() / total_days) * 100,
                'missing_dates': missing_dates[:10],
                'needs_download': len(missing_dates) > 0 or incomplete_data.count() > 0
            }
            return status
        except Exception as e:
            logger.error(f"Error getting download status: {e}")
            return None

def create_era5_downloader(mode='full', simulate=False, debug=False, simulate_mode=None, **kwargs):
    """Factory function to create ERA5Downloader with different configurations"""
    if simulate_mode is not None:
        simulate = simulate_mode
    config = {'simulate_mode': simulate, 'debug_mode': debug, **kwargs}
    
    if mode == 'surface':
        config['surface_only'] = True
        logger.info("Creating surface-only ERA5 downloader")
    elif mode == 'debug':
        config['debug_mode'] = True
        config['simulate_mode'] = True
        logger.info("Creating debug ERA5 downloader")
    elif mode == 'test':
        config['simulate_mode'] = True
        logger.info("Creating test ERA5 downloader")
    else:
        logger.info("Creating full-feature ERA5 downloader")
    
    return ERA5Downloader(**config)

CONSOLIDATION_INFO = {
    'version': '2.1.0',
    'consolidated_from': [
        'era5_utils_backup.py',
        'era5_simple_downloader.py',
        'era5_surface_test.py', 
        'complete_era5_downloader.py',
        'era5_downloader_clean.py'
    ],
    'features': [
        'Multiple download modes (full/surface-only/debug)',
        'Simulation mode for testing',
        'Comprehensive validation and status checking',
        'Backward compatibility with all previous implementations',
        'Factory function for easy configuration',
        'Enhanced error handling and logging',
        'Batched downloads for efficiency'
    ],
    'migration_date': '2025-08-24',
    'replaced_classes': [
        'SimpleERA5Downloader',
        'ERA5SurfaceOnlyDownloader', 
        'CompleteERA5Downloader',
        'CleanERA5Downloader'
    ]
}

logger.info(f"ERA5Downloader consolidated from {len(CONSOLIDATION_INFO['consolidated_from'])} implementations")

