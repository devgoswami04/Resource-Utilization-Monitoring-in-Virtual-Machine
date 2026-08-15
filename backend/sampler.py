"""Built-in telemetry sampler.

Historically the platform depended on the standalone ``agent/monitor.py`` process
to push telemetry into the API. In practice that meant the dashboard sat on stale
demo rows whenever the agent was not running. This module lets the backend feed
itself: a lightweight background thread samples the real machine with psutil and
ingests a metric on a fixed interval, so live data flows the moment the API boots.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import psutil

from backend.config import settings
from backend.database import SessionLocal
from backend.logger import get_logger
from backend.monitor import ingest_metric
from backend.schemas import MetricIngestRequest, TopProcess


logger = get_logger("backend.sampler")


def _top_processes(limit: int) -> list[TopProcess]:
    """Return the heaviest processes.

    Uses the batched ``process_iter(attrs=...)`` form so psutil pulls each
    process' fields under a single ``oneshot()`` — dramatically fewer syscalls
    than calling ``cpu_percent()``/``memory_info()`` per process. The costly IO
    counters and per-process ``status()`` are intentionally skipped here; the
    advisor backfills them lazily for the handful of processes it surfaces.
    """
    if not settings.collect_top_processes or limit <= 0:
        return []

    offenders: list[dict] = []
    snapshot_time = time.time()
    for process in psutil.process_iter(
        ["pid", "name", "username", "cpu_percent", "memory_percent", "memory_info", "create_time"]
    ):
        try:
            info = process.info
            name = str(info.get("name") or "unknown")
            pid = int(info.get("pid") or 0)
            if pid == 0 or name.lower() == "system idle process":
                continue
            memory_info = info.get("memory_info")
            create_time = info.get("create_time") or snapshot_time
            offenders.append(
                {
                    "pid": pid,
                    "name": name,
                    "cpu_percent": round(float(info.get("cpu_percent") or 0.0), 2),
                    "memory_percent": round(float(info.get("memory_percent") or 0.0), 2),
                    "memory_mb": round(float(getattr(memory_info, "rss", 0.0)) / (1024 * 1024), 2),
                    "runtime_minutes": round(max(snapshot_time - create_time, 0.0) / 60.0, 1),
                    "read_mb": 0.0,
                    "write_mb": 0.0,
                    "status": None,
                    "username": info.get("username"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, PermissionError, OSError):
            continue

    offenders.sort(key=lambda item: (item["cpu_percent"], item["memory_percent"]), reverse=True)
    return [TopProcess(**item) for item in offenders[:limit]]


def collect_sample(top_processes: list[TopProcess] | None = None) -> MetricIngestRequest:
    disk_path = Path.cwd().anchor or "/"
    load_average = 0.0
    if hasattr(psutil, "getloadavg"):
        try:
            load_average = float(psutil.getloadavg()[0])
        except OSError:
            load_average = 0.0

    return MetricIngestRequest(
        cpu=round(psutil.cpu_percent(interval=None), 2),
        memory=round(psutil.virtual_memory().percent, 2),
        disk=round(psutil.disk_usage(disk_path).percent, 2),
        load_average=round(load_average, 2),
        process_count=len(psutil.pids()),
        hostname=settings.hostname,
        environment=settings.platform_environment,
        source="backend-sampler",
        top_processes=top_processes if top_processes is not None else _top_processes(settings.top_process_limit),
    )


class TelemetrySampler:
    """Background thread that keeps the metrics table fed with live samples."""

    def __init__(self, interval_seconds: int | None = None) -> None:
        self.interval_seconds = max(int(interval_seconds or settings.sampler_interval_seconds), 1)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Prime psutil so the first cpu_percent reading is meaningful rather than 0.
        psutil.cpu_percent(interval=None)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="telemetry-sampler", daemon=True)
        self._thread.start()
        logger.info("Telemetry sampler started (every %ss).", self.interval_seconds)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval_seconds + 2)
            self._thread = None
        logger.info("Telemetry sampler stopped.")

    def _run(self) -> None:
        # Core metrics (cpu/mem/disk) refresh every interval; the heavier process
        # scan only refreshes periodically and is reused in between so a single
        # slow scan never starves the fast telemetry cadence.
        process_refresh_every = max(settings.top_process_limit and 4, 4)
        cached_processes: list[TopProcess] = []
        iteration = 0

        while not self._stop.is_set():
            started = time.time()
            if iteration % process_refresh_every == 0:
                try:
                    cached_processes = _top_processes(settings.top_process_limit)
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Process scan failed: %s", exc)

            db = SessionLocal()
            try:
                ingest_metric(db, collect_sample(top_processes=cached_processes))
            except Exception as exc:  # pragma: no cover - defensive background loop
                logger.warning("Sampler iteration failed: %s", exc)
            finally:
                db.close()

            iteration += 1
            elapsed = time.time() - started
            self._stop.wait(max(self.interval_seconds - elapsed, 0.5))
