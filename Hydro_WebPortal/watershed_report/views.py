import io
import json
import logging
import os
import struct
import tempfile
import zipfile

import geopandas as gpd
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from shapely.geometry import mapping, shape

from .analysis import analyze_area
from .models import WatershedReport

logger = logging.getLogger(__name__)

ALLOWED_GEOJSON_TYPES = ('Polygon', 'MultiPolygon')
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


@never_cache
@require_GET
def index(request):
    return render(request, 'watershed_report/index.html')


@csrf_protect
@require_POST
def analyze(request):
    """
    POST endpoint. Accepts either:
      - JSON body:  {"geometry": <GeoJSON geometry>, "name": "<optional title>"}
      - Multipart:  file=<.geojson or .zip>, name=<optional title>

    Runs spatial analysis, saves a WatershedReport record for the user,
    and returns JSON: {success, report_id, results}.
    """
    geom_geojson = None
    report_name  = ''

    # --- File upload path ---
    if request.FILES.get('file'):
        uploaded = request.FILES['file']
        if uploaded.size > MAX_UPLOAD_BYTES:
            return JsonResponse({'success': False, 'error': 'File too large (max 20 MB).'}, status=400)

        report_name = request.POST.get('name', '').strip()
        fname = uploaded.name.lower()
        try:
            if fname.endswith('.geojson') or fname.endswith('.json'):
                geom_geojson = _geom_from_geojson_bytes(uploaded.read())
            elif fname.endswith('.zip'):
                geom_geojson = _geom_from_zip_bytes(uploaded.read())
            else:
                return JsonResponse(
                    {'success': False, 'error': 'Unsupported file type. Upload .geojson or .zip (shapefile).'},
                    status=400,
                )
        except ValueError as exc:
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    # --- JSON body path ---
    else:
        try:
            body = json.loads(request.body)
            raw_geom = body.get('geometry')
            if raw_geom is None:
                return JsonResponse({'success': False, 'error': 'Missing "geometry" key.'}, status=400)
            geom_geojson = _validate_geom(raw_geom)
            report_name  = body.get('name', '').strip()
        except (json.JSONDecodeError, ValueError) as exc:
            return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    if geom_geojson is None:
        return JsonResponse({'success': False, 'error': 'Could not extract geometry.'}, status=400)

    try:
        results = analyze_area(geom_geojson)
    except Exception as exc:
        logger.exception('analyze_area failed')
        return JsonResponse({'success': False, 'error': f'Analysis error: {exc}'}, status=500)

    # Only persist to database for authenticated users.
    # Anonymous users receive results in memory; they can save later via /save/.
    report_id = None
    if request.user.is_authenticated:
        report = WatershedReport.objects.create(
            user     = request.user,
            name     = report_name,
            geometry = geom_geojson,
            results  = results,
            area_km2 = results.get('area_km2', 0),
        )
        report_id = report.pk

    return JsonResponse({'success': True, 'report_id': report_id, 'results': results})


# ---------------------------------------------------------------------------
# History list
# ---------------------------------------------------------------------------

@require_GET
def history(request):
    if not request.user.is_authenticated:
        return JsonResponse({'reports': []})
    qs = WatershedReport.objects.filter(user=request.user).values(
        'id', 'name', 'area_km2', 'created_at'
    )[:20]
    items = [
        {
            'id':         r['id'],
            'name':       r['name'] or f'Report #{r["id"]}',
            'area_km2':   r['area_km2'],
            'created_at': r['created_at'].strftime('%Y-%m-%d %H:%M'),
        }
        for r in qs
    ]
    return JsonResponse({'reports': items})


# ---------------------------------------------------------------------------
# Save an anonymously-analysed report (called after modal login)
# ---------------------------------------------------------------------------

