# Alert Watcher

Tails the Nginx JSON access log and sends Slack alerts when upstream error rates spike or traffic fails over between pools. It is packaged as a small Python service and is meant to run alongside the Nginx container in this repo.

## What it watches
- `status`, `upstream_status`: used to detect 5xx errors.
- `pool`, `release`: used to detect pool changes (failover/recovery) and include release metadata in alerts.

These fields come from the `app_json` log format defined in `nginx/nginx.conf.template`.

## Alerts
- `error_rate`: triggers when the 5xx rate across the sliding window exceeds the threshold.
- `failover`: triggers when traffic moves from the previously observed pool to a new pool.
- `recovery`: triggers when traffic returns to the configured primary pool.

Each alert type is subject to its own cooldown timer to avoid spam.

## Configuration (env vars)
- `SLACK_WEBHOOK_URL` (required): Slack incoming webhook URL.
- `LOG_PATH` (default: `/var/log/nginx/app_access.log`): path to the Nginx access log.
- `ALERT_ERROR_WINDOW` (default: `200`): number of recent requests in the error-rate window.
- `ALERT_ERROR_THRESHOLD` (default: `0.02`): fraction of 5xx responses that triggers an alert.
- `ALERT_COOLDOWN_SECONDS` (default: `300`): minimum seconds between same-type alerts.
- `PRIMARY_POOL` (optional): expected primary pool name (`blue` or `green`).
- `MAINTENANCE_FLAG_FILE` (optional): if this file exists, alerts are suppressed.

## Running
The top-level `docker-compose.yml` already builds and runs this container as `alert_watcher`. It mounts the Nginx log volume read-only and uses the environment variables above.

For local execution outside Docker:
```bash
python app.py
```

## Dependencies
See `alert-watcher/requirements.txt` (uses `requests` for Slack webhooks).
