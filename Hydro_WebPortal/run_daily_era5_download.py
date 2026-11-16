from daily_master_scheduler import daily_era5_download

if __name__ == "__main__":
    print("[INFO] Running one-time daily ERA5 data download...")
    daily_era5_download()
    print("[INFO] Daily ERA5 data download complete.")
