# Operations Runbook

This runbook explains how to interpret automated alerts emitted by the `alert_watcher`
service, along with the operator actions required to stabilise the stack. The watcher
parses the structured access logs written by Nginx and posts notifications to Slack
via `SLACK_WEBHOOK_URL`.

## Alert Types

### Failover Detected
- **Trigger**: The watcher observes successful requests being served by a different
  pool than the last healthy response (e.g. `blue → green`).
- **Read the alert**: The message contains the previous pool, the new pool, and the
  release ID now serving traffic.
- **Operator action**:
  1. Inspect the primary application logs: `docker compose logs app_blue` or `app_green`
     depending on which pool lost traffic.
  2. Check container health (`docker compose ps --status=running`) and resolve the
     underlying app issue (crash, dependency failure, resource exhaustion).
  3. Once the primary is healthy again, allow traffic to return naturally or update
     `ACTIVE_POOL` and redeploy if a manual switch is required.

### Recovery
- **Trigger**: After a failover, the watcher sees successful responses served by the
  configured primary pool again.
- **Read the alert**: Confirms the primary pool identifier and release now serving
  traffic.
- **Operator action**: Verify that request success rates remain high and that no chaos
  or maintenance tooling continues to run against the standby pool.

### High Error Rate
- **Trigger**: More than 2% of upstream responses returned 5xx status codes across the
  last 200 requests (configurable via `ALERT_ERROR_THRESHOLD` and
  `ALERT_ERROR_WINDOW`).
- **Read the alert**: Provides the rolling error percentage.
- **Operator action**:
  1. Inspect upstream logs for stack traces or timeout errors.
  2. Confirm container health and resource usage (`docker stats`, host metrics).
  3. Consider toggling pools (`ACTIVE_POOL`) if one release is degraded while the
     standby remains healthy.
  4. After mitigation, continue monitoring until alerts clear.

## Maintenance Mode

Use maintenance mode to silence Slack alerts during planned failovers or load tests
while keeping log ingestion active.

1. Ensure `MAINTENANCE_FLAG_FILE` is set (default `/var/run/maintenance.on`).
2. Enable suppression:
   ```bash
   docker compose exec alert_watcher sh -c "touch /var/run/maintenance.on"
   ```
3. Perform the planned operation.
4. Disable suppression and resume alerts:
   ```bash
   docker compose exec alert_watcher sh -c "rm -f /var/run/maintenance.on"
   ```

The watcher polls for the flag file before sending any Slack notification. Alerts
resume automatically once the file is removed.

## Accessing Logs

Structured access logs live in the `nginx_logs` named volume mounted at
`/var/log/nginx/app_access.log`. They contain JSON entries with pool, release, request
timings, and upstream metadata. To inspect them manually:

```bash
docker compose exec nginx tail -f /var/log/nginx/app_access.log
```

This same path is mounted read-only by the watcher for streaming analysis.
