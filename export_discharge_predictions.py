import csv
import re
from pathlib import Path

SQL_FILE = r"C:\Users\Dell\AppData\Local\Temp\066ed3b8-5668-48aa-9d22-b9f0268787ef_hydroV1.sql.zip.7ef\hydroV1.sql"
OUTPUT_DIR = Path(r"C:\Users\Dell\antar\DjangoHydro")

STATION_MAP = {
    "559a6e3b-7cae-40a4-aabe-7d0084d612cf": "Pilot_1",
    "c51d114b-3b79-4f0d-87ff-bfe2f8720b79": "Pilot_2",
}

COLUMNS = [
    "id", "target_date", "predicted_discharge", "prediction_confidence",
    "confidence_lower", "confidence_upper", "model_name", "sequence_length",
    "forecast_type", "processing_status", "actual_discharge", "accuracy_score",
    "created_at", "updated_at", "station_id", "predicted_energy"
]

def parse_copy_block(sql_text, table_name):
    """Extract rows from a PostgreSQL COPY ... FROM stdin block."""
    pattern = rf"COPY public\.{re.escape(table_name)} \([^)]+\) FROM stdin;\n(.*?)\\\."
    match = re.search(pattern, sql_text, re.DOTALL)
    if not match:
        return []
    raw = match.group(1).strip()
    if not raw:
        return []
    rows = []
    for line in raw.splitlines():
        if line.strip():
            fields = line.split("\t")
            rows.append(fields)
    return rows

def main():
    print(f"Reading SQL file...")
    sql_text = Path(SQL_FILE).read_text(encoding="utf-8", errors="replace")

    print("Parsing discharge_prediction_dischargeprediction table...")
    rows = parse_copy_block(sql_text, "discharge_prediction_dischargeprediction")
    print(f"  Total rows found: {len(rows)}")

    # Split by station
    station_rows = {sid: [] for sid in STATION_MAP}
    skipped = 0
    for row in rows:
        if len(row) != len(COLUMNS):
            skipped += 1
            continue
        record = dict(zip(COLUMNS, row))
        sid = record.get("station_id")
        if sid in station_rows:
            station_rows[sid].append(record)

    if skipped:
        print(f"  Warning: skipped {skipped} malformed rows")

    # Export per station
    for sid, station_name in STATION_MAP.items():
        data = station_rows[sid]
        if not data:
            print(f"  No data found for {station_name}")
            continue

        dates = [r["target_date"] for r in data]
        dates_sorted = sorted(dates)
        print(f"\n  {station_name} ({sid}):")
        print(f"    Records  : {len(data)}")
        print(f"    Date range: {dates_sorted[0]}  →  {dates_sorted[-1]}")

        out_path = OUTPUT_DIR / f"discharge_predictions_{station_name}.csv"
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()
            # Sort by date before writing
            for record in sorted(data, key=lambda r: r["target_date"]):
                # Replace PostgreSQL NULL (\N) with empty string
                clean = {k: ("" if v == r"\N" else v) for k, v in record.items()}
                writer.writerow(clean)
        print(f"    Exported : {out_path}")

    # Combined export
    all_data = []
    for sid, data in station_rows.items():
        for record in data:
            record["station_name"] = STATION_MAP[sid]
            all_data.append(record)

    combined_cols = ["station_name"] + COLUMNS
    out_combined = OUTPUT_DIR / "discharge_predictions_ALL.csv"
    with open(out_combined, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=combined_cols)
        writer.writeheader()
        for record in sorted(all_data, key=lambda r: (r["station_name"], r["target_date"])):
            clean = {k: ("" if v == r"\N" else v) for k, v in record.items()}
            writer.writerow(clean)
    print(f"\n  Combined export: {out_combined}")
    print(f"  Total combined rows: {len(all_data)}")

if __name__ == "__main__":
    main()
