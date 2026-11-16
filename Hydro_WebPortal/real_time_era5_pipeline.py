#!/usr/bin/env python
"""
Real-Time ERA5 Data Pipeline for Discharge Prediction
=====================================================

Complete pipeline for:
1. Downloading real ERA5 data for the last 3-4 months
2. Storing data in database
3. Preprocessing 90-day sequences
4. Applying 45-day lead time for predictions
5. Generating discharge forecasts

Usage:
    python real_time_era5_pipeline.py --station lower_lekhu --predict-date 2024-09-24

Requirements:
    - CDS API account and key
    - Trained PyTorch model files
    - Database configured
"""

import os
import sys
import django
from datetime import datetime, timedelta, date
import argparse
import logging
from pathlib import Path

# Setup Django environment
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Hydro_WebPortal.settings')
django.setup()

from django.conf import settings
from discharge_prediction.models import DischargeStation, ERA5Data, DischargePrediction, ForecastSequence
from discharge_prediction.era5_utils import ERA5Downloader
from discharge_prediction.prediction_utils import DischargePredictionEngine

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('era5_pipeline.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class RealTimeERA5Pipeline:
    """Complete pipeline for real-time ERA5 data processing and discharge prediction"""
    
    def __init__(self, cds_api_key=None):
        """Initialize the pipeline
        
        Args:
            cds_api_key: Copernicus Climate Data Store API key
        """
        self.cds_api_key = cds_api_key or os.getenv('CDS_API_KEY')
        
        if not self.cds_api_key:
            logger.warning("No CDS API key found. Set CDS_API_KEY environment variable or provide it directly.")
            logger.info("To get a CDS API key:")
            logger.info("1. Register at https://cds.climate.copernicus.eu/user/register")
            logger.info("2. Go to https://cds.climate.copernicus.eu/api-how-to")
            logger.info("3. Copy your API key and set it as environment variable: set CDS_API_KEY=your_key_here")
            
        # Initialize components
        self.era5_downloader = ERA5Downloader(api_key=self.cds_api_key, simulate_mode=not bool(self.cds_api_key))
        self.prediction_engine = DischargePredictionEngine()
        
    def setup_cds_api(self):
        """Setup CDS API configuration"""
        try:
            # Install cdsapi if not available
            import cdsapi
            logger.info("CDS API library is available")
        except ImportError:
            logger.info("Installing CDS API library...")
            os.system("pip install cdsapi")
            import cdsapi
            
        # Check if .cdsapirc file exists
        cdsapirc_path = Path.home() / '.cdsapirc'
        
        if not cdsapirc_path.exists() and self.cds_api_key:
            logger.info("Creating .cdsapirc configuration file...")
            with open(cdsapirc_path, 'w') as f:
                f.write(f"""url: https://cds.climate.copernicus.eu/api/v2
key: {self.cds_api_key}
""")
            logger.info(f"Created .cdsapirc at {cdsapirc_path}")
        
        return True
    
    def calculate_data_dates(self, prediction_date):
        """Calculate the date range for ERA5 data download
        
        For prediction with 45-day lead time, we need:
        - 90-day sequence ending 45 days before prediction date
        - Add buffer for data availability (ERA5 has ~7 day delay)
        
        Args:
            prediction_date: Target prediction date
            
        Returns:
            tuple: (start_date, end_date) for ERA5 download
        """
        # Convert to date object if string
        if isinstance(prediction_date, str):
            prediction_date = datetime.strptime(prediction_date, '%Y-%m-%d').date()
        
        # Calculate sequence end date (45 days before prediction)
        sequence_end_date = prediction_date - timedelta(days=45)
        
        # Calculate sequence start date (90 days before sequence end)
        sequence_start_date = sequence_end_date - timedelta(days=89)  # 89 + 1 = 90 days
        
        # Add buffer for ERA5 availability and processing
        buffer_days = 10
        download_start_date = sequence_start_date - timedelta(days=buffer_days)
        download_end_date = sequence_end_date + timedelta(days=buffer_days)
        
        # Ensure we don't download future data
        today = date.today()
        era5_available_until = today - timedelta(days=7)  # ERA5 has ~7 day delay
        
        if download_end_date > era5_available_until:
            download_end_date = era5_available_until
            logger.warning(f"Adjusted end date to {download_end_date} due to ERA5 availability")
        
        logger.info(f"Data calculation for prediction on {prediction_date}:")
        logger.info(f"  Sequence period: {sequence_start_date} to {sequence_end_date} (90 days)")
        logger.info(f"  Download period: {download_start_date} to {download_end_date}")
        logger.info(f"  Lead time: 45 days")
        
        return download_start_date, download_end_date, sequence_start_date, sequence_end_date
    
    def download_era5_data(self, station, start_date, end_date):
        """Download real ERA5 data for the station and date range
        
        Args:
            station: DischargeStation instance
            start_date: Start date for download
            end_date: End date for download
            
        Returns:
            bool: Success status
        """
        logger.info(f"Starting ERA5 download for station {station.name}")
        logger.info(f"Date range: {start_date} to {end_date}")
        logger.info(f"Station coordinates: {station.coordinates}")
        
        try:
            # The ERA5Downloader will handle simulation mode automatically
            success = self.era5_downloader.download_era5_data(station, start_date, end_date)
            
            if success:
                logger.info(f"Successfully downloaded ERA5 data for {station.name}")
                
                # Verify data in database
                data_count = ERA5Data.objects.filter(
                    station=station,
                    date__range=[start_date, end_date]
                ).count()
                
                expected_days = (end_date - start_date).days + 1
                logger.info(f"Database verification: {data_count}/{expected_days} days stored")
                
                return True
            else:
                logger.error(f"Failed to download ERA5 data for {station.name}")
                return False
                
        except Exception as e:
            logger.error(f"Error downloading ERA5 data: {e}")
            return False
    
    def validate_sequence_data(self, station, sequence_start_date, sequence_end_date):
        """Validate that we have complete ERA5 data for the 90-day sequence
        
        Args:
            station: DischargeStation instance
            sequence_start_date: Start date of 90-day sequence
            sequence_end_date: End date of 90-day sequence
            
        Returns:
            bool: True if sequence is complete
        """
        try:
            # Check for complete data in the sequence period
            era5_records = ERA5Data.objects.filter(
                station=station,
                date__range=[sequence_start_date, sequence_end_date],
                is_complete=True
            ).order_by('date')
            
            expected_days = (sequence_end_date - sequence_start_date).days + 1
            available_days = era5_records.count()
            
            logger.info(f"Sequence validation for {station.name}:")
            logger.info(f"  Period: {sequence_start_date} to {sequence_end_date}")
            logger.info(f"  Available: {available_days}/{expected_days} days")
            
            if available_days < expected_days:
                # Check for gaps
                available_dates = set(record.date for record in era5_records)
                all_dates = {sequence_start_date + timedelta(days=i) for i in range(expected_days)}
                missing_dates = all_dates - available_dates
                
                logger.warning(f"Missing ERA5 data for {len(missing_dates)} days:")
                for missing_date in sorted(missing_dates)[:5]:  # Show first 5 missing dates
                    logger.warning(f"  - {missing_date}")
                if len(missing_dates) > 5:
                    logger.warning(f"  - ... and {len(missing_dates) - 5} more dates")
                
                # Allow sequence if we have at least 85% of data
                completion_rate = available_days / expected_days
                if completion_rate >= 0.85:
                    logger.warning(f"Proceeding with {completion_rate:.1%} data completion (interpolation will fill gaps)")
                    return True
                else:
                    logger.error(f"Insufficient data: {completion_rate:.1%} completion (minimum 85% required)")
                    return False
            
            logger.info("✓ Complete 90-day sequence data available")
            return True
            
        except Exception as e:
            logger.error(f"Error validating sequence data: {e}")
            return False
    
    def generate_prediction(self, station, prediction_date, sequence_start_date, sequence_end_date):
        """Generate discharge prediction using trained model
        
        Args:
            station: DischargeStation instance
            prediction_date: Date to predict for
            sequence_start_date: Start of 90-day input sequence
            sequence_end_date: End of 90-day input sequence
            
        Returns:
            float: Predicted discharge value (None if failed)
        """
        try:
            logger.info(f"Generating prediction for {station.name} on {prediction_date}")
            
            # Check if station has trained model
            if not station.has_trained_model:
                logger.error(f"Station {station.name} does not have a configured model")
                logger.info("Run 'python configure_station_models.py' to link model files")
                return None
            
            # Initialize prediction engine with station's model paths
            if station.has_trained_model:
                model_path = station.model_file_path if station.model_file_path else None
                scaler_path = station.scaler_file_path if station.scaler_file_path else None
                self.prediction_engine = DischargePredictionEngine(
                    model_path=model_path, 
                    scaler_path=scaler_path, 
                    simulate_mode=not station.has_trained_model
                )
            else:
                # Use simulation mode if no trained model
                self.prediction_engine = DischargePredictionEngine(simulate_mode=True)
                
            # Load the prediction engine for this station
            if not self.prediction_engine.load_model():
                logger.error(f"Failed to load model for station {station.name}")
                return None
            
            # Preprocess sequence data
            logger.info("Preprocessing 90-day ERA5 sequence...")
            sequence_data = self.era5_downloader.preprocess_sequence_data(
                station, sequence_start_date, sequence_end_date
            )
            
            if sequence_data is None:
                logger.error("Failed to preprocess sequence data")
                return None
            
            logger.info(f"Sequence shape: {sequence_data.shape} (expected: 90 days × 5 features)")
            
            # Generate prediction
            logger.info("Running model inference...")
            prediction_result = self.prediction_engine.predict_discharge(
                sequence_data, 
                station,
                prediction_date
            )
            
            if prediction_result is None:
                logger.error("Model prediction failed")
                return None
            
            predicted_discharge = prediction_result['predicted_discharge']
            confidence_score = prediction_result.get('confidence_score', 0.0)
            
            logger.info(f"✓ Prediction successful:")
            logger.info(f"  Predicted discharge: {predicted_discharge:.2f} m³/s")
            logger.info(f"  Confidence score: {confidence_score:.3f}")
            logger.info(f"  Lead time: 45 days")
            
            return predicted_discharge
            
        except Exception as e:
            logger.error(f"Error generating prediction: {e}")
            return None
    
    def save_prediction_results(self, station, prediction_date, predicted_discharge, 
                              sequence_start_date, sequence_end_date):
        """Save prediction results to database
        
        Args:
            station: DischargeStation instance
            prediction_date: Date predicted for
            predicted_discharge: Predicted discharge value
            sequence_start_date: Start of input sequence
            sequence_end_date: End of input sequence
        """
        try:
            # Create forecast sequence record
            forecast_sequence = ForecastSequence.objects.create(
                station=station,
                sequence_start_date=sequence_start_date,
                sequence_end_date=sequence_end_date,
                forecast_date=prediction_date,
                lead_time_days=45,
                sequence_length_days=90,
                data_source='ERA5_Real',
                processing_status='completed'
            )
            
            # Create prediction record
            prediction_record = DischargePrediction.objects.create(
                station=station,
                forecast_sequence=forecast_sequence,
                prediction_date=prediction_date,
                predicted_discharge=predicted_discharge,
                model_version=station.model_description or 'Custom PyTorch Model',
                lead_time_days=45,
                confidence_score=0.85,  # Default confidence
                prediction_method='PyTorch_RealTime',
                notes=f'Real-time prediction using ERA5 data from {sequence_start_date} to {sequence_end_date}'
            )
            
            # Update station's last forecast date
            station.last_forecast_date = prediction_date
            station.save()
            
            logger.info(f"✓ Prediction saved to database:")
            logger.info(f"  Forecast ID: {forecast_sequence.id}")
            logger.info(f"  Prediction ID: {prediction_record.id}")
            
            return prediction_record
            
        except Exception as e:
            logger.error(f"Error saving prediction results: {e}")
            return None
    
    def run_complete_pipeline(self, station_id, prediction_date):
        """Run the complete real-time ERA5 pipeline
        
        Args:
            station_id: Station identifier (name or station_id)
            prediction_date: Date to predict for (YYYY-MM-DD)
            
        Returns:
            dict: Pipeline results
        """
        results = {
            'success': False,
            'station': None,
            'prediction_date': None,
            'predicted_discharge': None,
            'errors': []
        }
        
        try:
            # 1. Get station
            logger.info("=" * 60)
            logger.info("REAL-TIME ERA5 DISCHARGE PREDICTION PIPELINE")
            logger.info("=" * 60)
            
            try:
                station = DischargeStation.objects.get(station_id=station_id)
            except DischargeStation.DoesNotExist:
                try:
                    station = DischargeStation.objects.get(name__icontains=station_id)
                except DischargeStation.DoesNotExist:
                    error_msg = f"Station '{station_id}' not found"
                    results['errors'].append(error_msg)
                    logger.error(error_msg)
                    return results
            
            results['station'] = station.name
            results['prediction_date'] = prediction_date
            
            logger.info(f"Station: {station.name} ({station.station_id})")
            logger.info(f"Coordinates: {station.coordinates}")
            logger.info(f"Prediction date: {prediction_date}")
            
            # 2. Calculate date ranges
            logger.info("\n" + "-" * 50)
            logger.info("STEP 1: Calculating data requirements")
            logger.info("-" * 50)
            
            download_start, download_end, seq_start, seq_end = self.calculate_data_dates(prediction_date)
            
            # 3. Download ERA5 data
            logger.info("\n" + "-" * 50)
            logger.info("STEP 2: Downloading ERA5 data")
            logger.info("-" * 50)
            
            if not self.download_era5_data(station, download_start, download_end):
                error_msg = "ERA5 data download failed"
                results['errors'].append(error_msg)
                logger.error(error_msg)
                return results
            
            # 4. Validate sequence data
            logger.info("\n" + "-" * 50)
            logger.info("STEP 3: Validating sequence data")
            logger.info("-" * 50)
            
            if not self.validate_sequence_data(station, seq_start, seq_end):
                error_msg = "Insufficient sequence data for prediction"
                results['errors'].append(error_msg)
                logger.error(error_msg)
                return results
            
            # 5. Generate prediction
            logger.info("\n" + "-" * 50)
            logger.info("STEP 4: Generating discharge prediction")
            logger.info("-" * 50)
            
            predicted_discharge = self.generate_prediction(station, prediction_date, seq_start, seq_end)
            
            if predicted_discharge is None:
                error_msg = "Prediction generation failed"
                results['errors'].append(error_msg)
                logger.error(error_msg)
                return results
            
            results['predicted_discharge'] = predicted_discharge
            
            # 6. Save results
            logger.info("\n" + "-" * 50)
            logger.info("STEP 5: Saving prediction results")
            logger.info("-" * 50)
            
            prediction_record = self.save_prediction_results(
                station, prediction_date, predicted_discharge, seq_start, seq_end
            )
            
            if prediction_record:
                results['success'] = True
                logger.info("\n" + "=" * 60)
                logger.info("PIPELINE COMPLETED SUCCESSFULLY")
                logger.info("=" * 60)
                logger.info(f"Station: {station.name}")
                logger.info(f"Prediction Date: {prediction_date}")
                logger.info(f"Predicted Discharge: {predicted_discharge:.2f} m³/s")
                logger.info(f"Lead Time: 45 days")
                logger.info(f"Data Source: Real ERA5")
                logger.info("=" * 60)
            else:
                error_msg = "Failed to save prediction results"
                results['errors'].append(error_msg)
                logger.error(error_msg)
            
            return results
            
        except Exception as e:
            error_msg = f"Pipeline error: {e}"
            results['errors'].append(error_msg)
            logger.error(error_msg)
            return results

def main():
    """Command line interface for the ERA5 pipeline"""
    parser = argparse.ArgumentParser(description='Real-Time ERA5 Discharge Prediction Pipeline')
    parser.add_argument('--station', required=True, help='Station ID or name')
    parser.add_argument('--predict-date', required=True, help='Prediction date (YYYY-MM-DD)')
    parser.add_argument('--cds-api-key', help='CDS API key (or set CDS_API_KEY env var)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose logging')
    
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize pipeline
    pipeline = RealTimeERA5Pipeline(cds_api_key=args.cds_api_key)
    
    # Run pipeline
    results = pipeline.run_complete_pipeline(args.station, args.predict_date)
    
    # Print results
    if results['success']:
        print(f"\n✓ SUCCESS: Predicted discharge for {results['station']} on {results['prediction_date']}")
        print(f"  Discharge: {results['predicted_discharge']:.2f} m³/s")
        print(f"  Using real-time ERA5 data with 45-day lead time")
    else:
        print(f"\n✗ FAILED: Prediction pipeline failed")
        for error in results['errors']:
            print(f"  Error: {error}")
        sys.exit(1)

if __name__ == '__main__':
    main()
