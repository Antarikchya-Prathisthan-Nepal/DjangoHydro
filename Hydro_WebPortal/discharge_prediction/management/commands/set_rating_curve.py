"""
Management command: set_rating_curve

Sets the power-law rating curve parameters on a DischargeStation and then
recomputes the Q2 discharge for all existing DischargeRecord rows that have
a non-null stage_height.

Usage:
    # Set rating curve for station 1 (Likhu / Sangutar reference)
    python manage.py set_rating_curve \\
        --station 1 \\
        --c 62.59397 --a 1.85553 --b 1.83024 \\
        --ref-area 851

    # Set rating curve and recompute records
    python manage.py set_rating_curve --station 1 \\
        --c 62.59397 --a 1.85553 --b 1.83024 --ref-area 851 \\
        --recompute

    # Dry-run (show what Q2 values would be without writing)
    python manage.py set_rating_curve --station 1 \\
        --c 62.59397 --a 1.85553 --b 1.83024 --ref-area 851 \\
        --recompute --dry-run

    # Also update the station catchment area if it is wrong
    python manage.py set_rating_curve --station 1 \\
        --c 62.59397 --a 1.85553 --b 1.83024 --ref-area 851 \\
        --catchment-area 717.54 --recompute
"""

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from discharge_prediction.models import DHMStage, DischargeStation

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Configure rating-curve parameters on a DischargeStation and optionally recompute Q2 for all its records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--station",
            required=True,
            help="DischargeStation pk (integer) or exact name (string).",
        )
        parser.add_argument("--c",   type=float, required=True, dest="curve_c",
                            help="Rating curve coefficient c in Q = c*(H-a)^b")
        parser.add_argument("--a",   type=float, required=True, dest="curve_a",
                            help="Zero-flow stage offset a (metres) in Q = c*(H-a)^b")
        parser.add_argument("--b",   type=float, required=True, dest="curve_b",
                            help="Rating curve exponent b in Q = c*(H-a)^b")
        parser.add_argument("--ref-area", type=float, required=True, dest="ref_area",
                            help="Catchment area of the reference DHM gauging station A1 (km2)")
        parser.add_argument("--catchment-area", type=float, default=None, dest="catchment_area",
                            help="Override the station's own catchment area A2 (km2). "
                                 "Use when the stored value is incorrect.")
        parser.add_argument("--recompute", action="store_true", default=False,
                            help="Recompute discharge Q2 for all existing records that have stage_height.")
        parser.add_argument("--dry-run", action="store_true", default=False,
                            help="Print what would happen without writing to the database.")

    def handle(self, *args, **options):
        station_id = options["station"]
        dry_run    = options["dry_run"]

        # ── Resolve station ───────────────────────────────────────────────
        try:
            pk = int(station_id)
            station = DischargeStation.objects.get(pk=pk)
        except (ValueError, DischargeStation.DoesNotExist):
            # Try by name
            station = DischargeStation.objects.filter(name__iexact=station_id).first()
            if station is None:
                raise CommandError(f"Station '{station_id}' not found (tried pk and name).")

        self.stdout.write(f"Station: {station.name} (pk={station.pk})")
        self.stdout.write(f"  Current catchment_area      : {station.catchment_area} km2")
        self.stdout.write(f"  Current rating_curve_c      : {station.rating_curve_c}")
        self.stdout.write(f"  Current rating_curve_a      : {station.rating_curve_a}")
        self.stdout.write(f"  Current rating_curve_b      : {station.rating_curve_b}")
        self.stdout.write(f"  Current reference_catchment : {station.reference_catchment_area_km2} km2")

        # ── New parameter values ──────────────────────────────────────────
        new_c   = options["curve_c"]
        new_a   = options["curve_a"]
        new_b   = options["curve_b"]
        new_ref = options["ref_area"]
        new_catchment = options["catchment_area"]

        self.stdout.write("")
        self.stdout.write("New parameters:")
        self.stdout.write(f"  rating_curve_c             = {new_c}")
        self.stdout.write(f"  rating_curve_a             = {new_a} m")
        self.stdout.write(f"  rating_curve_b             = {new_b}")
        self.stdout.write(f"  reference_catchment_area   = {new_ref} km2")
        if new_catchment is not None:
            self.stdout.write(f"  catchment_area (override)  = {new_catchment} km2")

        if dry_run:
            self.stdout.write(self.style.WARNING("[dry-run] Station parameters NOT saved."))
        else:
            station.rating_curve_c = new_c
            station.rating_curve_a = new_a
            station.rating_curve_b = new_b
            station.reference_catchment_area_km2 = new_ref
            if new_catchment is not None:
                station.catchment_area = new_catchment
            station.save(update_fields=[
                'rating_curve_c', 'rating_curve_a', 'rating_curve_b',
                'reference_catchment_area_km2',
                *(['catchment_area'] if new_catchment is not None else []),
            ])
            self.stdout.write(self.style.SUCCESS("Station parameters saved."))

        if not options["recompute"]:
            self.stdout.write("\n(--recompute has no effect: discharge is computed on-the-fly from stage_height.)")
