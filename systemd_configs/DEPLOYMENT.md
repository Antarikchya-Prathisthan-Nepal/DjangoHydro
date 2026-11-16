# VPS Deployment — Daily Scheduler (systemd)

## What this runs

`daily_master_scheduler.py` is a **long-running Python process** that uses the
`schedule` library to fire three jobs once per day (at 12:16 NPT by default):

1. ERA5 climate data download
2. Discharge prediction pipeline
3. DHM discharge station fetch (newly added)

---

## Files

| File | Purpose |
|---|---|
| `systemd_configs/djangohydro-scheduler.service` | systemd unit — starts and keeps the scheduler alive |

A `.timer` file is **not needed** — the scheduler manages its own internal clock.

---

## One-time setup on the VPS

```bash
# 1. Create the log directory
sudo mkdir -p /var/log/djangohydro
sudo chown www-data:www-data /var/log/djangohydro

# 2. Copy the service file
sudo cp /srv/DjangoHydro/systemd_configs/djangohydro-scheduler.service \
        /etc/systemd/system/djangohydro-scheduler.service

# 3. Edit paths / user inside the file if needed
#    nano /etc/systemd/system/djangohydro-scheduler.service

# 4. Reload systemd, enable, and start
sudo systemctl daemon-reload
sudo systemctl enable djangohydro-scheduler
sudo systemctl start  djangohydro-scheduler

# 5. Verify
sudo systemctl status djangohydro-scheduler
```

---

## Day-to-day commands

```bash
# Live logs
sudo journalctl -u djangohydro-scheduler -f

# Tail the file-based log
tail -f /var/log/djangohydro/daily_pipeline.log

# Restart after a code update
sudo systemctl restart djangohydro-scheduler

# Stop
sudo systemctl stop djangohydro-scheduler
```

---

## Adjusting the daily run time

Open `Hydro_WebPortal/daily_master_scheduler.py` and change the
`schedule.every().day.at(...)` line:

```python
# e.g. 06:00 NPT  →  00:15 UTC  →  "00:15" in NPT offset terms
schedule.every().day.at("06:00").do(run_daily_pipeline)
```

Then `sudo systemctl restart djangohydro-scheduler`.

---

## Checking what paths to use

If your VPS uses a different deploy path than `/srv/DjangoHydro`, update these
two lines in the `.service` file:

```ini
WorkingDirectory=/srv/DjangoHydro/Hydro_WebPortal
ExecStart=/srv/DjangoHydro/myenv/bin/python daily_master_scheduler.py
```

Run `which python` inside the activated virtual environment to confirm the
`python` path.

---

## Environment secrets

Add secrets directly in the `.service` file (it is owned by root, not
world-readable):

```ini
Environment=DHM_WEBHOOK_TOKEN=your-real-token-here
Environment=DATABASE_URL=...
```

Or put them in a drop-in file:

```bash
sudo systemctl edit djangohydro-scheduler
```

```ini
[Service]
Environment=DHM_WEBHOOK_TOKEN=your-real-token-here
```
