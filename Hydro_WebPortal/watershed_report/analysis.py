"""
Spatial analysis engine for Watershed Report.

All datasets are read with bbox pre-filtering for performance.
The wards GeoJSON (small, 6803 features) is cached in memory after first load.
"""

import base64
import io
import json
import logging
import math
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use('Agg')  # non-interactive backend (safe for Django)
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import pyproj
import rasterio
import rasterio.mask
import rasterio.warp
from shapely.geometry import box, mapping, shape
from shapely.ops import transform

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / 'data'

# ---------------------------------------------------------------------------
# LULC class definitions (confirmed by user)
# ---------------------------------------------------------------------------
LULC_CLASSES = {
    1:  'Water Bodies',
    2:  'Trees',
    4:  'Flooded Vegetation',
    5:  'Cropland',
    7:  'Built-up / Settlement',
    8:  'Bare Land',
    9:  'Snow & Ice',
    11: 'Rangeland',
}

LULC_COLORS = {
    1:  '#419bdf',  # Water Bodies
    2:  '#397d49',  # Trees
    4:  '#7a87c6',  # Flooded Vegetation
    5:  '#e49635',  # Cropland
    7:  '#c4281b',  # Built-up / Settlement
    8:  '#a59b8f',  # Bare Land
    9:  '#a8ebff',  # Snow & Ice
    11: '#e3e2c3',  # Rangeland
}

LULC_TIFS = [
    DATA_DIR / 'lulc' / '44R_20250101-20251231.tif',
    DATA_DIR / 'lulc' / '45R_20250101-20251231.tif',
]

# In-memory cache for wards (small dataset)
_wards_gdf = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_wards():
    global _wards_gdf
    if _wards_gdf is None:
        logger.info('Loading wards GeoJSON into memory cache...')
        _wards_gdf = gpd.read_file(
            DATA_DIR / 'nepal_wards' / 'npl_admin4.geojson',
            encoding='utf-8',
        )
        if _wards_gdf.crs is None:
            _wards_gdf.set_crs('EPSG:4326', inplace=True)
        else:
            _wards_gdf = _wards_gdf.to_crs('EPSG:4326')
        logger.info('Wards loaded: %d features', len(_wards_gdf))
    return _wards_gdf


def _area_km2(geom):
    """Return the area of a WGS84 Shapely geometry in km²."""
    lon = geom.centroid.x
    epsg = 32644 if lon < 84 else 32645
    project = pyproj.Transformer.from_crs(
        'EPSG:4326', f'EPSG:{epsg}', always_xy=True
    ).transform
    return transform(project, geom).area / 1e6


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_area(geom_geojson: dict) -> dict:
    """
    Run full watershed report for a GeoJSON geometry (dict with type/coordinates).
    Returns a results dict with keys: area_km2, population, lulc, buildings, wards, map_image.
    """
    geom = shape(geom_geojson)
    results = {'area_km2': round(_area_km2(geom), 3)}

    # Run all spatial analyses in parallel (they are independent of each other)
    with ThreadPoolExecutor(max_workers=4) as pool:
        task_map = {
            pool.submit(_analyze_population, geom): 'population',
            pool.submit(_analyze_lulc,        geom): 'lulc',
            pool.submit(_analyze_buildings,   geom): 'buildings',
            pool.submit(_analyze_wards,        geom): 'wards',
        }
        for future in as_completed(task_map):
            key = task_map[future]
            try:
                results[key] = future.result()
            except Exception as exc:
                logger.exception('Analysis failed for %s', key)
                results[key] = {'error': str(exc)}

    # Generate PDF map image + Leaflet LULC overlay together:
    # LULC raster is read/reprojected once; OSM tiles are fetched concurrently.
    try:
        results['map_image'], results['lulc_overlay'] = _generate_visuals(geom)
    except Exception as exc:
        logger.exception('Visual generation failed')
        results['map_image'] = None
        results['lulc_overlay'] = None

    return results


