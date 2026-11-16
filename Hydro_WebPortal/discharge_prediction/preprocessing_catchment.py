#!/usr/bin/env python3
"""
Complete Runoff Data Preprocessing Pipeline
This script performs all preprocessing steps for runoff forecasting:
1. Unzip NetCDF files
2. Interpolate pressure level data to surface grid
3. Aggregate to daily data with catchment masking (weighted spatial average)
4. Extract point data
5. Merge surface and pressure data
6. Merge with discharge observations
7. Normalize data
8. Create sequences for training
"""

import os
import zipfile
import xarray as xr
import pandas as pd
import numpy as np
import joblib
import geopandas as gpd
from glob import glob
from sklearn.preprocessing import MinMaxScaler
from shapely.geometry import box, Polygon
from shapely.ops import unary_union

class RunoffDataPreprocessor:
    def __init__(self, base_dir, catchment_geojson_path, target_lat=None, target_lon=None, sequence_length=90, forecast_horizon=45):
        """
        Initialize the preprocessor with configuration
        
        Args:
            base_dir (str): Base directory containing the data
            catchment_geojson_path (str): Path to catchment GeoJSON file
            target_lat (float): Target latitude (kept for backward compatibility)
            target_lon (float): Target longitude (kept for backward compatibility)
            sequence_length (int): Length of input sequences
            forecast_horizon (int): Number of days to forecast
        """
        self.base_dir = base_dir
        self.catchment_geojson_path = catchment_geojson_path
        self.target_lat = target_lat
        self.target_lon = target_lon
        self.sequence_length = sequence_length
        self.forecast_horizon = forecast_horizon
        
        # Load catchment polygon
        self.catchment_gdf = gpd.read_file(catchment_geojson_path)
        self.catchment_polygon = self.catchment_gdf.geometry.unary_union
        print(f"✅ Loaded catchment from: {catchment_geojson_path}")
        print(f"   Catchment bounds: {self.catchment_polygon.bounds}")
        
        # Define paths
        self.paths = {
            "surface": os.path.join(base_dir, "surface"),
            "pressure": os.path.join(base_dir, "pressure"),
            "interpolated": os.path.join(base_dir, "processed", "interpolated"),
            "daily": os.path.join(base_dir, "processed", "daily"),
            "point": os.path.join(base_dir, "processed", "point"),
            "merged_csv": os.path.join(base_dir, "processed", "merged_input_data.csv"),
            "discharge_file": os.path.join(base_dir, "observed_discharge.csv"),
            "merged_csv_discharge": os.path.join(base_dir, "processed", "merged_input_data_with_discharge.csv"),
            "normalized_input": os.path.join(base_dir, "processed", "normalized_input_data.csv"),
            "X": os.path.join(base_dir, "processed", f"X_{sequence_length}day_{forecast_horizon}ahead.npy"),
            "Y": os.path.join(base_dir, "processed", f"Y_{sequence_length}day_{forecast_horizon}ahead.npy"),
            "Y_dates": os.path.join(base_dir, "processed", f"Y_dates_{sequence_length}day_{forecast_horizon}ahead.npy"),
            "scaler_x": os.path.join(base_dir, f"input_scaler_{sequence_length}day_{forecast_horizon}ahead.pkl"),
            "scaler_y": os.path.join(base_dir, f"discharge_scaler_{sequence_length}day_{forecast_horizon}ahead.pkl")
        }
        
        # Create necessary directories
        for path_key in ["interpolated", "daily", "point"]:
            os.makedirs(self.paths[path_key], exist_ok=True)
    
    def step1_unzip_netcdf_files(self):
        """Step 1: Unzip NetCDF files if they are compressed"""
        print("=" * 50)
        print("STEP 1: UNZIPPING NETCDF FILES")
        print("=" * 50)
        
        for filename in os.listdir(self.paths["surface"]):
            file_path = os.path.join(self.paths["surface"], filename)

            if filename.endswith(".nc"):
                try:
                    with zipfile.ZipFile(file_path, 'r') as zip_ref:
                        print(f"Unzipping: {filename}")
                        zip_ref.extract("data_0.nc", path=self.paths["surface"])

                    extracted_path = os.path.join(self.paths["surface"], "data_0.nc")
                    renamed_path = os.path.join(self.paths["surface"], filename)

                    os.remove(file_path)
                    os.rename(extracted_path, renamed_path)

                    print(f"→ Renamed to: {renamed_path}")

                except zipfile.BadZipFile:
                    print(f"✔ Valid NetCDF: {filename} (no action needed)")
                except FileNotFoundError:
                    print(f"⚠ data_0.nc not found after unzipping: {filename}")
                except Exception as e:
                    print(f"❌ Error processing {filename}: {e}")
    
    def step2_interpolate_pressure_data(self):
        """Step 2: Interpolate pressure level data to surface grid"""
        print("=" * 50)
        print("STEP 2: INTERPOLATING PRESSURE DATA")
        print("=" * 50)
        
        for filename in os.listdir(self.paths["pressure"]):
            if filename.endswith(".nc") and filename.startswith("era5_q925"):
                parts = filename.split("_")
                year = parts[2]
                month = parts[3].split(".")[0]

                print(f"📦 Processing {year}-{month}...")

                surface_file = os.path.join(self.paths["surface"], f"era5_land_{year}_{month}.nc")
                pressure_file = os.path.join(self.paths["pressure"], filename)
                output_file = os.path.join(self.paths["interpolated"], f"era5_q925_{year}_{month}.nc")

                if os.path.exists(output_file):
                    # print(f"✅ Already exists: {output_file}, skipping.")
                    continue

                try:
                    ds_land = xr.open_dataset(surface_file, engine="netcdf4")
                    ds_q = xr.open_dataset(pressure_file, engine="netcdf4")

                    # Get the full latitude/longitude grid from surface data
                    surface_lat_grid = ds_land.latitude
                    surface_lon_grid = ds_land.longitude

                    # Interpolate pressure data to surface grid
                    q_interp = ds_q['q'].interp(latitude=surface_lat_grid, longitude=surface_lon_grid, method='linear')
                    q_interp.to_netcdf(output_file)

                    print(f"✅ Saved: {output_file}")

                except Exception as e:
                    print(f"❌ Failed to process {filename}: {e}")
    
    def calculate_cell_weights(self, lats, lons):
        """
        Calculate overlap weights for each grid cell with the catchment polygon
        
        Args:
            lats: Array of latitude values
            lons: Array of longitude values
            
        Returns:
            2D array of weights (normalized to sum to 1)
        """
        # Calculate cell boundaries (assuming regular grid)
        lat_res = abs(float(lats[1] - lats[0])) if len(lats) > 1 else 0.1
        lon_res = abs(float(lons[1] - lons[0])) if len(lons) > 1 else 0.1
        
        weights = np.zeros((len(lats), len(lons)))
        
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                # Create cell polygon
                cell = box(
                    float(lon) - lon_res/2,
                    float(lat) - lat_res/2,
                    float(lon) + lon_res/2,
                    float(lat) + lat_res/2
                )
                
                # Calculate intersection area
                if cell.intersects(self.catchment_polygon):
                    intersection = cell.intersection(self.catchment_polygon)
                    weights[i, j] = intersection.area
        
        # Normalize weights to sum to 1
        total_weight = weights.sum()
        if total_weight > 0:
            weights = weights / total_weight
        
        return weights
    
    def step3_aggregate_to_daily(self):
        """Step 3: Aggregate hourly data to daily and mask cells outside catchment"""
        print("=" * 50)
        print("STEP 3: AGGREGATING TO DAILY DATA WITH CATCHMENT MASKING")
        print("=" * 50)
        
        input_dirs = [self.paths["surface"], self.paths["interpolated"]]

        for input_dir in input_dirs:
            for file in os.listdir(input_dir):
                if file.endswith(".nc"):
                    input_path = os.path.join(input_dir, file)
                    daily_path = os.path.join(self.paths["daily"], file.replace(".nc", "_daily.nc"))

                    if os.path.exists(daily_path):
                        # print(f"✅ Already exists: {daily_path}, skipping.")
                        continue

                    try:
                        ds = xr.open_dataset(input_path, engine="netcdf4")
                        
                        # Get coordinates
                        lats = ds.latitude.values
                        lons = ds.longitude.values
                        
                        # Calculate weights for catchment (for masking)
                        print(f"   Calculating catchment mask for {file}...")
                        weights = self.calculate_cell_weights(lats, lons)
                        
                        # Create mask (cells with zero weight are outside catchment)
                        mask = weights > 0
                        num_cells = mask.sum()
                        print(f"   Masking to {num_cells} grid cells within catchment")
                        
                        # Store weights for later use in step 4
                        if not hasattr(self, '_weights_cache'):
                            self._weights_cache = weights
                        
                        # Temporal aggregation only (keep spatial dimensions)
                        ds_daily = xr.Dataset()
                        
                        for var in ds.data_vars:
                            # Temporal aggregation
                            if var == 'tp':
                                daily_temporal = ds[var].resample(valid_time='1D').sum()
                            else:
                                daily_temporal = ds[var].resample(valid_time='1D').mean()
                            
                            # Apply catchment mask (set cells outside catchment to NaN)
                            mask_da = xr.DataArray(
                                mask,
                                coords={'latitude': lats, 'longitude': lons},
                                dims=['latitude', 'longitude']
                            )
                            
                            # Mask the data: where mask is False, set to NaN
                            masked_data = daily_temporal.where(mask_da)
                            ds_daily[var] = masked_data
                        
                        # Save with spatial dimensions intact
                        ds_daily.to_netcdf(daily_path)
                        print(f"✅ Processed: {file} (kept lat/lon dimensions for QGIS)")

                    except Exception as e:
                        print(f"❌ Error processing {file}: {e}")
    
    def step4_extract_point_data(self):
        """Step 4: Apply weighted spatial aggregation and convert to CSV"""
        print("=" * 50)
        print("STEP 4: APPLYING WEIGHTED SPATIAL AGGREGATION")
        print("=" * 50)
        
        for file in os.listdir(self.paths["daily"]):
            if file.endswith(".nc"):
                input_path = os.path.join(self.paths["daily"], file)
                var_name = file.replace("_daily.nc", "")
                output_csv = os.path.join(self.paths["point"], f"{var_name}.csv")

                if os.path.exists(output_csv):
                    # print(f"✅ Already exists: {output_csv}, skipping.")
                    continue

                try:
                    ds = xr.open_dataset(input_path)
                    
                    # Get coordinates and calculate weights if not cached
                    lats = ds.latitude.values
                    lons = ds.longitude.values
                    
                    if not hasattr(self, '_weights_cache'):
                        print(f"   Calculating weights for {var_name}...")
                        self._weights_cache = self.calculate_cell_weights(lats, lons)
                    
                    weights = self._weights_cache
                    
                    # Convert weights to xarray DataArray
                    weights_da = xr.DataArray(
                        weights,
                        coords={'latitude': lats, 'longitude': lons},
                        dims=['latitude', 'longitude']
                    )
                    
                    # Apply weighted spatial aggregation for each variable
                    aggregated_data = {}
                    for var in ds.data_vars:
                        # Weighted sum (works for both precipitation and averaged variables)
                        aggregated = (ds[var] * weights_da).sum(dim=['latitude', 'longitude'])
                        aggregated_data[var] = aggregated
                    
                    # Create aggregated dataset
                    ds_agg = xr.Dataset(aggregated_data)
                    
                    # Convert to dataframe
                    df = ds_agg.to_dataframe().reset_index()
                    df.to_csv(output_csv, index=False)
                    print(f"✅ Aggregated and converted: {var_name}")

                except Exception as e:
                    print(f"❌ Error processing {file}: {e}")
    
    def step5_merge_surface_pressure_data(self):
        """Step 5: Merge surface and pressure data"""
        print("=" * 50)
        print("STEP 5: MERGING SURFACE AND PRESSURE DATA")
        print("=" * 50)
        
        land_files = sorted(glob(os.path.join(self.paths["point"], "era5_land_*.csv")))
        q_files = sorted(glob(os.path.join(self.paths["point"], "era5_q925_*.csv")))

        land_dfs = []
        for f in land_files:
            df = pd.read_csv(f, parse_dates=["valid_time"])
            land_dfs.append(df[["valid_time", "t2m", "u10", "v10", "tp", "swvl1"]])

        df_land = pd.concat(land_dfs).sort_values("valid_time").reset_index(drop=True)

        q_dfs = []
        for f in q_files:
            df = pd.read_csv(f, parse_dates=["valid_time"])
            q_dfs.append(df[["valid_time", "q"]])

        df_q = pd.concat(q_dfs).sort_values("valid_time").reset_index(drop=True)

        merged = pd.merge(df_land, df_q, on="valid_time", how="inner")
        merged.to_csv(self.paths["merged_csv"], index=False)

        print("✅ Merged input dataset saved to:", self.paths["merged_csv"])
    
    def step6_merge_with_discharge(self):
        """Step 6: Merge with discharge observations"""
        print("=" * 50)
        print("STEP 6: MERGING WITH DISCHARGE DATA")
        print("=" * 50)
        
        if not os.path.exists(self.paths["discharge_file"]):
            print(f"❌ Discharge file not found: {self.paths['discharge_file']}")
            print("Please place your discharge observation file in the correct location.")
            return False

        # Load input features
        df_input = pd.read_csv(self.paths["merged_csv"], parse_dates=["valid_time"])

        # Load discharge data
        df_discharge = pd.read_csv(self.paths["discharge_file"], parse_dates=["valid_time"])

        # Clean and align dates
        df_input["valid_time"] = pd.to_datetime(df_input["valid_time"]).dt.date
        df_discharge["valid_time"] = pd.to_datetime(df_discharge["valid_time"]).dt.date

        # Merge only on exact matching dates
        df_merged = pd.merge(df_input, df_discharge, on="valid_time", how="inner")

        # Drop missing values
        df_merged = df_merged.dropna()

        # Save final merged data
        df_merged.to_csv(self.paths["merged_csv_discharge"], index=False)
        print("✅ Final merged dataset saved to:", self.paths["merged_csv_discharge"])
        return True
    
    def split_and_normalize(self, val_frac=0.2, test_frac=0.2):
        """
        Chronologically split merged data into train/val/test by fraction (no random shuffle), fit scalers on train, and save normalized splits.
        Args:
            val_frac (float): Fraction for validation (from end)
            test_frac (float): Fraction for test (from end)
        """
        print("=" * 50)
        print("SPLITTING AND NORMALIZING DATA (CHRONOLOGICAL, NO LEAKAGE)")
        print("=" * 50)
        df = pd.read_csv(self.paths["merged_csv_discharge"], parse_dates=["valid_time"])
        input_cols = ["t2m", "u10", "v10", "tp", "q", "swvl1", "Discharge"]  # 7 features (Discharge as autoregressive input)
        output_col = ["Discharge"]
        n = len(df)
        n_test = int(n * test_frac)
        n_val = int(n * val_frac)
        n_train = n - n_val - n_test
        train_df = df.iloc[:n_train].copy()
        val_df = df.iloc[n_train:n_train+n_val].copy()
        test_df = df.iloc[n_train+n_val:].copy() if n_test > 0 else None

        # Step 1: Fit output scaler FIRST on raw (unscaled) discharge
        # This ensures scaler_y correctly maps original discharge values
        output_scaler = MinMaxScaler()
        output_scaler.fit(train_df[output_col])
        joblib.dump(output_scaler, self.paths["scaler_y"])

        # Step 2: Fit input scaler on all 7 features (includes Discharge)
        # MinMaxScaler scales each column independently, so Discharge scaling
        # in input_scaler matches output_scaler (same min/max from same train data)
        input_scaler = MinMaxScaler()
        train_df[input_cols] = input_scaler.fit_transform(train_df[input_cols])
        joblib.dump(input_scaler, self.paths["scaler_x"])

        # Transform val/test with train input scaler only
        val_df[input_cols] = input_scaler.transform(val_df[input_cols])
        if test_df is not None:
            test_df[input_cols] = input_scaler.transform(test_df[input_cols])
        # Save splits
        train_df.to_csv(os.path.join(self.base_dir, "processed", "normalized_input_train.csv"), index=False)
        val_df.to_csv(os.path.join(self.base_dir, "processed", "normalized_input_val.csv"), index=False)
        if test_df is not None:
            test_df.to_csv(os.path.join(self.base_dir, "processed", "normalized_input_test.csv"), index=False)
        print(f"✅ Train/val/test splits saved and normalized. Train: {len(train_df)}, Val: {len(val_df)}, Test: {len(test_df) if test_df is not None else 0}")
    
    def step8_create_sequences_split(self, split='train'):
        """
        Create sequences for a given split (train/val/test) after proper normalization.
        """
        print(f"=" * 50)
        print(f"STEP 8: CREATING SEQUENCES FOR {split.upper()} (45th day only)")
        print("=" * 50)
        feature_cols = ["t2m", "u10", "v10", "tp", "q", "swvl1","Discharge"]
        target_col = "Discharge"
        split_file = os.path.join(self.base_dir, "processed", f"normalized_input_{split}.csv")
        df = pd.read_csv(split_file, parse_dates=["valid_time"])
        X_data = df[feature_cols].values
        y_data = df[target_col].values
        dates = df["valid_time"].values
        X, y, y_dates = [], [], []
        for i in range(len(df) - self.sequence_length - self.forecast_horizon + 1):
            X_seq = X_data[i:i + self.sequence_length]
            y_seq = y_data[i + self.sequence_length : i + self.sequence_length + self.forecast_horizon]
            y_seq_dates = dates[i + self.sequence_length : i + self.sequence_length + self.forecast_horizon]
            if not np.isnan(X_seq).any() and not np.isnan(y_seq).any():
                X.append(X_seq)
                y.append(y_seq[-1])
                y_dates.append(y_seq_dates[-1])
        X = np.array(X)
        y = np.array(y)
        y_dates = np.array(y_dates)
        np.save(os.path.join(self.base_dir, "processed", f"X_{split}.npy"), X)
        np.save(os.path.join(self.base_dir, "processed", f"Y_{split}.npy"), y)
        np.save(os.path.join(self.base_dir, "processed", f"Y_dates_{split}.npy"), y_dates)
        print(f"✅ Sequences for {split} created and saved: X shape {X.shape}, y shape {y.shape}, dates shape {y_dates.shape}")

    def run_complete_pipeline(self, skip_steps=None):
        """
        Run the complete preprocessing pipeline
        
        Args:
            skip_steps (list): List of step numbers to skip (1-8)
        """
        if skip_steps is None:
            skip_steps = []
        
        print("Starting Complete Runoff Data Preprocessing Pipeline")
        print(f"Base Directory: {self.base_dir}")
        print(f"Target Coordinates: ({self.target_lat}, {self.target_lon})")
        print(f"Sequence Length: {self.sequence_length}")
        print(f"Forecast Horizon: {self.forecast_horizon}")
        print()
        
        steps = [
            (1, self.step1_unzip_netcdf_files),
            (2, self.step2_interpolate_pressure_data),
            (3, self.step3_aggregate_to_daily),
            (4, self.step4_extract_point_data),
            (5, self.step5_merge_surface_pressure_data),
            (6, self.step6_merge_with_discharge),
            # Do NOT run step7_normalize_data or step8_create_sequences here!
        ]

        # Run steps 1–6 as before
        for step_num, step_func in steps:
            if step_num in skip_steps:
                print(f"⏭️ Skipping Step {step_num}")
                continue
            try:
                result = step_func()
                if result is False:
                    print(f"❌ Step {step_num} failed. Stopping pipeline.")
                    break
                print()
            except Exception as e:
                print(f"❌ Error in Step {step_num}: {e}")
                break

        # Now run split_and_normalize and create sequences for each split
        self.split_and_normalize(val_frac=0.15, test_frac=0.15)
        for split in ['train', 'val', 'test']:
            self.step8_create_sequences_split(split=split)

        print("🎉 Preprocessing pipeline completed!")

# Example usage and configuration
if __name__ == "__main__":
    # Configuration - directly modify this for your project
    config = {
        "base_dir": r"/Users/apn_hq/SDAPTeam/Hydropower/HydroAPN/RUNoff/LowerLikhu/catchment_process/catchment_crop",
        "catchment_geojson": r"/Users/apn_hq/SDAPTeam/Hydropower/HydroAPN/RUNoff/LowerLikhu/catchment_process/catchment_crop/catchment/LowerLikhu/catchment.geojson",
        "target_lat": 27.4284,
        "target_lon": 86.2517
    }
    
    # Create preprocessor with catchment masking
    preprocessor = RunoffDataPreprocessor(
        base_dir=config["base_dir"],
        catchment_geojson_path=config["catchment_geojson"],
        target_lat=config["target_lat"],
        target_lon=config["target_lon"],
        sequence_length=60,
        forecast_horizon=45
    )
    
    # Run complete pipeline
    # To skip certain steps, pass skip_steps=[1, 2, 3] etc.
    preprocessor.run_complete_pipeline(skip_steps=[1,2,3,4,5,6])
    
    # Or run individual steps:
    # preprocessor.step1_unzip_netcdf_files()
    # preprocessor.step2_interpolate_pressure_data()
    # etc.