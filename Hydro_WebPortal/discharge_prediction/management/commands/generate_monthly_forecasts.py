"""
Django management command to generate monthly forecasts

Usage:
    python manage.py generate_monthly_forecasts
    python manage.py generate_monthly_forecasts --station "Lower likhu"
    python manage.py generate_monthly_forecasts --year 2025 --month 11
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from discharge_prediction.models import DischargeStation, MonthlyForecast
from datetime import date
from calendar import monthrange

class Command(BaseCommand):
    help = 'Generate monthly energy forecasts for all stations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--station',
            type=str,
            help='Station name to process (optional, processes all if not specified)',
        )
        parser.add_argument(
            '--year',
            type=int,
            help='Year to process (optional, processes all available if not specified)',
        )
        parser.add_argument(
            '--month',
            type=int,
            help='Month to process (1-12, optional, processes all available if not specified)',
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force regeneration even if forecast already exists',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('🌊 DJANGO MONTHLY FORECAST GENERATOR'))
        self.stdout.write('=' * 60)
        
        # Get stations to process
        if options['station']:
            try:
                stations = [DischargeStation.objects.get(name__icontains=options['station'])]
                self.stdout.write(f"📍 Processing specific station: {stations[0].name}")
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station '{options['station']}' not found")
        else:
            stations = DischargeStation.objects.filter(is_active=True)
            self.stdout.write(f"🏭 Processing all {stations.count()} active stations")

        # Get months to process
        if options['year'] and options['month']:
            # Process specific month
            target_months = [(options['year'], options['month'])]
            self.stdout.write(f"📅 Processing specific month: {options['year']}-{options['month']:02d}")
        else:
            # Process all available months
            target_months = self.get_available_months()
            self.stdout.write(f"📅 Processing {len(target_months)} available months")

        # Statistics
        total_processed = 0
        total_successful = 0
        total_skipped = 0

        # Process each station and month combination
        for station in stations:
            self.stdout.write(f"\n🏭 STATION: {station.name}")
            self.stdout.write('-' * 50)
            
            for year, month in target_months:
                try:
                    result = self.process_monthly_forecast(
                        station, year, month, 
                        force=options['force']
                    )
                    
                    total_processed += 1
                    if result['success']:
                        total_successful += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"  ✅ {year}-{month:02d}: {result['message']}"
                            )
                        )
                    else:
                        total_skipped += 1
                        self.stdout.write(
                            self.style.WARNING(
                                f"  ⚠️  {year}-{month:02d}: {result['message']}"
                            )
                        )
                        
                except Exception as e:
                    total_processed += 1
                    total_skipped += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"  ❌ {year}-{month:02d}: Error - {str(e)}"
                        )
                    )

        # Final summary
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS('📊 FINAL SUMMARY'))
        self.stdout.write('=' * 60)
        self.stdout.write(f"🏭 Stations: {len(stations)}")
        self.stdout.write(f"📅 Months processed: {total_processed}")
        self.stdout.write(f"✅ Successful: {total_successful}")
        self.stdout.write(f"⚠️  Skipped: {total_skipped}")
        self.stdout.write(f"⏰ Completed at: {timezone.now().strftime('%Y-%m-%d %H:%M:%S')}")

    def get_available_months(self):
        """Get all available year-month combinations from daily predictions"""
        from discharge_prediction.models import DischargePrediction
        from django.db.models import Min, Max
        
        # Get date range of predictions
        date_stats = DischargePrediction.objects.aggregate(
            min_date=Min('target_date'),
            max_date=Max('target_date')
        )
        
        if not date_stats['min_date']:
            return []
        
        # Generate month list
        months = []
        current_date = date_stats['min_date'].replace(day=1)
        end_date = date_stats['max_date']
        
        while current_date <= end_date:
            months.append((current_date.year, current_date.month))
            
            # Move to next month
            if current_date.month == 12:
                current_date = current_date.replace(year=current_date.year + 1, month=1)
            else:
                current_date = current_date.replace(month=current_date.month + 1)
        
        return months

    def process_monthly_forecast(self, station, year, month, force=False):
        """Process monthly forecast for a specific station and month"""
        from discharge_prediction.models import DischargePrediction
        
        # Check if forecast already exists
        existing_forecast = MonthlyForecast.objects.filter(
            station=station,
            target_year=year,
            target_month=month
        ).first()
        
        if existing_forecast and not force:
            if existing_forecast.processing_status == 'completed':
                energy = existing_forecast.total_energy_mwh or 0
                return {
                    'success': True,
                    'message': f'Already exists - {energy:.2f} MWh'
                }
        
        # Check data completeness
        days_in_month = monthrange(year, month)[1]
        first_day = date(year, month, 1)
        last_day = date(year, month, days_in_month)
        
        predictions_count = DischargePrediction.objects.filter(
            station=station,
            target_date__range=[first_day, last_day]
        ).count()
        
        if predictions_count != days_in_month:
            return {
                'success': False,
                'message': f'Incomplete data: {predictions_count}/{days_in_month} days'
            }
        
        # Create or update forecast
        forecast, created = MonthlyForecast.objects.get_or_create(
            station=station,
            target_year=year,
            target_month=month,
            defaults={'processing_status': 'pending'}
        )
        
        # Run aggregation
        forecast.aggregate_daily_predictions()
        
        # Return result
        energy = forecast.total_energy_mwh or 0
        discharge = forecast.mean_discharge or 0
        action = "Created" if created else "Updated"
        
        return {
            'success': True,
            'message': f'{action} - {discharge:.2f} m³/s → {energy:.2f} MWh'
        }