"""
Django Management Command: Create Prediction Sequences
=====================================================

Usage:
    python manage.py create_sequences --station LOWER_LEKHU --date 2025-03-01
    python manage.py create_sequences --station LOWER_LEKHU --monthly 2025-03
    python manage.py create_sequences --all-stations --date 2025-03-01
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from datetime import date, datetime, timedelta
from discharge_prediction.models import DischargeStation, ERA5Data, DischargePrediction
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Create prediction sequences and generate discharge forecasts'

    def add_arguments(self, parser):
        parser.add_argument(
            '--station',
            type=str,
            help='Station ID to generate predictions for'
        )
        parser.add_argument(
            '--all-stations',
            action='store_true',
            help='Generate predictions for all active stations'
        )
        parser.add_argument(
            '--date',
            type=str,
            help='Target prediction date (YYYY-MM-DD)'
        )
        parser.add_argument(
            '--monthly',
            type=str,
            help='Generate monthly forecast (YYYY-MM)'
        )
        parser.add_argument(
            '--days',
            type=int,
            default=1,
            help='Number of days to forecast (default: 1)'
        )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS('🌊 Starting Discharge Prediction Sequence Creation')
        )

        try:
            # Import here to avoid circular imports
            from create_prediction_sequences import SequenceCreator
            
            creator = SequenceCreator()
            
            # Determine stations to process
            if options['all_stations']:
                stations = DischargeStation.objects.filter(is_active=True)
                if not stations.exists():
                    raise CommandError('No active stations found')
                self.stdout.write(f'Processing {stations.count()} active stations')
            elif options['station']:
                try:
                    stations = [DischargeStation.objects.get(station_id=options['station'])]
                    self.stdout.write(f'Processing station: {stations[0].name}')
                except DischargeStation.DoesNotExist:
                    raise CommandError(f'Station {options["station"]} not found')
            else:
                raise CommandError('Must specify either --station or --all-stations')

            # Determine target dates
            if options['monthly']:
                # Monthly forecast
                try:
                    year, month = map(int, options['monthly'].split('-'))
                    target_month_start = date(year, month, 1)
                    self.stdout.write(f'Generating monthly forecast for {target_month_start.strftime("%B %Y")}')
                    
                    for station in stations:
                        self._generate_monthly_forecast(creator, station, target_month_start)
                        
                except ValueError:
                    raise CommandError('Monthly format should be YYYY-MM')
                    
            elif options['date']:
                # Single date or multi-day forecast
                try:
                    start_date = datetime.strptime(options['date'], '%Y-%m-%d').date()
                    days = options['days']
                    
                    self.stdout.write(f'Generating {days} day(s) forecast starting from {start_date}')
                    
                    for station in stations:
                        self._generate_daily_forecasts(creator, station, start_date, days)
                        
                except ValueError:
                    raise CommandError('Date format should be YYYY-MM-DD')
            else:
                raise CommandError('Must specify either --date or --monthly')

            self.stdout.write(
                self.style.SUCCESS('✅ Prediction sequence creation completed successfully')
            )

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'❌ Error: {str(e)}')
            )
            raise

    def _generate_daily_forecasts(self, creator, station, start_date, days):
        """Generate daily forecasts for specified number of days"""
        self.stdout.write(f'\n🏭 Station: {station.name}')
        
        # Check data availability
        era5_count = ERA5Data.objects.filter(station=station, is_complete=True).count()
        if era5_count < 90:
            self.stdout.write(
                self.style.WARNING(f'⚠️  Insufficient ERA5 data: {era5_count} records (need ≥90)')
            )
            return

        successful_predictions = 0
        
        for i in range(days):
            target_date = start_date + timedelta(days=i)
            
            try:
                prediction = creator.generate_prediction(station, target_date)
                successful_predictions += 1
                
                self.stdout.write(
                    f'  📅 {target_date}: {prediction.predicted_discharge:.2f} m³/s '
                    f'(confidence: {prediction.prediction_confidence:.3f})'
                )
                
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f'  ❌ {target_date}: Failed - {str(e)}')
                )

        self.stdout.write(
            f'📊 Completed {successful_predictions}/{days} predictions for {station.name}'
        )

    def _generate_monthly_forecast(self, creator, station, target_month_start):
        """Generate complete monthly forecast"""
        self.stdout.write(f'\n🏭 Station: {station.name}')
        
        try:
            predictions = creator.create_monthly_rolling_forecast(station, target_month_start)
            
            if predictions:
                # Calculate monthly statistics
                discharges = [p.predicted_discharge for p in predictions]
                avg_discharge = sum(discharges) / len(discharges)
                min_discharge = min(discharges)
                max_discharge = max(discharges)
                
                self.stdout.write(f'📈 Monthly Summary:')
                self.stdout.write(f'  Average: {avg_discharge:.2f} m³/s')
                self.stdout.write(f'  Range: {min_discharge:.2f} - {max_discharge:.2f} m³/s')
                self.stdout.write(f'  Total Predictions: {len(predictions)}')
                
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f'❌ Monthly forecast failed: {str(e)}')
            )
