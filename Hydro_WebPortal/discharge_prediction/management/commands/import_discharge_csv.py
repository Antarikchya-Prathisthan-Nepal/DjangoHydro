"""
Management command: import_discharge_csv
=========================================
Import historical discharge records from a CSV file into the DischargeRecord
table.  The CSV can be a direct export from Google Sheets or any spreadsheet.

Usage
-----
    python manage.py import_discharge_csv --station 1 --file path/to/data.csv
    python manage.py import_discharge_csv --station 1 --file data.csv --dry-run
    python manage.py import_discharge_csv --station 1 --file data.csv --source manual_entry

CSV format
----------
The file must have a header row.  Column names are flexible — the command
auto-detects common variations, or you can specify them explicitly:

    date (or Date, timestamp, Timestamp, ...)
    discharge (or avg, average, Average, ...)
    discharge_max (or max, Max, maximum, ...)
    discharge_min (or min, Min, minimum, ...)

Minimum required column: date + discharge (average).
Max and Min are optional — left NULL if not present.

Example CSV
-----------
    date,discharge,discharge_max,discharge_min
    2025-08-01,45.2,52.1,38.7
    2025-08-02,43.8,50.0,37.2
    ...

Date formats accepted: YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY, MM/DD/YYYY
"""

import csv
import math
import logging
from datetime import datetime, date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from discharge_prediction.models import DischargeStation, DHMStage

logger = logging.getLogger(__name__)

# ── Column name aliases ──────────────────────────────────────────────────────
DATE_ALIASES    = {'date', 'timestamp', 'time', 'day', 'Date', 'Timestamp',
                   'TIME', 'DAY', 'DATE'}
AVG_ALIASES     = {'discharge', 'avg', 'average', 'discharge_avg',
                   'Discharge', 'Average', 'AVG', 'AVERAGE', 'Q', 'q',
                   'mean', 'Mean', 'MEAN', 'Q_avg'}
MAX_ALIASES     = {'discharge_max', 'max', 'maximum', 'Max', 'Maximum',
                   'MAX', 'MAXIMUM', 'Q_max', 'Qmax'}
MIN_ALIASES     = {'discharge_min', 'min', 'minimum', 'Min', 'Minimum',
                   'MIN', 'MINIMUM', 'Q_min', 'Qmin'}

DATE_FORMATS    = ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%m/%d/%Y',
                   '%Y/%m/%d', '%d.%m.%Y', '%Y-%m-%dT%H:%M:%S',
                   '%Y-%m-%d %H:%M:%S']


def _find_col(headers: list[str], aliases: set[str]) -> str | None:
    """Return the first header that matches any alias (case-sensitive first,
    then case-insensitive fallback)."""
    for h in headers:
        if h in aliases:
            return h
    for h in headers:
        if h.lower() in {a.lower() for a in aliases}:
            return h
    return None


def _parse_date(value: str) -> date | None:
    value = value.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _safe_float(value) -> float | None:
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ('-', 'N/A', 'n/a', 'null', 'NULL', 'None', 'NA'):
        return None
    try:
        f = float(s)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


