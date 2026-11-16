import rasterio
import numpy as np
import os

# Directory containing DEM files
dem_dir = os.path.join(os.path.dirname(__file__), '../data/raster/dem')

def check_nodata_in_dem(dem_path):
    with rasterio.open(dem_path) as src:
        data = src.read(1)
        nodata = src.nodata
        if nodata is None:
            print(f"{os.path.basename(dem_path)}: No explicit nodata value set.")
            nodata = -9999  # fallback, but may not be correct
        nodata_count = np.sum(data == nodata)
        total_count = data.size
        percent_nodata = (nodata_count / total_count) * 100
        print(f"{os.path.basename(dem_path)}: {nodata_count} nodata pixels out of {total_count} ({percent_nodata:.2f}%)")
        return nodata_count, percent_nodata

def main():
    tif_files = [os.path.join(dem_dir, f) for f in os.listdir(dem_dir) if f.endswith('.tif')]
    if not tif_files:
        print("No DEM .tif files found in directory:", dem_dir)
        return
    for tif in tif_files:
        check_nodata_in_dem(tif)

if __name__ == "__main__":
    main()
