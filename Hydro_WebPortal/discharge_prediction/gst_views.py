"""
GST (Ground Station Telemetry) receiver endpoint.

The field device POSTs JSON to this endpoint; Django validates the credentials,
applies the same 4-stage pipeline as the legacy insert.php, and persists each
reading to the SensorReading model.

Pipeline stages (mirroring insert.php):
  1. RAW      — every authenticated reading is saved (processing_status='raw')
  2. FILTERED — if |depth - prev_depth| <= threshold, saved again (processing_status='filtered')
                The filtered depth is also set as water_depth on the raw row so the
                latest raw row always carries the most recent accepted depth.
  3. SEA LEVEL — WSE (cm) = GST_SEA_LEVEL_CONSTANT - (GST_SEA_LEVEL_X - depth_cm)
                 saved on the same filtered SensorReading row (processing_status='calibrated')
  4. STATISTICS — rolling median of last 11 calibrated WSE values (when >= 5 exist),
                  converted to metres, stored as discharge_depth on the same row
                  and is_validated set to True.

All constants come from Django settings (read from .env), never hardcoded here.
"""

import json
import logging
import statistics
from datetime import datetime, timezone

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from .models import DischargeStation, SensorReading

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_gst_timestamp(date_str, time_str):
    """
    Parse GST date/time strings into an aware datetime (UTC assumed).

    insert.php stores date/time as separate varchar columns; the device sends
    them in 'DD/MM/YYYY' and 'HH:MM:SS' format respectively.
    Falls back to now() if parsing fails.
    """
    try:
        dt = datetime.strptime(f"{date_str} {time_str}", "%d/%m/%Y %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        logger.warning("GST: could not parse timestamp date=%r time=%r, using now()", date_str, time_str)
        return datetime.now(tz=timezone.utc)


def _get_previous_filtered_depth(station):
    """Return the depth_cm of the most recent filtered/calibrated reading, or the initial baseline."""
    initial = settings.GST_FILTER_INITIAL_DEPTH
    latest = (
        SensorReading.objects
        .filter(station=station, processing_status__in=('filtered', 'calibrated'))
        .order_by('-timestamp')
        .values_list('water_depth', flat=True)
        .first()
    )
    if latest is not None:
        return float(latest)
    return initial


def _consecutive_raw_rejections(station):
    """
    Count how many raw rows exist after the most recent filtered row
    (equivalent to insert.php's consecutive rejection counter).
    """
    latest_filtered = (
        SensorReading.objects
        .filter(station=station, processing_status__in=('filtered', 'calibrated'))
        .order_by('-created_at')
        .values_list('created_at', flat=True)
        .first()
    )
    if latest_filtered is None:
        return SensorReading.objects.filter(station=station, processing_status='raw').count()
    return SensorReading.objects.filter(
        station=station,
        processing_status='raw',
        created_at__gt=latest_filtered,
    ).count()


def _rolling_median_wse(station, limit=11, min_samples=5):
    """
    Return median WSE (cm) from the last `limit` calibrated readings,
    or None if fewer than `min_samples` exist.
    """
    wse_values = list(
        SensorReading.objects
        .filter(station=station, processing_status='calibrated', water_surface_elevation__isnull=False)
        .order_by('-timestamp')
        .values_list('water_surface_elevation', flat=True)[:limit]
    )
    if len(wse_values) < min_samples:
        return None
    return statistics.median(wse_values)


# ---------------------------------------------------------------------------
# Main receiver view
# ---------------------------------------------------------------------------

@csrf_exempt
def gst_receive(request):
    """
    POST /discharge-prediction/api/gst/receive/

    Accepts the JSON payload sent by the GST field device, runs the 4-stage
    pipeline, and returns a JSON response mirroring the structure of insert.php.
    GET requests return a status message (so browsers don't see an error page).
    """
    if request.method == 'GET':
        return JsonResponse({
            "endpoint": "GST Receiver",
            "status": "online",
            "method": "POST only",
            "description": "This endpoint accepts POST requests from GST field devices.",
        })
    if request.method != 'POST':
        return JsonResponse({"error": "Method not allowed"}, status=405)

    # ---- 1. Parse body ----
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"response": "Invalid JSON"}, status=400)

    gst = body.get("GST_data")
    if not gst:
        return JsonResponse({"response": "Invalid JSON"}, status=400)

    # ---- 2. Validate credentials ----
    creds = gst.get("credentials", {})
    if (
        creds.get("username") != settings.GST_USERNAME
        or creds.get("password") != settings.GST_PASSWORD
    ):
        logger.warning("GST: invalid credentials from %s", request.META.get("REMOTE_ADDR"))
        return JsonResponse({"response": "Invalid credentials"}, status=401)

    # ---- 3. Validate payload structure ----
    station_data_list = gst.get("station_data")
    if not station_data_list or not isinstance(station_data_list, list):
        return JsonResponse({"response": "Missing station_data"}, status=400)

    station_block = station_data_list[0]
    sensors = station_block.get("sensors_data", {})

    station_id_block = gst.get("station_id", {})

    # ---- 4. Extract all fields ----
    device_id_str = str(station_id_block.get("id", ""))
    lat = station_id_block.get("location", {}).get("lat")
    lon = station_id_block.get("location", {}).get("lon")
    date_str = station_id_block.get("timestamp", {}).get("date", "")
    time_str = station_id_block.get("timestamp", {}).get("time", "")
    solar_curr = station_id_block.get("electrical_params", {}).get("sol_current")
    load_curr = station_id_block.get("electrical_params", {}).get("load_current")
    device_status_raw = gst.get("status", 1)
    wifi = gst.get("wifi_strength")
    ip_addr = station_block.get("ip_address")

    temp = sensors.get("temp")
    pressure = sensors.get("pressure")
    humidity = sensors.get("humidity")
    air_quality = sensors.get("air_quality")

    raw_depth = sensors.get("depth")
    if raw_depth is None:
        return JsonResponse({"response": "Missing depth in sensors_data"}, status=400)

    depth_cm = abs(float(raw_depth))  # cm, always positive (mirrors PHP abs())

    timestamp = _parse_gst_timestamp(date_str, time_str)

    # ---- 5. Resolve Django station (Mailung station_id='2') ----
    try:
        station = DischargeStation.objects.get(station_id='2')
    except DischargeStation.DoesNotExist:
        logger.error("GST: DischargeStation with station_id='2' (Mailung) not found")
        return JsonResponse({"response": "Station not configured"}, status=500)

    # ---- 6. Save RAW reading (every authenticated push) ----
    raw_reading = SensorReading(
        station=station,
        timestamp=timestamp,
        device_username=creds.get("username"),
        device_id=device_id_str,
        wifi_strength=int(wifi) if wifi is not None else None,
        ip_address=ip_addr,
        device_status=int(device_status_raw),
        temperature=float(temp) if temp is not None else None,
        humidity=float(humidity) if humidity is not None else None,
        pressure=float(pressure) if pressure is not None else None,
        air_quality=float(air_quality) if air_quality is not None else None,
        water_depth=depth_cm,   # raw cm from device
        latitude=float(lat) if lat is not None else None,
        longitude=float(lon) if lon is not None else None,
        solar_current=float(solar_curr) if solar_curr is not None else None,
        load_current=float(load_curr) if load_curr is not None else None,
        processing_status='raw',
        data_quality='good',
    )
    try:
        raw_reading.save()
    except Exception as exc:
        logger.error("GST: failed to save raw reading: %s", exc)
        return JsonResponse({"response": "failed to upload", "error": str(exc)}, status=500)

    response = {
        "response": "successfully uploaded",
        "main_table": True,
    }

    # ---- 7. Depth noise filter ----
    threshold = settings.GST_FILTER_THRESHOLD
    prev_depth = _get_previous_filtered_depth(station)
    depth_diff = abs(depth_cm - prev_depth)

    # Stuck-filter detection: if 50+ consecutive rejections, use median of last 11 raw
    consecutive_rejections = _consecutive_raw_rejections(station)
    filter_stuck = False
    median_fallback = None

    if consecutive_rejections >= 50 and depth_diff > threshold:
        last_11_raw = list(
            SensorReading.objects
            .filter(station=station, processing_status='raw')
            .order_by('-timestamp')
            .values_list('water_depth', flat=True)[:11]
        )
        if last_11_raw:
            median_fallback = statistics.median(last_11_raw)
            prev_depth = median_fallback
            depth_diff = abs(depth_cm - prev_depth)
            filter_stuck = True

    response["debug"] = {
        "current_depth_cm": depth_cm,
        "prev_depth_cm": prev_depth,
        "depth_diff_cm": round(depth_diff, 2),
        "threshold_cm": threshold,
        "meets_threshold": depth_diff <= threshold,
        "consecutive_rejections": consecutive_rejections,
        "filter_stuck_detected": filter_stuck,
        "median_fallback_applied": round(median_fallback, 2) if median_fallback is not None else False,
    }

    if depth_diff > threshold:
        response["filtered"] = False
        response["reason"] = "Depth difference exceeds threshold"
        response["depth_difference_cm"] = round(depth_diff, 2)
        return JsonResponse(response)

    # ---- 8. Stage 2 — Mark as filtered & compute sea-level WSE ----
    x = settings.GST_SEA_LEVEL_X
    sea_const = settings.GST_SEA_LEVEL_CONSTANT
    wse_cm = round(sea_const - (x - depth_cm), 2)   # e.g. 205300 - (835 - depth)

    raw_reading.processing_status = 'calibrated'
    raw_reading.water_surface_elevation = wse_cm
    response["filtered"] = True
    response["prev_depth_was_cm"] = prev_depth
    response["new_prev_depth_cm"] = depth_cm
    response["sea_level"] = {
        "formula": f"{sea_const} - ({x} - depth_cm)",
        "depth_cm": depth_cm,
        "wse_cm": wse_cm,
    }

    # ---- 9. Stage 4 — Rolling median statistics (WSE → metres) ----
    # Include the current reading's WSE in the window by temporarily appending
    wse_window = list(
        SensorReading.objects
        .filter(station=station, processing_status='calibrated', water_surface_elevation__isnull=False)
        .order_by('-timestamp')
        .values_list('water_surface_elevation', flat=True)[:10]   # 10 existing + 1 current = 11
    )
    wse_window.append(wse_cm)

    if len(wse_window) >= 5:
        median_wse_cm = statistics.median(wse_window)
        median_wse_m = round(median_wse_cm / 100, 4)
        raw_reading.discharge_depth = median_wse_m
        raw_reading.is_validated = True
        response["statistics"] = {
            "sample_count": len(wse_window),
            "median_wse_cm": round(median_wse_cm, 2),
            "median_wse_m": median_wse_m,
        }
    else:
        response["statistics"] = {
            "status": "skipped",
            "reason": f"Only {len(wse_window)} calibrated readings (need >= 5)",
        }

    # Save the updated row (calibrated + WSE + optional discharge_depth)
    try:
        raw_reading.save()
    except Exception as exc:
        logger.error("GST: failed to save calibrated reading: %s", exc)
        response["calibration_save_error"] = str(exc)

    return JsonResponse(response)