# ---------------------------------------------------------------------------
# OSM tile helpers for basemap
# ---------------------------------------------------------------------------

def _choose_zoom(minx, miny, maxx, maxy) -> int:
    """Pick a sensible OSM zoom level based on bounding-box span."""
    span = max(maxx - minx, maxy - miny)
    if span > 4:    return 7
    if span > 2:    return 8
    if span > 0.8:  return 9
    if span > 0.3:  return 10
    if span > 0.1:  return 11
    if span > 0.03: return 12
    return 13


def _ll_to_tile(lat: float, lon: float, z: int):
    """WGS84 lat/lon → OSM tile (x, y) at zoom z."""
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    lat_r = math.radians(lat)
    y = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return max(0, min(x, n - 1)), max(0, min(y, n - 1))


def _tile_to_lon(x: int, z: int) -> float:
    return x / 2 ** z * 360 - 180


def _tile_to_lat(y: int, z: int) -> float:
    n = math.pi - 2 * math.pi * y / 2 ** z
    return math.degrees(math.atan(math.sinh(n)))


def _fetch_basemap(w: float, s: float, e: float, n: float, zoom: int):
    """
    Download and stitch OSM tiles covering the padded bbox.
    Returns (PIL.Image, extent) where extent = [west, east, south, north].
    Raises on any failure so the caller can fall back gracefully.
    """
    from PIL import Image

    # Tile range: NW corner → SE corner
    tx0, ty0 = _ll_to_tile(n, w, zoom)  # northernmost / westernmost
    tx1, ty1 = _ll_to_tile(s, e, zoom)  # southernmost / easternmost

    n_x = tx1 - tx0 + 1
    n_y = ty1 - ty0 + 1
    if n_x * n_y > 30:
        raise ValueError(f'Too many tiles ({n_x}×{n_y}) – increase zoom cap')

    TILE = 256
    canvas = Image.new('RGB', (n_x * TILE, n_y * TILE))
    headers = {
        'User-Agent': 'HydroPortal/1.0 watershed-report (https://hydro.antarikchya.org.np)',
    }

    def _fetch_one(args):
        _ix, _iy, _tx, _ty = args
        url = f'https://tile.openstreetmap.org/{zoom}/{_tx}/{_ty}.png'
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            return _ix, _iy, Image.open(io.BytesIO(resp.read())).convert('RGB')

    tile_coords = [
        (ix, iy, tx0 + ix, ty0 + iy)
        for ix in range(n_x) for iy in range(n_y)
    ]
    with ThreadPoolExecutor(max_workers=min(len(tile_coords), 9)) as pool:
        for _ix, _iy, tile in pool.map(_fetch_one, tile_coords):
            canvas.paste(tile, (_ix * TILE, _iy * TILE))

    # Geographic extent of the stitched canvas
    west  = _tile_to_lon(tx0,     zoom)
    east  = _tile_to_lon(tx1 + 1, zoom)
    north = _tile_to_lat(ty0,     zoom)
    south = _tile_to_lat(ty1 + 1, zoom)
    return canvas, [west, east, south, north]  # imshow extent [left, right, bottom, top]


