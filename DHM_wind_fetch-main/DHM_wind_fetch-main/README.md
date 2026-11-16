# DHM Wind Speed and Direction Daily Fetch

Fetches daily wind speed and wind direction data from DHM Nepal and writes combined station-wise data to Google Sheets. Both parameters are fetched together and stored in the same worksheet with columns for wind speed (min/max/avg) and wind direction (min/max/avg).

## Files

- `fetch_wind.py`: Main script that fetches and updates sheet data
- `wind_stations.py`: Station configuration entry point
- `all_wind_stations.py`: Full generated station mapping (speed and direction series IDs + worksheet)
- `.github/workflows/daily_fetch_wind.yml`: Scheduled GitHub Actions workflow

## Setup

1. Create a Google Sheet named `DHM_wind` (or set env var `DHM_WIND_SHEET`).
2. Share the sheet with your service account email.
3. Add your service account JSON as GitHub secret:
   - `GOOGLE_SERVICE_ACCOUNT_WIND`

## Data Collected

For each station, the script collects:
- **Wind Speed (m/s)**: Min, Max, Average (from 1-hour averages at 10m height)
- **Wind Direction (degrees)**: Min, Max, Average (from 1-hour averages at 10m height)

Both parameters are fetched from the same DHM surface observation API and stored together in a single worksheet per station.

## Manual Run

```bash
pip install pandas requests lxml gspread gspread_dataframe
python fetch_wind.py
```

## Schedule

Workflow runs daily at 10:00 AM NPT (04:15 UTC).
