# DHM Temperature Daily Fetch

Fetches daily temperature data from DHM Nepal and writes station-wise data to Google Sheets.

## Files

- `fetch_temperature.py`: Main script that fetches and updates sheet data
- `temperature_stations.py`: Station configuration (`seriesid` + worksheet name)
- `.github/workflows/daily_fetch_temperature.yml`: Scheduled GitHub Actions workflow

## Setup

1. Create a Google Sheet named `DHM_temperature` (or set a custom name with env var `DHM_TEMPERATURE_SHEET`).
2. Share that sheet with your service account email.
3. Add your service account JSON as GitHub secret:
   - `GOOGLE_SERVICE_ACCOUNT_TEMPERATURE`
4. Edit `temperature_stations.py` and replace each `REPLACE_WITH_DHM_SERIES_ID` with real DHM temperature series IDs.

## How Series IDs Work

You need DHM temperature series IDs for each station.
If DHM changes endpoints or requires CSRF, set optional secret/environment variable `DHM_CSRF_TOKEN`.

## Manual Run

```bash
pip install pandas requests lxml gspread gspread_dataframe
python fetch_temperature.py
```

## Schedule

Workflow runs daily at 10:00 AM NPT (04:15 UTC).