@login_required
@csrf_protect
@require_POST
def save_report(request):
    """Persist results for a user who ran the analysis while not logged in.

    Accepts JSON {geometry, name}; re-runs analysis server-side so we don't
    trust a potentially-large results blob from the client.
    """
    try:
        body       = json.loads(request.body)
        raw_geom   = body.get('geometry')
        report_name = body.get('name', '').strip()
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)

    if not raw_geom:
        return JsonResponse({'success': False, 'error': 'Missing geometry.'}, status=400)

    try:
        geom_geojson = _validate_geom(raw_geom)
    except ValueError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=400)

    try:
        results = analyze_area(geom_geojson)
    except Exception as exc:
        logger.exception('analyze_area failed in save_report')
        return JsonResponse({'success': False, 'error': f'Analysis error: {exc}'}, status=500)

    report = WatershedReport.objects.create(
        user     = request.user,
        name     = report_name,
        geometry = geom_geojson,
        results  = results,
        area_km2 = results.get('area_km2', 0),
    )
    return JsonResponse({'success': True, 'report_id': report.pk})


# ---------------------------------------------------------------------------
# Load a saved report
# ---------------------------------------------------------------------------

@login_required
@require_GET
def report_detail(request, report_id):
    report = get_object_or_404(WatershedReport, pk=report_id, user=request.user)
    return JsonResponse({
        'id':         report.pk,
        'name':       report.display_name(),
        'geometry':   report.geometry,
        'results':    report.results,
        'area_km2':   report.area_km2,
        'created_at': report.created_at.strftime('%Y-%m-%d %H:%M'),
    })


# ---------------------------------------------------------------------------
# Rename a saved report
# ---------------------------------------------------------------------------

@login_required
@csrf_protect
@require_POST
def report_rename(request, report_id):
    report = get_object_or_404(WatershedReport, pk=report_id, user=request.user)
    try:
        body     = json.loads(request.body)
        new_name = body.get('name', '').strip()[:200]
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON.'}, status=400)
    report.name = new_name
    report.save(update_fields=['name'])
    return JsonResponse({'success': True, 'name': report.display_name()})


# ---------------------------------------------------------------------------
# Delete a saved report
# ---------------------------------------------------------------------------

@login_required
@csrf_protect
@require_POST
def report_delete(request, report_id):
    report = get_object_or_404(WatershedReport, pk=report_id, user=request.user)
    report.delete()
    return JsonResponse({'success': True})


# ---------------------------------------------------------------------------
# Print / download report (renders a print-friendly HTML page)
# ---------------------------------------------------------------------------

