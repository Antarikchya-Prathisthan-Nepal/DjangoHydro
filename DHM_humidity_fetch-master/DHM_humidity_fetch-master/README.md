# DHM Humidity Daily Fetch

Fetches relative humidity data from DHM Nepal and writes station-wise daily
min/max/average values to Google Sheets.

## Files

- `fetch_humidity.py`: Main script that fetches and updates sheet data
- `humidity_stations.py`: Station configuration entry point
- `all_humidity_stations.py`: Full generated station mapping (`seriesid` + worksheet)
- `dhm_humidity_station_ids.csv`: Reference list of stations and RH series IDs
- `.github/workflows/daily_fetch_humidity.yml`: Scheduled GitHub Actions workflow

## Setup

1. Create a Google Sheet named `DHM_humidity` (or set env var `DHM_HUMIDITY_SHEET`).
2. Share the sheet with your service account email.
3. Add your service account JSON as GitHub secret:
   - `GOOGLE_SERVICE_ACCOUNT_HUMIDITY`

## Manual Run

```bash
pip install pandas requests lxml gspread gspread_dataframe
python fetch_humidity.py
```

## Schedule

Workflow runs daily at 10:00 AM NPT (04:15 UTC).