class Command(BaseCommand):
    help = (
        "Import historical discharge records from a CSV file "
        "(e.g. exported from Google Sheets) into the DischargeRecord table."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--station',
            required=True,
            help="DischargeStation.station_id value (e.g. 1, 2) or the "
                 "station name as stored in the database.",
        )
        parser.add_argument(
            '--file',
            required=True,
            help="Path to the CSV file to import.",
        )
        parser.add_argument(
            '--source',
            default='manual_entry',
            help="Value for the data_source field (default: manual_entry). "
                 "Use e.g. 'google_sheets' or 'dhm_manual' if preferred.",
        )
        parser.add_argument(
            '--date-col',
            default=None,
            help="Override the auto-detected date column name.",
        )
        parser.add_argument(
            '--discharge-col',
            default=None,
            help="Override the auto-detected average discharge column name.",
        )
        parser.add_argument(
            '--max-col',
            default=None,
            help="Override the auto-detected max discharge column name.",
        )
        parser.add_argument(
            '--min-col',
            default=None,
            help="Override the auto-detected min discharge column name.",
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            default=False,
            help="Parse and validate the CSV without writing anything to the DB.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options['dry_run']
        csv_path = Path(options['file'])

        if not csv_path.exists():
            raise CommandError(f"File not found: {csv_path}")

        # ── Resolve station ───────────────────────────────────────────────
        station_key = options['station']
        station = (
            DischargeStation.objects.filter(station_id=station_key).first()
            or DischargeStation.objects.filter(name__iexact=station_key).first()
        )
        if not station:
            raise CommandError(
                f"No DischargeStation found with station_id or name '{station_key}'. "
                f"Available: "
                + ', '.join(
                    f"{s.station_id} ({s.name})"
                    for s in DischargeStation.objects.all()
                )
            )

        self.stdout.write(f"Station : {station.name} (id={station.station_id})")
        self.stdout.write(f"File    : {csv_path}")
        self.stdout.write(f"Source  : {options['source']}")
        if dry_run:
            self.stdout.write(self.style.WARNING("Mode    : DRY-RUN (no DB writes)"))
        self.stdout.write("-" * 50)

        # ── Read CSV ──────────────────────────────────────────────────────
        with csv_path.open(newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames or []
            if not headers:
                raise CommandError("CSV file has no header row.")

            self.stdout.write(f"Columns detected: {', '.join(headers)}")

            # Resolve column names
            date_col     = options['date_col']     or _find_col(headers, DATE_ALIASES)
            avg_col      = options['discharge_col'] or _find_col(headers, AVG_ALIASES)
            max_col      = options['max_col']      or _find_col(headers, MAX_ALIASES)
            min_col      = options['min_col']      or _find_col(headers, MIN_ALIASES)

            if not date_col:
                raise CommandError(
                    "Cannot find a date column. Detected headers: "
                    + ', '.join(headers)
                    + ". Use --date-col to specify it."
                )
            if not avg_col:
                raise CommandError(
                    "Cannot find a discharge (average) column. Detected headers: "
                    + ', '.join(headers)
                    + ". Use --discharge-col to specify it."
                )

            self.stdout.write(f"  date col     : {date_col}")
            self.stdout.write(f"  discharge col: {avg_col}")
            self.stdout.write(f"  max col      : {max_col or '(not found - will be NULL)'}")
            self.stdout.write(f"  min col      : {min_col or '(not found - will be NULL)'}")
            self.stdout.write("-" * 50)

            rows = list(reader)

        # ── Process rows ──────────────────────────────────────────────────
        saved = 0
        skipped = 0
        errors = 0

        for i, row in enumerate(rows, start=2):  # row 1 = header
            raw_date = row.get(date_col, '').strip()
            if not raw_date:
                self.stdout.write(self.style.WARNING(f"  Row {i}: empty date — skipped"))
                skipped += 1
                continue

            row_date = _parse_date(raw_date)
            if row_date is None:
                self.stdout.write(
                    self.style.ERROR(f"  Row {i}: cannot parse date '{raw_date}' — skipped")
                )
                errors += 1
                continue

            avg_discharge = _safe_float(row.get(avg_col))
            if avg_discharge is None:
                self.stdout.write(
                    self.style.WARNING(f"  Row {i} ({row_date}): no discharge value — skipped")
                )
                skipped += 1
                continue

            discharge_max = _safe_float(row.get(max_col)) if max_col else None
            discharge_min = _safe_float(row.get(min_col)) if min_col else None

            if dry_run:
                self.stdout.write(
                    f"  [dry-run] {row_date}: H_avg={avg_discharge:.3f} m"
                    f" H_max={discharge_max} H_min={discharge_min}"
                )
                saved += 1
                continue

            # Timestamp: midnight UTC on the measurement date
            ts = timezone.make_aware(
                datetime.combine(row_date, datetime.min.time())
            )

            try:
                with transaction.atomic():
                    _, created = DHMStage.objects.update_or_create(
                        station=station,
                        timestamp=ts,
                        defaults={
                            'stage_height':     avg_discharge,
                            'stage_height_max': discharge_max,
                            'stage_height_min': discharge_min,
                            'quality_flag':     'good',
                            'data_source':      options['source'],
                        },
                    )
                    saved += 1
                    action = 'created' if created else 'updated'
                    logger.debug("%s record for %s on %s", action, station.name, row_date)

            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"  Row {i} ({row_date}): DB error — {exc}"))
                logger.error("DB write failed for %s on %s: %s", station.name, row_date, exc)
                errors += 1

        # ── Summary ───────────────────────────────────────────────────────
        self.stdout.write("=" * 50)
        label = "(dry-run)" if dry_run else "saved"
        self.stdout.write(
            self.style.SUCCESS(
                f"Done.  {saved} rows {label},  {skipped} skipped,  {errors} errors."
            )
        )
        if dry_run:
            self.stdout.write(
                "Re-run without --dry-run to write to the database."
            )
