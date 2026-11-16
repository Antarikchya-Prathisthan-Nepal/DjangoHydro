import rasterio
import os

dem_dir = os.path.join(os.path.dirname(__file__), '../data/raster/dem')

def print_dem_info(dem_path):
    with rasterio.open(dem_path) as src:
        print(f"File: {os.path.basename(dem_path)}")
        print(f"  CRS: {src.crs}")
        print(f"  Bounds: {src.bounds}")
        print(f"  Width x Height: {src.width} x {src.height}")
        print(f"  Resolution: {src.res}")
        print()

def main():
    tif_files = [os.path.join(dem_dir, f) for f in os.listdir(dem_dir) if f.endswith('.tif')]
    if not tif_files:
        print("No DEM .tif files found in directory:", dem_dir)
        return
    for tif in tif_files:
        print_dem_info(tif)

if __name__ == "__main__":
    main()