@login_required
@require_GET
def report_print(request, report_id):
    report = get_object_or_404(WatershedReport, pk=report_id, user=request.user)
    results = report.results

    # Flatten LULC list for template
    lulc = results.get('lulc') if isinstance(results.get('lulc'), list) else []
    buildings = results.get('buildings') or {}
    wards_data = results.get('wards') or {}

    context = {
        'report':       report,
        'area_km2':     results.get('area_km2', 0),
        'population':   results.get('population') or {},
        'lulc':         lulc,
        'buildings':    buildings,
        'by_type':      buildings.get('by_type', []),
        'wards_data':   wards_data,
        'wards':        wards_data.get('wards', []),
        'districts':    wards_data.get('districts', []),
        'municipalities': wards_data.get('municipalities', []),
        'map_image':    results.get('map_image'),
    }
    return render(request, 'watershed_report/report_print.html', context)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_shx(shp_bytes: bytes) -> bytes:
    """Reconstruct a .shx index file from .shp bytes.

    A shapefile index (.shx) is a 100-byte header followed by 8-byte
    records, each holding the offset and content-length of the
    corresponding .shp record (both big-endian int32, in 16-bit words).
    """
    records = []
    pos = 100  # skip the 100-byte file header
    n = len(shp_bytes)
    while pos + 8 <= n:
        content_len = struct.unpack('>i', shp_bytes[pos + 4: pos + 8])[0]
        records.append((pos // 2, content_len))   # offset & length in 16-bit words
        pos += 8 + content_len * 2
    shx_file_len_words = (100 + len(records) * 8) // 2
    header = bytearray(shp_bytes[:100])
    struct.pack_into('>i', header, 24, shx_file_len_words)  # patch file-length field
    out = bytes(header)
    for offset, content_len in records:
        out += struct.pack('>ii', offset, content_len)
    return out


def _validate_geom(raw_geom: dict) -> dict:
    """Validate and normalise a raw GeoJSON geometry dict."""
    if not isinstance(raw_geom, dict):
        raise ValueError('geometry must be a JSON object.')

    geom_type = raw_geom.get('type', '')

    # Accept a Feature or FeatureCollection and unwrap
    if geom_type == 'Feature':
        raw_geom = raw_geom.get('geometry') or {}
        geom_type = raw_geom.get('type', '')
    elif geom_type == 'FeatureCollection':
        features = raw_geom.get('features', [])
        if not features:
            raise ValueError('FeatureCollection is empty.')
        raw_geom = features[0].get('geometry') or {}
        geom_type = raw_geom.get('type', '')

    if geom_type not in ALLOWED_GEOJSON_TYPES:
        raise ValueError(f'Geometry must be Polygon or MultiPolygon, got: {geom_type!r}.')

    # Parse through Shapely to validate topology
    try:
        geom = shape(raw_geom)
    except Exception as exc:
        raise ValueError(f'Invalid geometry: {exc}')

    if not geom.is_valid:
        geom = geom.buffer(0)  # attempt auto-repair

    return mapping(geom)


def _geom_from_geojson_bytes(data: bytes) -> dict:
    """Extract the first Polygon/MultiPolygon geometry from GeoJSON bytes."""
    try:
        obj = json.loads(data.decode('utf-8'))
    except Exception:
        raise ValueError('File is not valid JSON.')
    return _validate_geom(obj)


def _geom_from_zip_bytes(data: bytes) -> dict:
    """Extract the union (or first feature) geometry from a zipped shapefile."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ValueError('Uploaded file is not a valid ZIP archive.')

    names = zf.namelist()
    shp_names = [n for n in names if n.lower().endswith('.shp')]
    if not shp_names:
        raise ValueError('No .shp file found inside the ZIP.')

    shp_name = shp_names[0]
    # Match companion files by basename only (handles zips with subdirectories
    # and mixed-case extensions like .SHX vs .shx)
    shp_stem = os.path.splitext(os.path.basename(shp_name))[0].lower()
    file_map = {}
    for n in names:
        bn = os.path.basename(n)
        stem, ext = os.path.splitext(bn)
        if stem.lower() == shp_stem and ext.lower() in ('.shp', '.dbf', '.shx', '.prj', '.cpg'):
            file_map[ext.lower()] = zf.read(n)

    if '.shp' not in file_map:
        raise ValueError('Could not read .shp from ZIP.')

    # If .shx is missing, reconstruct it from the .shp record headers
    if '.shx' not in file_map:
        file_map['.shx'] = _build_shx(file_map['.shp'])

    # Write all shapefile components to a temp directory and read from disk.
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            for ext, content in file_map.items():
                with open(os.path.join(tmpdir, 'layer' + ext), 'wb') as fh:
                    fh.write(content)
            gdf = gpd.read_file(os.path.join(tmpdir, 'layer.shp'))
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'Could not read shapefile: {exc}')

    if gdf.empty:
        raise ValueError('Shapefile contains no features.')

    # Reproject to WGS84 if needed
    if gdf.crs is not None and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs('EPSG:4326')

    # Union all features into one geometry
    union_geom = gdf.geometry.unary_union
    if union_geom.geom_type not in ALLOWED_GEOJSON_TYPES:
        raise ValueError('Shapefile geometry must be Polygon or MultiPolygon.')

    return mapping(union_geom)
