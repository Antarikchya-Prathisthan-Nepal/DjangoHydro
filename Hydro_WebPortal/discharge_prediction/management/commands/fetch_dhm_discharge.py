"""
Management command: fetch_dhm_discharge
========================================
Scrapes daily discharge data (Max / Min / Average) from the DHM
(Department of Hydrology and Meteorology, Nepal) River Watch portal and
writes it directly into the DischargeRecord database table.

Usage
-----
    python manage.py fetch_dhm_discharge
    python manage.py fetch_dhm_discharge --station Likhu_Sangutar
    python manage.py fetch_dhm_discharge --date 2026-03-18

The command replaces the old GitHub Actions → Google Sheets pipeline.
No Google credentials are required.

Data flow
---------
    DHM portal (POST /getRiverWatchBySeriesId_Single)
        → HTML table in JSON response
        → pandas DataFrame (Date | Max | Min | Average)
        → DischargeRecord rows (data_source='dhm_scrape')

Matching a DHM series to a DischargeStation
-------------------------------------------
Each entry in DHM_STATIONS maps a human-readable name to:
  - seriesid  : DHM series identifier used in the POST payload
  - station_id: The station_id field on the DischargeStation model.
                Set this to the value stored in your database for that station.
                Use an empty string to skip matching (data will not be saved).

Only the *Average* discharge column is written as the primary discharge value;
Max and Min are stored in the notes field as JSON so they can be recovered later.
"""

import logging
import time
from datetime import date, datetime, timedelta
from io import StringIO

import requests
import pandas as pd

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from discharge_prediction.models import DischargeStation, DHMStage
from discharge_prediction.dhm_stations import DHM_STATIONS

logger = logging.getLogger(__name__)

DHM_URL = "https://dhm.gov.np/site/getRiverWatchBySeriesId_Single"
DHM_HEADERS = {"User-Agent": "Mozilla/5.0"}
# The CSRF token is embedded in the DHM site; this value has been stable for
# years but may change — if requests start failing, update this value.
DHM_CSRF = "f0486dc1567fe23edf08ccb55e7e51a4"


def fetch_dhm_series(seriesid: str, target_date: date | None = None) -> pd.DataFrame:
    """
    Fetch the 7-day daily discharge table for *seriesid* from the DHM portal.

    Returns a DataFrame with columns: Date (datetime), Max, Min, Average.
    Raises requests.HTTPError or ValueError on failure.
    """
    payload = {
        "date": str(target_date or date.today()),
        "period": "3",       # 3 = daily
        "seriesid": seriesid,
        "csrf_test_name": DHM_CSRF,
    }
    resp = requests.post(DHM_URL, data=payload, headers=DHM_HEADERS, timeout=30)
    resp.raise_for_status()

    body = resp.json()
    table_html = body.get("data", {}).get("table", "")
    if not table_html:
        raise ValueError(f"Empty table in DHM response for seriesid={seriesid}")

    df = pd.read_html(StringIO(table_html))[0]
    df["Date"] = pd.to_datetime(df["Date"], format="mixed", dayfirst=False)
    return df


