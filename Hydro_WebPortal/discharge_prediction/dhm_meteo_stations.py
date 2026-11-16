"""
DHM meteorological station configuration for fetch_dhm_meteo management command.

Structure
---------
Each key is a human-readable station name matching the DHMMeteoStation.name field.
Each value contains:

  variable_type        – 'rainfall' or 'climate'
  links_to             – list of DischargeStation.station_id values that use this source
  seriesid             – DHM series ID for rainfall and temperature POST requests
  humidity_seriesid    – DHM series ID for relative humidity (surface-observation)
  wind_speed_seriesid  – DHM series ID for wind speed (surface-observation)
  wind_dir_seriesid    – DHM series ID for wind direction (surface-observation)

Fetch strategy:
  rainfall  → POST https://dhm.gov.np/hydrology/getRainfallWatchBySeriesId_single
  climate   → GET  https://dhm.gov.np/hydrology/surface-observation
              (single page fetch shared across all climate stations in one run)

Station ID mapping (DischargeStation.station_id):
  '1'  → Lower Likhnu
  '2'  → Mailung  (update if your DB station_id differs)
"""

DHM_METEO_STATIONS = {
    # ── Mailung ────────────────────────────────────────────────────────────────
    "Pansayakhola": {
        "variable_type": "rainfall",
        "links_to": ["2"],          # Mailung station_id
        "seriesid": "5756",
    },
    "Nuwakot": {
        "variable_type": "climate",
        "links_to": ["2"],          # Mailung station_id
        "seriesid": "9651",                  # temperature
        "humidity_seriesid": "9647",
        "wind_speed_seriesid": "9619",
        "wind_dir_seriesid": "9609",
    },

    # ── Lower Likhnu ───────────────────────────────────────────────────────────
    "Siruwa": {
        "variable_type": "rainfall",
        "links_to": ["1"],          # Lower Likhnu station_id
        "seriesid": "21133",
    },
    "Jiri": {
        "variable_type": "climate",
        "links_to": ["1"],          # Lower Likhnu station_id
        "seriesid": "6901",                  # temperature
        "humidity_seriesid": "6897",
        "wind_speed_seriesid": "6857",
        "wind_dir_seriesid": "6843",
    },
}
