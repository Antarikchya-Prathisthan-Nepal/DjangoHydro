import re
import json
import os
import csv

def sanitize_worksheet(name):
    # Sanitize station names to safe worksheet keys.
    s = (name or "").strip()
    s = s.replace("@", "")
    s = s.replace("(", " ").replace(")", " ")
    s = s.replace(" ", "_")
    s = re.sub(r'[^a-zA-Z0-9_]', '', s) 
    s = re.sub(r'_+', '_', s)
    return s.strip("_") or "Unknown"

html_path = r"C:\Users\Dell\SDAP\Runoff\surface_obs.html"
data_json = None

if os.path.exists(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        content = f.read()
        match = re.search(r"var\s+observation_data\s*=\s*(\[.*?\]);", content, re.DOTALL)
        if match:
            try:
                data_json = json.loads(match.group(1))
            except Exception as e:
                print(f"Error parsing local JSON: {e}")

if not data_json:
    import requests
    print("Fetching from remote...")
    try:
        resp = requests.get("https://dhm.gov.np/hydrology/surface-observation", timeout=30)
        match = re.search(r"var\s+observation_data\s*=\s*(\[.*?\]);", resp.text, re.DOTALL)
        if match:
            data_json = json.loads(match.group(1))
    except Exception as e:
        print(f"Error fetching from remote: {e}")

if not data_json:
    print("Could not find observation_data")
    exit(1)

humidity_stations = {}
csv_rows = []

for item in data_json:
    series_id = None
    if "observations" in item:
        for obs in item["observations"]:
            if obs.get("parameter_code") == "RH_1H":
                series_id = str(obs.get("series_id"))
                break
    
    if series_id:
        st_name = item.get("name", "Unknown")
        ws_name = sanitize_worksheet(st_name)

        # Keep keys unique when two stations sanitize to same worksheet name.
        key_name = ws_name
        if key_name in humidity_stations and humidity_stations[key_name]["seriesid"] != series_id:
            key_name = f"{ws_name}_{item.get('id', 'X')}"

        humidity_stations[key_name] = {
            "seriesid": series_id,
            "worksheet": key_name
        }

        meta = item.get("meta_data") or {}
        csv_rows.append({
            "station_name": key_name,
            "station_id": item.get("id", ""),
            "identifier": item.get("identifier", ""),
            "province": meta.get("Province", ""),
            "district": meta.get("District", ""),
            "station_type": meta.get("Station Type", ""),
            "rh1h_series_id": series_id
        })

# Sort humidity_stations by key
sorted_keys = sorted(humidity_stations.keys())
sorted_humidity_stations = {k: humidity_stations[k] for k in sorted_keys}

# Write all_humidity_stations.py
with open("all_humidity_stations.py", "w", encoding="utf-8") as f:
    f.write("HUMIDITY_STATIONS = ")
    json.dump(sorted_humidity_stations, f, indent=4)
    f.write("\n")

# Write dhm_humidity_station_ids.csv
with open("dhm_humidity_station_ids.csv", "w", encoding="utf-8", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=["station_name", "station_id", "identifier", "province", "district", "station_type", "rh1h_series_id"])
    writer.writeheader()
    for row in csv_rows:
        writer.writerow(row)

print(f"Station count: {len(humidity_stations)}")
