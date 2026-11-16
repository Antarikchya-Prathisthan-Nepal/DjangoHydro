# Delineation Process Documentation

## 1. Purpose

This document explains the complete delineation workflow in the `delineation` app:
- how a user click becomes a watershed polygon,
- what datasets are used,
- what files and fields are involved,
- what is stored and returned,
- and current caveats in the implementation.

The implementation is a hybrid delineation approach:
- vector network traversal for upstream unit catchments,
- raster refinement only for the terminal unit catchment near the outlet.

---

## 2. Main Components

### Backend modules
- `delineation/views.py`: API entry points, request validation, model persistence, response formatting.
- `delineation/utils.py`: Core watershed delineation orchestration (`WatershedDelineator`).
- `delineation/merit_detailed.py`: High-resolution raster split inside terminal catchment (`split_catchment`).
- `delineation/fast_dissolve.py`: Fast dissolve and geometry cleanup utilities.
- `delineation/elevation_utils.py`: DEM-based elevation area stats and optional elevation band polygons.
- `delineation/models.py`: DB models for watershed results, logs, and user sessions.
- `delineation/urls.py`: Route wiring for map page and APIs.

### Frontend trigger
- `templates/delineation/index.html`: map UI container and script loading.
- `static/js/scripts.js`: Leaflet click flow and POST to `/delineation/api/delineate/`.

### Runtime configuration
- `Hydro_WebPortal/settings.py`: MERIT data paths, raster paths, thresholds, and delineation behavior flags.

---

## 3. Data Used for Delineation

## 3.1 MERIT-Hydro vector datasets

Located under `data/shp` (via `settings.SHAPE_DATA_PATH`):

1) Level-2 basin polygons
- Path pattern: `basins_level2/merit_hydro_vect_level2.shp`
- Purpose: first-stage basin lookup for clicked coordinate.
- Key field used:
  - `BASIN` (Pfafstetter level-2 basin id)

2) Unit catchment polygons per basin
- Path pattern: `merit_catchments/cat_pfaf_{basin}_MERIT_Hydro_v07_Basins_v01.shp`
- Purpose: determine terminal catchment and dissolve upstream polygons.
- Key fields used:
  - `COMID` (index key)
  - `geometry`

3) River network per basin
- Path pattern: `merit_rivers/riv_pfaf_{basin}_MERIT_Hydro_v07_Basins_v01.shp`
- Purpose: upstream traversal and stream metadata.
- Key fields used:
  - `COMID` (index key)
  - `up1`, `up2`, `up3`, `up4` (upstream links)
  - `uparea` (area matching heuristic)
  - `lengthkm` (main stream length)
  - `order` (stream order)
  - `geometry`

## 3.2 MERIT-Hydro raster datasets

Located under `data/raster` (via `settings.RASTER_DATA_PATH`):

1) Flow direction raster per basin
- Path pattern: `flowdir_basins/flowdir{basin}.tif`
- Purpose: pixel-scale upstream delineation in terminal catchment.
- Flow direction map used in code:
  - `dirmap = (64, 128, 1, 2, 4, 8, 16, 32)` (ESRI convention)

2) Flow accumulation raster per basin
- Path pattern: `accum_basins/accum{basin}.tif`
- Purpose: snapping pour point to stream grid using accumulation threshold.

## 3.3 DEM data for elevation stats (post-delineation)

From `elevation_utils.get_dem_paths()`:
- uses `settings.DEM_PATHS` or `settings.DEM_PATH` if present,
- else scans `data/raster/dem/*.tif`,
- fallback default `data/raster/dem/nepal_dem.tif`.

Used to compute:
- area below elevation thresholds (default 3000 m and 5000 m),
- optional elevation band polygons for frontend overlays.

---

## 4. End-to-End Processing Flow

## 4.1 Frontend request

1) User clicks on Leaflet map (`static/js/scripts.js`).
2) Browser sends POST JSON to `/delineation/api/delineate/` with:
- `latitude`
- `longitude`
- `method` (usually `vector`)
- `precision` (usually `high`)

## 4.2 View-level handling (`views.delineate_watershed`)

1) Parse JSON and validate Nepal bounds:
- longitude 80 to 89
- latitude 26 to 31
2) Create or fetch session (`SessionManager.get_or_create_session`).
3) Create `WatershedDelineation` row for traceability.
4) Create `ProcessingLog` entry for initialization.
5) Dispatch delineation using `WatershedDelineator.delineate_watershed(...)`.

## 4.3 Core delineation (`utils.WatershedDelineator.delineate_watershed`)

1) Build click point geometry (`Point(longitude, latitude)`).
2) Spatial join click point with level-2 basin polygons to get `BASIN`.
3) Load basin-specific catchment and river shapefiles.
4) Determine terminal `COMID`:
- if click intersects a catchment polygon, use that `COMID`.
- else snap to nearest river (`find_nearest_river`) with distance cutoff.
- optional area matching heuristic (`area_reported`) compares against river `uparea`.
5) Extract terminal catchment polygon.
6) Run raster refinement only inside terminal catchment via
`split_catchment(session_key, basin, lat, lng, catchment_poly, bSingleCatchment)`.
7) Recursively collect upstream COMIDs using `up1..up4` (`addnode`).
8) Replace terminal catchment polygon with raster-split polygon.
9) Dissolve all selected subbasins into one watershed polygon (`dissolve_geopandas`).
10) Optionally close small interior holes (`close_holes`) if `settings.FILL`.
11) Keep largest polygon if multipart (`get_largest`).
12) Compute area in km2 using Albers equal-area projection (`get_area_mghydro_style`).
13) Build result payload (`success`, `watershed_geojson`, properties, stream info, outlet coords).