class Command(BaseCommand):
    help = (
        "Fetch daily discharge data from the DHM River Watch portal and "
        "store it directly in the DischargeRecord table."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--station",
            dest="station",
            default=None,
            help="Restrict to a single station name (key in DHM_STATIONS). "
                 "Omit to process all stations.",
        )
        parser.add_argument(
            "--date",
            dest="target_date",
            default=None,
            help="Reference date for the 7-day window (YYYY-MM-DD). "
                 "Defaults to today.",
        )
        parser.add_argument(
            "--from-date",
            dest="from_date",
            default=None,
            help="Backfill start date (YYYY-MM-DD). Iterates 7-day windows from "
                 "this date up to today (or --date if also specified). "
                 "Ignored when --date is given without --from-date.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Fetch and parse data without writing to the database.",
        )

    def handle(self, *args, **options):
        dry_run: bool = options["dry_run"]
        target_date: date | None = None
        from_date: date | None = None

        if options["target_date"]:
            try:
                target_date = datetime.strptime(options["target_date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--date must be in YYYY-MM-DD format")

        if options["from_date"]:
            try:
                from_date = datetime.strptime(options["from_date"], "%Y-%m-%d").date()
            except ValueError:
                raise CommandError("--from-date must be in YYYY-MM-DD format")

        # Build the list of reference dates to query.
        # DHM returns ~7 rows per request centred on the reference date.
        # When backfilling, step every 7 days from from_date up to end_date.
        if from_date:
            end_date = target_date or date.today()
            if from_date > end_date:
                raise CommandError("--from-date must be earlier than --date / today")
            date_windows: list[date] = []
            cursor = from_date
            while cursor <= end_date:
                date_windows.append(cursor)
                cursor += timedelta(days=7)
            # Always include the end date so the most recent window is covered
            if date_windows[-1] != end_date:
                date_windows.append(end_date)
            self.stdout.write(
                f"Backfill mode: {from_date} -> {end_date} ({len(date_windows)} windows)"
            )
        else:
            # Normal single-window mode
            date_windows = [target_date]  # target_date may be None (= today)

        # Filter to one station if requested
        stations_to_process = DHM_STATIONS
        if options["station"]:
            key = options["station"]
            if key not in DHM_STATIONS:
                raise CommandError(
                    f"Station '{key}' not found in DHM_STATIONS. "
                    f"Available: {', '.join(DHM_STATIONS.keys())}"
                )
            stations_to_process = {key: DHM_STATIONS[key]}

        total_saved = 0
        total_skipped = 0
        total_errors = 0

        for station_name, cfg in stations_to_process.items():
            seriesid = cfg["seriesid"]
            station_id = cfg.get("station_id", "")

            self.stdout.write(f">> Fetching {station_name} (seriesid={seriesid})")

            # ── Resolve DischargeStation up-front (skip entire station fast) ──
            station_obj = None
            if station_id:
                try:
                    station_obj = DischargeStation.objects.get(station_id=station_id)
                except DischargeStation.DoesNotExist:
                    self.stderr.write(
                        self.style.ERROR(
                            f"  [ERROR] DischargeStation with station_id='{station_id}' not found "
                            f"for {station_name} — skipping"
                        )
                    )
                    total_skipped += 1
                    continue

            # ── Iterate over each date window ─────────────────────────────
            station_saved = 0
            for window_idx, win_date in enumerate(date_windows):
                # Polite delay between requests when backfilling
                if window_idx > 0:
                    time.sleep(1)

                try:
                    df = fetch_dhm_series(seriesid, win_date)
                except Exception as exc:
                    self.stderr.write(self.style.ERROR(f"  [ERROR] Fetch error ({win_date}): {exc}"  ))
                    logger.error("DHM fetch failed for %s on %s: %s", station_name, win_date, exc)
                    total_errors += 1
                    continue

                if df.empty:
                    logger.debug("Empty data for %s window %s", station_name, win_date)
                    continue

                if len(date_windows) > 1:
                    self.stdout.write(f"  [window {win_date}] {len(df)} rows")

                # ── No station_id — dry-run print or skip ─────────────────
                if not station_obj:
                    if dry_run:
                        if window_idx == 0:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  [WARN] No station_id configured for {station_name} "
                                    f"(dry-run - showing rows anyway)"
                                )
                            )
                        for _, row in df.iterrows():
                            row_date = row["Date"].date()
                            avg = _safe_float(row.get("Average"))
                            mx  = _safe_float(row.get("Max"))
                            mn  = _safe_float(row.get("Min"))
                            self.stdout.write(
                                f"  [dry-run] {row_date}: avg={avg} max={mx} min={mn} m3/s"
                            )
                    else:
                        if window_idx == 0:
                            self.stdout.write(
                                self.style.WARNING(
                                    f"  [WARN] No station_id configured for {station_name} - skipping DB write"
                                )
                            )
                    total_skipped += 1
                    break  # no point looping windows if station not linked

                # ── Write rows for this window ────────────────────────────
                for _, row in df.iterrows():
                    row_date: date = row["Date"].date()
                    avg_discharge = _safe_float(row.get("Average"))

                    if avg_discharge is None:
                        logger.debug(
                            "No average discharge for %s on %s — skipping row",
                            station_name, row_date,
                        )
                        continue

                    # Timestamp: midnight UTC on the measurement date
                    ts = timezone.make_aware(
                        datetime.combine(row_date, datetime.min.time()),
                    )

                    discharge_max = _safe_float(row.get("Max"))
                    discharge_min = _safe_float(row.get("Min"))

                    if dry_run:
                        self.stdout.write(
                            f"  [dry-run] {row_date}: H_avg={avg_discharge:.3f} m"
                            f" H_max={discharge_max} H_min={discharge_min}"
                        )
                        station_saved += 1
                        continue

                    try:
                        with transaction.atomic():
                            _, created = DHMStage.objects.update_or_create(
                                station=station_obj,
                                timestamp=ts,
                                defaults={
                                    "stage_height":     avg_discharge,
                                    "stage_height_max": discharge_max,
                                    "stage_height_min": discharge_min,
                                    "quality_flag":     "good",
                                    "data_source":      "dhm_scrape",
                                },
                            )
                            station_saved += 1
                            action = "created" if created else "updated"
                            logger.debug("%s: %s record for %s", action, station_name, row_date)

                    except Exception as exc:
                        self.stderr.write(self.style.ERROR(f"  [ERROR] DB error on {row_date}: {exc}"))
                        logger.error("DB write failed for %s %s: %s", station_name, row_date, exc)

            total_saved += station_saved
            self.stdout.write(
                self.style.SUCCESS(
                    f"  [OK] {station_name}: {station_saved} rows {'(dry-run)' if dry_run else 'saved'}"
                )
            )

        # ── Summary ───────────────────────────────────────────────────────
        self.stdout.write("─" * 50)
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Saved={total_saved}, Skipped={total_skipped}, Errors={total_errors}"
            )
        )


def _safe_float(value) -> float | None:
    """Return float or None; silently ignore non-numeric / NaN values."""
    try:
        f = float(value)
        import math
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None
