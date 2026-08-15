from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

import psutil
import requests


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from backend.config import settings  # noqa: E402
from backend.logger import get_logger  # noqa: E402


logger = get_logger("agent.monitor")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000/metrics")
HOSTNAME = socket.gethostname()
ENVIRONMENT = os.getenv("PLATFORM_ENVIRONMENT", settings.platform_environment)
INTERVAL_SECONDS = settings.monitor_interval_seconds
RETRY_ATTEMPTS = settings.agent_retry_attempts


def _top_processes(limit: int) -> list[dict]:
    offenders: list[dict] = []
    snapshot_time = time.time()
    for process in psutil.process_iter(["pid", "name", "username"]):
        try:
            info = process.info
            process_name = str(info.get("name") or "unknown")
            if int(info.get("pid") or 0) == 0 or process_name.lower() == "system idle process":
                continue
            memory_info = process.memory_info()
            io_counters = process.io_counters() if hasattr(process, "io_counters") else None
            create_time = process.create_time()
            offenders.append(
                {
                    "pid": int(info.get("pid") or 0),
                    "name": process_name,
                    "cpu_percent": round(float(process.cpu_percent(interval=None) or 0.0), 2),
                    "memory_percent": round(float(process.memory_percent() or 0.0), 2),
                    "memory_mb": round(float(memory_info.rss) / (1024 * 1024), 2),
                    "runtime_minutes": round(max(snapshot_time - create_time, 0.0) / 60.0, 1),
                    "read_mb": round(float(getattr(io_counters, "read_bytes", 0.0)) / (1024 * 1024), 2),
                    "write_mb": round(float(getattr(io_counters, "write_bytes", 0.0)) / (1024 * 1024), 2),
                    "status": process.status(),
                    "username": info.get("username"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, PermissionError, OSError):
            continue
    offenders.sort(key=lambda item: (item["cpu_percent"], item["memory_percent"]), reverse=True)
    return offenders[:limit]


def collect_metrics() -> dict:
    disk_path = Path.cwd().anchor or "/"
    load_average = 0.0
    if hasattr(psutil, "getloadavg"):
        try:
            load_average = float(psutil.getloadavg()[0])
        except OSError:
            load_average = 0.0

    return {
        "cpu": round(psutil.cpu_percent(interval=None), 2),
        "memory": round(psutil.virtual_memory().percent, 2),
        "disk": round(psutil.disk_usage(disk_path).percent, 2),
        "load_average": round(load_average, 2),
        "process_count": len(psutil.pids()),
        "hostname": HOSTNAME,
        "environment": ENVIRONMENT,
        "source": "monitor-agent",
        "top_processes": _top_processes(settings.top_process_limit) if settings.collect_top_processes else [],
    }


def send_metrics(session: requests.Session, payload: dict) -> None:
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = session.post(BACKEND_URL, json=payload, timeout=settings.request_timeout_seconds)
            response.raise_for_status()
            logger.info(
                "Sent telemetry sample cpu=%.1f memory=%.1f disk=%.1f",
                payload["cpu"],
                payload["memory"],
                payload["disk"],
            )
            return
        except requests.RequestException as exc:
            delay = min(2**attempt, 10)
            response_body = ""
            if getattr(exc, "response", None) is not None:
                response_body = exc.response.text[:500]
            logger.warning(
                "Metric send failed on attempt %s/%s: %s%s",
                attempt,
                RETRY_ATTEMPTS,
                exc,
                f" | backend_response={response_body}" if response_body else "",
            )
            if attempt == RETRY_ATTEMPTS:
                logger.error("Dropping telemetry sample after exhausting retries.")
                return
            time.sleep(delay)


def main() -> None:
    logger.info("Starting monitor agent -> %s", BACKEND_URL)
    with requests.Session() as session:
        psutil.cpu_percent(interval=None)
        while True:
            try:
                payload = collect_metrics()
                send_metrics(session, payload)
            except Exception as exc:  # pragma: no cover - defensive path
                logger.exception("Monitoring loop encountered an error: %s", exc)
            time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