## 4.4 Raster refinement details (`merit_detailed.split_catchment`)

1) Create rounded/expanded catchment bounding box aligned to MERIT 3-arcsec grid.
2) Read flow direction raster window only for that box (memory-efficient).
3) Rasterize terminal catchment polygon to mask.
4) Zero-out flow direction/accumulation outside mask to avoid snapping to neighboring basins.
5) Choose accumulation threshold:
- `THRESHOLD_SINGLE` if single-catchment mode,
- `THRESHOLD_MULTIPLE` otherwise.
6) Snap pour point to stream mask (`grid.snap_to_mask`).
7) Delineate catchment (`grid.catchment`).
8) Polygonize raster catchment (`grid.polygonize`).
9) Dissolve polygons; if multipart, keep largest polygon.
10) Return terminal split polygon and snapped outlet coordinates.

## 4.5 Persistence and response (`views.delineate_watershed`)

On success:
1) Convert geometry to DB-compatible MultiPolygon.
2) Save to `WatershedDelineation`:
- `watershed_polygon`
- `watershed_area_km2`
- `main_stream_length_km`
- `stream_order`
- `processing_time_seconds`
- elevation fields (if available)
3) Compute elevation stats via `calculate_elevation_area_stats`.
4) Return JSON with:
- watershed id,
- watershed GeoJSON,
- area and stream properties,
- snapped outlet coords,
- elevation stats,
- elevation band polygons.

---

## 5. Data Model Fields Involved

## 5.1 Input/session tracking

`WatershedDelineation`:
- `session_key`
- `click_point`
- `click_latitude`
- `click_longitude`

`UserSession`:
- `session_key`
- `ip_address`
- `user_agent`
- usage counters

## 5.2 Output storage

`WatershedDelineation`:
- `watershed_polygon` (MultiPolygon, SRID 4326)
- `watershed_area_km2`
- `main_stream_length_km`
- `stream_order`
- `area_below_3000m_km2`, `area_below_3000m_percent`
- `area_below_5000m_km2`, `area_below_5000m_percent`
- `processing_time_seconds`
- `success`, `error_message`

`ProcessingLog`:
- per-step status and diagnostics.

---

## 6. Configuration Affecting Delineation

From `settings.py`:
- `SHAPE_DATA_PATH`, `RASTER_DATA_PATH`
- `THRESHOLD_SINGLE = 500`
- `THRESHOLD_MULTIPLE = 5000`
- `FILL = True`
- `FILL_THRESHOLD = 100`
- `PIXEL_AREA = 0.000000695`
- `SEARCH_DIST = 0.025`
- `VERBOSE = True`

---

## 7. Current Caveats and Risks (from code review)

1) Single-catchment flag is hardcoded
- In `utils.py`, `bSingleCatchment` is always set to `True`.
- Effect: multi-catchment watersheds may use too-small snap threshold.

2) Distance checks use geographic degrees
- Nearest-river distance and area-match search buffer use degree units.
- Effect: threshold behavior varies by latitude and is not meter-based.

3) GeoJSON shape conversion mismatch in view
- Result GeoJSON is a `Feature`; `shape(...)` is called directly on that dict.
- Correct usage should pass `feature['geometry']`.

4) Duplicate `index` view definitions in `views.py`
- Later definition overrides earlier one.

5) Session counters are not updated after delineation
- `SessionManager.update_session_stats(...)` exists but is not called in flow.

6) Elevation coverage logic can overstate coverage
- In `elevation_utils.calculate_elevation_area_stats`, coverage is forced to 100% when any valid pixels exist.
- Effect: can hide partial DEM coverage.

7) Fallback elevation stats are hardcoded
- If DEM fails/does not overlap, synthetic Nepal fallback values are returned.
- Effect: may look valid but are estimates.

8) No substantial test suite in `delineation/tests.py`
- Regression risk for geometry, snapping, and elevation logic.

---

## 8. Practical Request/Response Contract

## Request (POST `/delineation/api/delineate/`)
Example payload:

```json
{
  "latitude": 28.25,
  "longitude": 83.90,
  "method": "vector",
  "precision": "high",
  "target_area": 1400.0
}
```

## Success response (main fields)
- `success`
- `watershed_id`
- `watershed_geojson`
- `properties.area_km2`
- `stream_info.main_stream_length_km`
- `stream_info.stream_order`
- `outlet_coords`
- `elevation_stats`
- `elevation_band_polygons`

## Error response
- `success = false`
- `error`

---

## 9. Summary

The delineation app uses a robust hybrid architecture:
- fast vector traversal for upstream topology,
- precise raster delineation where it matters most (terminal catchment),
- optional DEM-based elevation analytics.

The core process is production-usable, but several known correctness issues remain in snapping, geometry conversion, and elevation coverage reporting. Fixing those items will improve reproducibility and trust in area/elevation outputs.