def _make_lulc_overlay(geom, w: float, s: float, e: float, n: float):
    """
    Reproject LULC rasters to WGS84, clip to the watershed polygon, and return
    an RGBA PIL Image covering [w, e, s, n] together with the set of class values
    that are actually present.
    Returns (PIL.Image, [w,e,s,n], set_of_class_values) or None.
    """
    from PIL import Image as PILImage
    from rasterio.transform import from_bounds as tfb
    from rasterio.features import rasterize

    OUT_W, OUT_H = 512, 384
    DST_CRS = 'EPSG:4326'
    dst_tfm = tfb(w, s, e, n, OUT_W, OUT_H)

    combined = np.zeros((OUT_H, OUT_W), dtype=np.uint8)

    for tif_path in LULC_TIFS:
        if not tif_path.exists():
            continue
        try:
            with rasterio.open(tif_path) as src:
                src_b_wgs = rasterio.warp.transform_bounds(src.crs, DST_CRS, *src.bounds)
                if not box(*src_b_wgs).intersects(box(w, s, e, n)):
                    continue
                dst_arr = np.zeros((OUT_H, OUT_W), dtype=np.uint8)
                rasterio.warp.reproject(
                    source=rasterio.band(src, 1),
                    destination=dst_arr,
                    dst_transform=dst_tfm,
                    dst_crs=DST_CRS,
                    resampling=rasterio.warp.Resampling.nearest,
                    dst_nodata=0,
                )
                px = dst_arr > 0
                combined[px] = dst_arr[px]
        except Exception as exc:
            logger.debug('LULC tile reproject failed (%s): %s', tif_path.name, exc)

    if combined.max() == 0:
        return None

    # Clip to watershed polygon
    try:
        geom_mask = rasterize(
            [(mapping(geom), 1)],
            out_shape=(OUT_H, OUT_W),
            transform=dst_tfm,
            fill=0,
            dtype=np.uint8,
        )
        combined = np.where(geom_mask > 0, combined, 0)
    except Exception:
        pass

    def _hex_rgb(h):
        h = h.lstrip('#')
        return int(h[:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    rgba = np.zeros((OUT_H, OUT_W, 4), dtype=np.uint8)
    classes_present = set()
    for val, color_hex in LULC_COLORS.items():
        px = combined == val
        if not px.any():
            continue
        r, g, b = _hex_rgb(color_hex)
        rgba[px, 0] = r
        rgba[px, 1] = g
        rgba[px, 2] = b
        rgba[px, 3] = 210
        classes_present.add(val)

    if not classes_present:
        return None

    return PILImage.fromarray(rgba, 'RGBA'), [w, e, s, n], classes_present


def _make_lulc_image_overlay(geom) -> dict | None:
    """
    Generate a Leaflet-ready LULC colour overlay clipped to the watershed polygon.
    Returns {'image': 'data:image/png;base64,...', 'bounds': [[s,w],[n,e]]} or None.
    """
    from PIL import Image as PILImage
    from rasterio.transform import from_bounds as tfb
    from rasterio.features import rasterize

    minx, miny, maxx, maxy = geom.bounds
    pad_x = max((maxx - minx) * 0.02, 0.002)
    pad_y = max((maxy - miny) * 0.02, 0.002)
    w, s, e, n = minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y

    OUT_W, OUT_H = 800, 600
    DST_CRS = 'EPSG:4326'
    dst_tfm = tfb(w, s, e, n, OUT_W, OUT_H)

    combined = np.zeros((OUT_H, OUT_W), dtype=np.uint8)

    for tif_path in LULC_TIFS:
        if not tif_path.exists():
            continue
        try:
            with rasterio.open(tif_path) as src:
                src_b_wgs = rasterio.warp.transform_bounds(src.crs, DST_CRS, *src.bounds)
                if not box(*src_b_wgs).intersects(box(w, s, e, n)):
                    continue
                dst_arr = np.zeros((OUT_H, OUT_W), dtype=np.uint8)
                rasterio.warp.reproject(
                    source=rasterio.band(src, 1),
                    destination=dst_arr,
                    dst_transform=dst_tfm,
                    dst_crs=DST_CRS,
                    resampling=rasterio.warp.Resampling.nearest,
                    dst_nodata=0,
                )
                px = dst_arr > 0
                combined[px] = dst_arr[px]
        except Exception as exc:
            logger.debug('LULC image overlay tile failed (%s): %s', tif_path.name, exc)

    if combined.max() == 0:
        return None

    # Clip to watershed polygon
    try:
        geom_mask = rasterize(
            [(mapping(geom), 1)],
            out_shape=(OUT_H, OUT_W),
            transform=dst_tfm,
            fill=0,
            dtype=np.uint8,
        )
        combined = np.where(geom_mask > 0, combined, 0)
    except Exception:
        pass

    def _hex_rgb(h):
        h = h.lstrip('#')
        return int(h[:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    rgba = np.zeros((OUT_H, OUT_W, 4), dtype=np.uint8)
    for val, color_hex in LULC_COLORS.items():
        px = combined == val
        if not px.any():
            continue
        r, g, b = _hex_rgb(color_hex)
        rgba[px, 0] = r
        rgba[px, 1] = g
        rgba[px, 2] = b
        rgba[px, 3] = 185  # semi-transparent so OSM basemap shows through

    if rgba[:, :, 3].sum() == 0:
        return None

    img = PILImage.fromarray(rgba, 'RGBA')
    buf = io.BytesIO()
    img.save(buf, format='PNG', optimize=True)
    buf.seek(0)
    return {
        'image': 'data:image/png;base64,' + base64.b64encode(buf.read()).decode('ascii'),
        'bounds': [[s, w], [n, e]],  # Leaflet [[south, west], [north, east]]
    }


# ---------------------------------------------------------------------------
# Per-layer analysis
# ---------------------------------------------------------------------------

def _generate_map_image(geom) -> str:
    """
    Generate a location map with:
      - OSM basemap tiles (if reachable)
      - LULC colour overlay clipped to the watershed polygon
      - Ward / municipality boundaries with name labels
      - Watershed polygon outline
    Falls back gracefully when any layer cannot be loaded.
    Returns a base64-encoded PNG data URI string.
    """
    minx, miny, maxx, maxy = geom.bounds
    pad_x = max((maxx - minx) * 0.30, 0.02)
    pad_y = max((maxy - miny) * 0.30, 0.02)
    w, s, e, n = minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y

    # -- OSM basemap ----------------------------------------------------------
    basemap = None
    try:
        zoom = _choose_zoom(w, s, e, n)
        basemap_img, bm_ext = _fetch_basemap(w, s, e, n, zoom)
        basemap = (basemap_img, bm_ext)
        logger.debug('Basemap fetched at zoom %d', zoom)
    except Exception as exc:
        logger.info('Basemap unavailable (%s) – using plain background', exc)

    # -- LULC colour overlay (clipped to polygon) -----------------------------
    lulc_overlay = None
    lulc_classes_shown = set()
    try:
        result = _make_lulc_overlay(geom, w, s, e, n)
        if result:
            lulc_overlay, _, lulc_classes_shown = result
    except Exception as exc:
        logger.info('LULC overlay failed (%s)', exc)

    # -- Ward / municipality data for boundaries + labels ---------------------
    ward_gdf_local = None
    try:
        all_wards = _load_wards()
        nearby = all_wards[all_wards.intersects(box(w, s, e, n))].copy()
        if not nearby.empty:
            ward_gdf_local = nearby
    except Exception:
        pass

    # -- Build figure ---------------------------------------------------------
    fig, ax = plt.subplots(figsize=(7, 3), dpi=120)
    fig.patch.set_facecolor('#ffffff')

    # Layer 0: OSM basemap
    if basemap:
        ax.imshow(np.array(basemap[0]), extent=basemap[1],
                  origin='upper', aspect='auto', zorder=0)
    ax.set_facecolor('#d6eaf8')

    # Layer 1: LULC colour overlay
    if lulc_overlay is not None:
        ax.imshow(np.array(lulc_overlay), extent=[w, e, s, n],
                  origin='upper', aspect='auto', zorder=1)

    # Layer 2: ward boundaries
    if ward_gdf_local is not None:
        ward_gdf_local.plot(
            ax=ax, facecolor='none', edgecolor='#37474f',
            linewidth=0.4, alpha=0.75, zorder=2,
        )

    # Layer 3: watershed polygon (semi-transparent fill + solid outline)
    poly_edge = '#1565c0'
    poly_fill = '#3498db'
    poly_alpha = 0.15 if lulc_overlay is not None else (0.25 if basemap else 0.65)
    gdf = gpd.GeoDataFrame(geometry=[geom], crs='EPSG:4326')
    gdf.plot(ax=ax, facecolor=poly_fill, edgecolor='none',
             linewidth=0, alpha=poly_alpha, zorder=3)
    gdf.plot(ax=ax, facecolor='none', edgecolor=poly_edge,
             linewidth=2.0, zorder=4)

    # Layer 5: municipality name labels
    if ward_gdf_local is not None and 'GaPa_NaPa' in ward_gdf_local.columns:
        muni_groups = ward_gdf_local.groupby('GaPa_NaPa')
        n_munis = len(muni_groups)
        fs = 4.5 if n_munis > 8 else 5.5
        for muni_name, grp in muni_groups:
            if not muni_name:
                continue
            c = grp.geometry.unary_union.centroid
            lx, ly = c.x, c.y
            if not (w < lx < e and s < ly < n):
                continue
            ax.annotate(
                str(muni_name), xy=(lx, ly),
                fontsize=fs, color='#0d1b2a', ha='center', va='center',
                fontweight='bold',
                bbox=dict(facecolor='white', alpha=0.55, edgecolor='none', pad=0.5),
                zorder=6,
            )

    # Layer 6: centroid crosshair
    cx, cy = geom.centroid.x, geom.centroid.y
    ax.plot(cx, cy, '+', color='#e74c3c', markersize=9, markeredgewidth=2, zorder=7)

    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    ax.set_xlabel('Longitude', fontsize=6, color='#546e7a')
    ax.set_ylabel('Latitude', fontsize=6, color='#546e7a')
    ax.tick_params(labelsize=5, colors='#546e7a')
    for spine in ax.spines.values():
        spine.set_edgecolor('#90a4ae')

    # Legend: watershed boundary + LULC classes present
    legend_handles = [
        mpatches.Patch(facecolor=poly_fill, edgecolor=poly_edge,
                       linewidth=1, label='Watershed boundary'),
    ]
    for val in sorted(lulc_classes_shown):
        legend_handles.append(mpatches.Patch(
            facecolor=LULC_COLORS.get(val, '#888'),
            label=LULC_CLASSES.get(val, f'Class {val}'),
        ))
    ncol = 2 if len(legend_handles) > 4 else 1
    ax.legend(handles=legend_handles, fontsize=4.5, loc='lower right',
              framealpha=0.92, edgecolor='#cfd8dc', ncol=ncol)

    # OSM attribution
    if basemap:
        ax.text(0.01, 0.01, '© OpenStreetMap contributors',
                transform=ax.transAxes, fontsize=4.5, color='#546e7a',
                va='bottom', ha='left',
                bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=1),
                zorder=8)

    ax.set_title('Location Map', fontsize=8, color='#0f3460', pad=5, fontweight='bold')
    plt.tight_layout(pad=0.4)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    buf.seek(0)
    return 'data:image/png;base64,' + base64.b64encode(buf.read()).decode('ascii')


def _compute_lulc_raster(geom, w: float, s: float, e: float, n: float,
                          out_w: int, out_h: int) -> np.ndarray:
    """
    Reproject all LULC TIF tiles to WGS84 and clip to the watershed polygon.
    Returns an (out_h, out_w) uint8 ndarray of class values; 0 = outside / no data.
    """
    from rasterio.transform import from_bounds as tfb
    from rasterio.features import rasterize as _rasterize

    DST_CRS = 'EPSG:4326'
    dst_tfm = tfb(w, s, e, n, out_w, out_h)
    combined = np.zeros((out_h, out_w), dtype=np.uint8)

    for tif_path in LULC_TIFS:
        if not tif_path.exists():
            continue
        try:
            with rasterio.open(tif_path) as src:
                src_b_wgs = rasterio.warp.transform_bounds(src.crs, DST_CRS, *src.bounds)
                if not box(*src_b_wgs).intersects(box(w, s, e, n)):
                    continue
                dst_arr = np.zeros((out_h, out_w), dtype=np.uint8)
                rasterio.warp.reproject(
                    source=rasterio.band(src, 1),
                    destination=dst_arr,
                    dst_transform=dst_tfm,
                    dst_crs=DST_CRS,
                    resampling=rasterio.warp.Resampling.nearest,
                    dst_nodata=0,
                )
                mask = dst_arr > 0
                combined[mask] = dst_arr[mask]
        except Exception as exc:
            logger.debug('LULC reproject failed (%s): %s', tif_path.name, exc)

    if combined.max() == 0:
        return combined

    # Clip to watershed polygon
    try:
        poly_mask = _rasterize(
            [(mapping(geom), 1)],
            out_shape=(out_h, out_w),
            transform=dst_tfm,
            fill=0,
            dtype=np.uint8,
        )
        combined = np.where(poly_mask > 0, combined, 0)
    except Exception:
        pass
    return combined


def _generate_visuals(geom):
    """
    Generate the PDF location map and Leaflet LULC overlay together.

    Key optimisations vs the previous two-function approach:
      - LULC rasters are read and reprojected only ONCE (shared for PDF + Leaflet).
      - OSM tile fetching and LULC raster reprojection run concurrently.
      - Individual OSM tiles inside _fetch_basemap are also fetched concurrently.

    Returns (map_image_b64_str, lulc_overlay_dict_or_None).
    """
    from PIL import Image as PILImage

    minx, miny, maxx, maxy = geom.bounds

    # Wide bbox for PDF context (30% padding)
    pad_x = max((maxx - minx) * 0.30, 0.02)
    pad_y = max((maxy - miny) * 0.30, 0.02)
    w, s, e, n = minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y

    # Tight bbox for LULC overlay (2% padding)
    lpad_x = max((maxx - minx) * 0.02, 0.002)
    lpad_y = max((maxy - miny) * 0.02, 0.002)
    lw, ls, le, ln = minx - lpad_x, miny - lpad_y, maxx + lpad_x, maxy + lpad_y

    # Fetch OSM basemap and compute LULC raster concurrently
    basemap = None
    lulc_arr = None
    with ThreadPoolExecutor(max_workers=2) as pool:
        bm_fut   = pool.submit(_fetch_basemap, w, s, e, n, _choose_zoom(w, s, e, n))
        lulc_fut = pool.submit(_compute_lulc_raster, geom, lw, ls, le, ln, 800, 600)
        try:
            basemap = bm_fut.result()
            logger.debug('Basemap fetched')
        except Exception as exc:
            logger.info('Basemap unavailable (%s) – plain background', exc)
        try:
            lulc_arr = lulc_fut.result()
            if lulc_arr.max() == 0:
                lulc_arr = None
        except Exception as exc:
            logger.info('LULC raster failed: %s', exc)

    # Colorise LULC array to RGBA PIL image (reused for both PDF and Leaflet)
    def _hex_rgb(h):
        h = h.lstrip('#')
        return int(h[:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    lulc_rgba = None
    classes_present = set()
    if lulc_arr is not None:
        OUT_H, OUT_W = lulc_arr.shape
        rgba = np.zeros((OUT_H, OUT_W, 4), dtype=np.uint8)
        for val, color_hex in LULC_COLORS.items():
            px = lulc_arr == val
            if not px.any():
                continue
            r, g, b = _hex_rgb(color_hex)
            rgba[px, 0] = r
            rgba[px, 1] = g
            rgba[px, 2] = b
            rgba[px, 3] = 210
            classes_present.add(val)
        if classes_present:
            lulc_rgba = PILImage.fromarray(rgba, 'RGBA')

    # Leaflet overlay: same RGBA image with slightly lower alpha for interactivity
    lulc_overlay = None
    if lulc_rgba is not None:
        rgba_leaf = np.array(lulc_rgba).copy()
        rgba_leaf[:, :, 3] = np.where(rgba_leaf[:, :, 3] > 0, 185, 0).astype(np.uint8)
        buf = io.BytesIO()
        PILImage.fromarray(rgba_leaf, 'RGBA').save(buf, format='PNG', optimize=True)
        buf.seek(0)
        lulc_overlay = {
            'image': 'data:image/png;base64,' + base64.b64encode(buf.read()).decode('ascii'),
            'bounds': [[ls, lw], [ln, le]],
        }

    # Ward boundaries for PDF map labels
    ward_gdf_local = None
    try:
        all_wards = _load_wards()
        nearby = all_wards[all_wards.intersects(box(w, s, e, n))].copy()
        if not nearby.empty:
            ward_gdf_local = nearby
    except Exception:
        pass

    # Build matplotlib figure
    fig, ax = plt.subplots(figsize=(7, 3), dpi=120)
    fig.patch.set_facecolor('#ffffff')

    if basemap:
        ax.imshow(np.array(basemap[0]), extent=basemap[1],
                  origin='upper', aspect='auto', zorder=0)
    ax.set_facecolor('#d6eaf8')

    if lulc_rgba is not None:
        ax.imshow(np.array(lulc_rgba), extent=[lw, le, ls, ln],
                  origin='upper', aspect='auto', zorder=1)

    if ward_gdf_local is not None:
        ward_gdf_local.plot(
            ax=ax, facecolor='none', edgecolor='#37474f',
            linewidth=0.4, alpha=0.75, zorder=2,
        )

    poly_edge  = '#1565c0'
    poly_fill  = '#3498db'
    poly_alpha = 0.15 if lulc_rgba is not None else (0.25 if basemap else 0.65)
    gdf = gpd.GeoDataFrame(geometry=[geom], crs='EPSG:4326')
    gdf.plot(ax=ax, facecolor=poly_fill, edgecolor='none', linewidth=0,
             alpha=poly_alpha, zorder=3)
    gdf.plot(ax=ax, facecolor='none', edgecolor=poly_edge, linewidth=2.0, zorder=4)

    cx, cy = geom.centroid.x, geom.centroid.y
    ax.plot(cx, cy, '+', color='#e74c3c', markersize=9, markeredgewidth=2, zorder=7)

    ax.set_xlim(w, e)
    ax.set_ylim(s, n)
    ax.set_xlabel('Longitude', fontsize=6, color='#546e7a')
    ax.set_ylabel('Latitude', fontsize=6, color='#546e7a')
    ax.tick_params(labelsize=5, colors='#546e7a')
    for spine in ax.spines.values():
        spine.set_edgecolor('#90a4ae')

    legend_handles = [
        mpatches.Patch(facecolor=poly_fill, edgecolor=poly_edge,
                       linewidth=1, label='Watershed boundary'),
    ]
    for val in sorted(classes_present):
        legend_handles.append(mpatches.Patch(
            facecolor=LULC_COLORS.get(val, '#888'),
            label=LULC_CLASSES.get(val, f'Class {val}'),
        ))
    ncol = 2 if len(legend_handles) > 4 else 1
    ax.legend(handles=legend_handles, fontsize=4.5, loc='lower right',
              framealpha=0.92, edgecolor='#cfd8dc', ncol=ncol)

    if basemap:
        ax.text(0.01, 0.01, '© OpenStreetMap contributors',
                transform=ax.transAxes, fontsize=4.5, color='#546e7a',
                va='bottom', ha='left',
                bbox=dict(facecolor='white', alpha=0.6, edgecolor='none', pad=1),
                zorder=8)

    ax.set_title('Location Map', fontsize=8, color='#0f3460', pad=5, fontweight='bold')
    plt.tight_layout(pad=0.4)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    buf.seek(0)
    map_image = 'data:image/png;base64,' + base64.b64encode(buf.read()).decode('ascii')

    return map_image, lulc_overlay


def _analyze_population(geom):
    bbox = geom.bounds  # (minx, miny, maxx, maxy)
    pop_path = DATA_DIR / 'Population' / 'nepal_polygon.shp'

    pop_gdf = gpd.read_file(pop_path, bbox=bbox)
    if pop_gdf.empty:
        return {'total': 0, 'cell_count': 0}

    intersecting = pop_gdf[pop_gdf.intersects(geom)]
    total = float(intersecting['VALUE'].sum())
    return {
        'total': round(total),
        'cell_count': len(intersecting),
    }


def _analyze_lulc(geom):
    class_pixels: dict[int, int] = {}
    pixel_area_m2 = None

    for tif_path in LULC_TIFS:
        if not tif_path.exists():
            logger.warning('LULC file not found: %s', tif_path)
            continue

        with rasterio.open(tif_path) as src:
            # Project geometry from WGS84 to raster CRS
            raster_crs = src.crs
            project_fwd = pyproj.Transformer.from_crs(
                'EPSG:4326', raster_crs, always_xy=True
            ).transform
            geom_proj = transform(project_fwd, geom)

            # Skip if no overlap
            if not geom_proj.intersects(box(*src.bounds)):
                continue

            if pixel_area_m2 is None:
                pixel_area_m2 = abs(src.transform.a * src.transform.e)

            try:
                out_image, _ = rasterio.mask.mask(
                    src, [mapping(geom_proj)], crop=True, nodata=0
                )
                arr = out_image[0]
                unique, counts = np.unique(arr, return_counts=True)
                for val, cnt in zip(unique, counts):
                    if int(val) == 0:
                        continue
                    class_pixels[int(val)] = class_pixels.get(int(val), 0) + int(cnt)
            except Exception as exc:
                logger.warning('LULC masking failed for %s: %s', tif_path.name, exc)

    if pixel_area_m2 is None:
        pixel_area_m2 = 100  # fallback: 10 m × 10 m

    total_px = sum(class_pixels.values())
    lulc_result = []
    for val, count in sorted(class_pixels.items()):
        area_km2 = count * pixel_area_m2 / 1e6
        label = LULC_CLASSES.get(val, f'Class {val}')
        pct = round(count / total_px * 100, 1) if total_px > 0 else 0
        lulc_result.append({
            'class_value': val,
            'class_name': label,
            'area_km2': round(area_km2, 4),
            'percentage': pct,
            'color': LULC_COLORS.get(val, '#888888'),
        })

    return lulc_result


def _analyze_buildings(geom):
    bbox = geom.bounds
    bld_path = DATA_DIR / 'buildings' / 'gis_osm_buildings_a_free_1.shp'

    bld_gdf = gpd.read_file(bld_path, bbox=bbox)
    if bld_gdf.empty:
        return {'total': 0, 'by_type': []}

    # Ensure same CRS
    if bld_gdf.crs is None:
        bld_gdf.set_crs('EPSG:4326', inplace=True)
    else:
        bld_gdf = bld_gdf.to_crs('EPSG:4326')

    intersecting = bld_gdf[bld_gdf.intersects(geom)]
    vc = intersecting['type'].fillna('unclassified').value_counts()
    type_counts = [{'type': k, 'count': int(v)} for k, v in vc.items()]
    return {
        'total': len(intersecting),
        'by_type': type_counts,
    }


def _analyze_wards(geom):
    wards_gdf = _load_wards()
    intersecting = wards_gdf[wards_gdf.intersects(geom)]

    wards = []
    for _, row in intersecting.iterrows():
        wards.append({
            'district':      row.get('DISTRICT', ''),
            'municipality':  row.get('GaPa_NaPa', ''),
            'type':          row.get('Type_GN', ''),
            'ward_number':   row.get('NEW_WARD_N', ''),
            'state_code':    row.get('STATE_CODE', ''),
            'area_sqkm':     round(float(row.get('Area_SQKM', 0) or 0), 2),
        })

    # Summarise districts and municipalities
    districts = sorted({w['district'] for w in wards if w['district']})
    municipalities = sorted({w['municipality'] for w in wards if w['municipality']})

    return {
        'ward_count': len(wards),
        'district_count': len(districts),
        'districts': districts,
        'municipalities': municipalities,
        'wards': wards,
    }
