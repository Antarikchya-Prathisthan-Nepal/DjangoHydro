"""
Management command to configure download areas for discharge stations
"""

from django.core.management.base import BaseCommand, CommandError
from discharge_prediction.models import DischargeStation
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Configure ERA5 download areas for discharge stations'

    def add_arguments(self, parser):
        parser.add_argument(
            '--station-name',
            type=str,
            help='Station name (partial match)'
        )
        
        parser.add_argument(
            '--station-id', 
            type=str,
            help='Exact station ID'
        )
        
        parser.add_argument(
            '--list-areas',
            action='store_true',
            help='List current area configurations for all stations'
        )
        
        parser.add_argument(
            '--set-area',
            action='store_true',
            help='Set custom area for station'
        )
        
        parser.add_argument(
            '--north',
            type=float,
            help='North boundary (decimal degrees)'
        )
        
        parser.add_argument(
            '--west', 
            type=float,
            help='West boundary (decimal degrees)'
        )
        
        parser.add_argument(
            '--south',
            type=float,
            help='South boundary (decimal degrees)'
        )
        
        parser.add_argument(
            '--east',
            type=float,
            help='East boundary (decimal degrees)'
        )
        
        parser.add_argument(
            '--auto-area',
            action='store_true',
            help='Enable automatic area generation for station'
        )

    def handle(self, *args, **options):
        if options['list_areas']:
            self.list_all_areas()
        elif options['set_area']:
            self.set_custom_area(options)
        elif options['auto_area']:
            self.enable_auto_area(options)
        else:
            self.stdout.write(
                self.style.WARNING(
                    'Please specify an action: --list-areas, --set-area, or --auto-area'
                )
            )

    def list_all_areas(self):
        """List area configurations for all stations"""
        self.stdout.write(self.style.SUCCESS('\\n📍 STATION AREA CONFIGURATIONS\\n'))
        self.stdout.write('=' * 80)
        
        stations = DischargeStation.objects.all().order_by('name')
        
        for station in stations:
            try:
                area_info = station.get_area_info()
                
                self.stdout.write(f'\\n🏢 {station.name} ({station.station_id})')
                self.stdout.write(f'   📍 Location: {station.location}')
                self.stdout.write(f'   🗺️  Area Type: {area_info["type"]}')
                self.stdout.write(f'   📦 Bounding Box:')
                self.stdout.write(f'      North: {area_info["north"]:.4f}°')
                self.stdout.write(f'      West:  {area_info["west"]:.4f}°') 
                self.stdout.write(f'      South: {area_info["south"]:.4f}°')
                self.stdout.write(f'      East:  {area_info["east"]:.4f}°')
                self.stdout.write(f'   📏 Size: {area_info["size_degrees"]["lat_span"]:.2f}° × {area_info["size_degrees"]["lon_span"]:.2f}°')
                
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'   ❌ Error getting area info: {e}')
                )
        
        self.stdout.write('\\n' + '=' * 80)

    def set_custom_area(self, options):
        """Set custom area for a station"""
        station = self.get_station(options)
        
        # Validate required parameters
        required_params = ['north', 'west', 'south', 'east']
        missing_params = [param for param in required_params if options[param] is None]
        
        if missing_params:
            raise CommandError(f"Missing required parameters: {', '.join(missing_params)}")
        
        # Validate area bounds
        north, west, south, east = options['north'], options['west'], options['south'], options['east']
        
        if north <= south:
            raise CommandError("North boundary must be greater than South boundary")
        if east <= west:
            raise CommandError("East boundary must be greater than West boundary")
        if not (-90 <= north <= 90) or not (-90 <= south <= 90):
            raise CommandError("Latitude boundaries must be between -90 and 90 degrees")
        if not (-180 <= west <= 180) or not (-180 <= east <= 180):
            raise CommandError("Longitude boundaries must be between -180 and 180 degrees")
        
        # Set custom area
        self.stdout.write(f'Setting custom area for {station.name}...')
        self.stdout.write(f'  North: {north}°')
        self.stdout.write(f'  West: {west}°')
        self.stdout.write(f'  South: {south}°')
        self.stdout.write(f'  East: {east}°')
        
        try:
            station.set_custom_area(north, west, south, east)
            
            # Verify the change
            area_info = station.get_area_info()
            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Custom area set successfully!\\n'
                    f'   Area size: {area_info["size_degrees"]["lat_span"]:.2f}° × {area_info["size_degrees"]["lon_span"]:.2f}°'
                )
            )
            
        except Exception as e:
            raise CommandError(f"Error setting custom area: {e}")

    def enable_auto_area(self, options):
        """Enable automatic area generation for a station"""
        station = self.get_station(options)
        
        self.stdout.write(f'Enabling automatic area generation for {station.name}...')
        
        try:
            station.use_auto_area = True
            station.save()
            
            # Show the auto-generated area
            area_info = station.get_area_info()
            self.stdout.write(
                self.style.SUCCESS(
                    f'✅ Automatic area enabled!\\n'
                    f'   Auto-generated area: {area_info["size_degrees"]["lat_span"]:.2f}° × {area_info["size_degrees"]["lon_span"]:.2f}°'
                )
            )
            
        except Exception as e:
            raise CommandError(f"Error enabling auto area: {e}")

    def get_station(self, options):
        """Get station from command options"""
        if options['station_id']:
            try:
                return DischargeStation.objects.get(station_id=options['station_id'])
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station with ID '{options['station_id']}' not found")
        
        elif options['station_name']:
            try:
                return DischargeStation.objects.get(name__icontains=options['station_name'])
            except DischargeStation.DoesNotExist:
                raise CommandError(f"Station with name '{options['station_name']}' not found")
            except DischargeStation.MultipleObjectsReturned:
                stations = DischargeStation.objects.filter(name__icontains=options['station_name'])
                self.stdout.write(self.style.WARNING('Multiple stations found:'))
                for station in stations:
                    self.stdout.write(f"  - {station.station_id}: {station.name}")
                raise CommandError("Multiple stations found. Use --station-id for specific selection")
        
        else:
            raise CommandError("Please specify either --station-id or --station-name")
