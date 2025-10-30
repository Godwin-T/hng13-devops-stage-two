import collections
import json
import os
import sys
import time
from typing import Deque, Optional

import requests


def log(message: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    print(f"[alert-watcher] {ts} {message}", file=sys.stderr, flush=True)


class AlertWatcher:
    def __init__(
        self,
        webhook_url: str,
        log_path: str = "/var/log/nginx/app_access.log",
        window_size: int = 200,
        error_threshold: float = 0.02,
        cooldown_seconds: int = 300,
        primary_pool: Optional[str] = None,
        maintenance_flag: Optional[str] = None,
    ) -> None:
        self.webhook_url = webhook_url
        self.log_path = log_path
        self.window: Deque[int] = collections.deque(maxlen=window_size)
        self.error_threshold = error_threshold
        self.cooldown_seconds = cooldown_seconds
        self.primary_pool = (primary_pool or "").strip().lower()
        self.maintenance_flag = (maintenance_flag or "").strip()
        self.current_pool: Optional[str] = None
        self.cooldowns: dict[str, float] = {}
        self.error_alert_active = False

    def process_line(self, line: str) -> None:
        entry = self._parse_entry(line)
        if not entry:
            return

        self._record_error(entry)
        self._check_failover(entry)

    def _parse_entry(self, line: str) -> Optional[dict]:
        line = line.strip()
        if not line:
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            log(f"Skipping unparsable log line: {line}")
            return None
        return data

    def _record_error(self, entry: dict) -> None:
        is_error = 1 if self._is_error(entry) else 0
        self.window.append(is_error)

        if len(self.window) < self.window.maxlen:
            return

        error_rate = sum(self.window) / len(self.window)
        if error_rate >= self.error_threshold:
            if not self.error_alert_active:
                self._notify(
                    "error_rate",
                    (
                        f"High upstream error rate detected: "
                        f"{error_rate * 100:.2f}% over last {len(self.window)} requests."
                    ),
                )
                self.error_alert_active = True
        else:
            self.error_alert_active = False

    def _check_failover(self, entry: dict) -> None:
        status = entry.get("status")
        pool = (entry.get("pool") or "").strip().lower()
        release = entry.get("release") or "unknown"

        if not pool or status != 200:
            return

        previous_pool = self.current_pool
        if previous_pool == pool:
            return

        self.current_pool = pool
        if previous_pool is None:
            log(f"Initial pool observed: {pool} (release {release})")
            return

        if self.primary_pool and pool == self.primary_pool:
            self._notify(
                "recovery",
                (
                    f"Traffic recovered to primary pool '{pool}' "
                    f"(was '{previous_pool}'). Release {release} now serving."
                ),
            )
        else:
            self._notify(
                "failover",
                (
                    f"Failover detected: traffic moved from '{previous_pool}' "
                    f"to '{pool}'. Release {release} now serving."
                ),
            )

    def _is_error(self, entry: dict) -> bool:
        upstream_status = entry.get("upstream_status")
        status_code = self._first_status(upstream_status)
        if status_code is None:
            status_code = entry.get("status")
        if status_code is None:
            return False
        try:
            return int(status_code) >= 500
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _first_status(value: Optional[object]) -> Optional[int]:
        if value is None:
            return None
        candidates: list[str] = []
        if isinstance(value, (list, tuple)):
            for item in value:
                candidates.append(str(item))
        else:
            candidates = str(value).split(",")

        for part in candidates:
            part = part.strip()
            if not part:
                continue
            try:
                return int(part)
            except ValueError:
                continue
        return None

    def _notify(self, alert_type: str, message: str) -> None:
        if self._in_cooldown(alert_type):
            return

        if self._maintenance_active():
            log(f"Maintenance mode active; suppressing {alert_type} alert: {message}")
            return

        if not self.webhook_url:
            log(f"Cannot send {alert_type} alert (no webhook configured): {message}")
            return

        payload = {"text": f":rotating_light: {message}"}
        try:
            response = requests.post(
                self.webhook_url, json=payload, timeout=5, headers={"Content-Type": "application/json"}
            )
            if response.status_code >= 400:
                log(
                    f"Slack webhook returned {response.status_code}: {response.text.strip()}"
                )
            else:
                log(f"Sent {alert_type} alert: {message}")
                self.cooldowns[alert_type] = time.time()
        except requests.RequestException as exc:
            log(f"Failed to send {alert_type} alert: {exc}")

    def _maintenance_active(self) -> bool:
        return bool(self.maintenance_flag and os.path.exists(self.maintenance_flag))

    def _in_cooldown(self, alert_type: str) -> bool:
        last = self.cooldowns.get(alert_type)
        if last is None:
            return False
        return (time.time() - last) < self.cooldown_seconds


def tail_file(path: str, watcher: AlertWatcher) -> None:
    file_obj = None
    inode = None

    while True:
        if file_obj is None:
            try:
                file_obj = open(path, "r", encoding="utf-8")
                file_obj.seek(0, os.SEEK_END)
                inode = os.fstat(file_obj.fileno()).st_ino
                log(f"Tailing log file {path}")
            except FileNotFoundError:
                time.sleep(1)
                continue

        line = file_obj.readline()
        if line:
            watcher.process_line(line)
            continue

        try:
            stat_result = os.stat(path)
            if inode is not None and stat_result.st_ino != inode:
                log("Log rotation detected; reopening file")
                file_obj.close()
                file_obj = None
                inode = None
                continue
            if file_obj.tell() > stat_result.st_size:
                file_obj.seek(0)
        except FileNotFoundError:
            file_obj.close()
            file_obj = None
            inode = None
        time.sleep(0.2)


def main() -> None:
    webhook_url = (os.getenv("SLACK_WEBHOOK_URL") or "").strip()
    if not webhook_url:
        log("SLACK_WEBHOOK_URL is required.")
        sys.exit(1)

    log_path = os.getenv("LOG_PATH", "/var/log/nginx/app_access.log")
    window_size = int(os.getenv("ALERT_ERROR_WINDOW", "200"))
    threshold = float(os.getenv("ALERT_ERROR_THRESHOLD", "0.02"))
    cooldown = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
    primary_pool = os.getenv("PRIMARY_POOL")
    maintenance_flag = os.getenv("MAINTENANCE_FLAG_FILE")

    watcher = AlertWatcher(
        webhook_url=webhook_url,
        log_path=log_path,
        window_size=window_size,
        error_threshold=threshold,
        cooldown_seconds=cooldown,
        primary_pool=primary_pool,
        maintenance_flag=maintenance_flag,
    )

    try:
        tail_file(log_path, watcher)
    except KeyboardInterrupt:
        log("Shutting down after keyboard interrupt.")


if __name__ == "__main__":
    main()
