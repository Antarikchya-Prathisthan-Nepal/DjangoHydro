# DHM Rainfall Daily Fetch

Fetches daily rainfall data from the Department of Hydrology and Meteorology (DHM) Nepal and stores it in Google Sheets.

## Setup

1. Create a Google Cloud service account and download the JSON key file.
2. Create a Google Sheet named `DHM_rainfall` and share it with the service account email.
3. Add the service account JSON as a GitHub secret named `GOOGLE_SERVICE_ACCOUNT`.

## Station Configuration

Edit `rainfall_stations.py` to add/remove rainfall stations. Each station needs:
- `seriesid`: The DHM series ID for the rainfall data
- `worksheet`: The worksheet name in the Google Sheet

All 299 available DHM rainfall stations are included by default. Remove the ones you don't need.

## Manual Run

You can trigger the workflow manually from the GitHub Actions tab using "workflow_dispatch".

## Schedule

Runs daily at 10:00 AM NPT (4:15 AM UTC) via GitHub Actions cron.
