import json
import sys
from shapely.geometry import shape

# Usage: python check_watershed_bounds.py <geojson_file>

def print_watershed_bounds(geojson_path):
    with open(geojson_path, 'r') as f:
        data = json.load(f)
    # Assume FeatureCollection or single Feature
    if data.get('type') == 'FeatureCollection':
        for i, feature in enumerate(data['features']):
            geom = shape(feature['geometry'])
            print(f"Feature {i+1} bounds: {geom.bounds}")
    elif data.get('type') == 'Feature':
        geom = shape(data['geometry'])
        print(f"Feature bounds: {geom.bounds}")
    else:
        print("Unknown GeoJSON type.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python check_watershed_bounds.py <geojson_file>")
    else:
        print_watershed_bounds(sys.argv[1])
