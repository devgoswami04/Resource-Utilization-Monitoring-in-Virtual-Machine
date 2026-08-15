from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


_ENV_CACHE = _load_env_file(ENV_FILE)


def _get_env(name: str, default: str) -> str:
    return os.getenv(name, _ENV_CACHE.get(name, default))


def _get_bool(name: str, default: bool) -> bool:
    value = _get_env(name, str(default))
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(name: str, default: int) -> int:
    value = _get_env(name, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def _get_float(name: str, default: float) -> float:
    value = _get_env(name, str(default))
    try:
        return float(value)
    except ValueError:
        return default


def _get_list(name: str, default: list[str]) -> list[str]:
    raw = _get_env(name, ",".join(default))
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


@dataclass(frozen=True)
class ThresholdBand:
    warning: float
    critical: float
    emergency: float


@dataclass(frozen=True)
class Settings:
    app_name: str = _get_env("APP_NAME", "Aegis Resource Advisor")
    platform_environment: str = _get_env("PLATFORM_ENVIRONMENT", "student-laptop")
    database_path: Path = Path(
        _get_env("DATABASE_PATH", str(BACKEND_DIR / "metrics.db"))
    ).expanduser().resolve()
    log_path: Path = Path(
        _get_env("LOG_PATH", str(BACKEND_DIR / "platform.log"))
    ).expanduser().resolve()
    frontend_origins: list[str] = field(
        default_factory=lambda: _get_list(
            "FRONTEND_ORIGINS",
            ["http://127.0.0.1:5173", "http://localhost:5173"],
        )
    )
    frontend_api_base_url: str = _get_env("FRONTEND_API_BASE_URL", "http://127.0.0.1:8000")
    prediction_window: int = _get_int("PREDICTION_WINDOW", 48)
    dashboard_history_limit: int = _get_int("DASHBOARD_HISTORY_LIMIT", 36)
    incident_history_limit: int = _get_int("INCIDENT_HISTORY_LIMIT", 20)
    action_history_limit: int = _get_int("ACTION_HISTORY_LIMIT", 20)
    monitor_interval_seconds: int = _get_int("MONITOR_INTERVAL_SECONDS", 5)
    enable_local_sampler: bool = _get_bool("ENABLE_LOCAL_SAMPLER", True)
    sampler_interval_seconds: int = _get_int("SAMPLER_INTERVAL_SECONDS", 4)
    request_timeout_seconds: int = _get_int("REQUEST_TIMEOUT_SECONDS", 12)
    agent_retry_attempts: int = _get_int("AGENT_RETRY_ATTEMPTS", 3)
    collect_top_processes: bool = _get_bool("COLLECT_TOP_PROCESSES", True)
    top_process_limit: int = _get_int("TOP_PROCESS_LIMIT", 8)
    demo_mode: bool = _get_bool("DEMO_MODE", True)
    auto_remediation_enabled: bool = _get_bool("AUTO_REMEDIATION_ENABLED", False)
    allow_live_remediation: bool = _get_bool("ALLOW_LIVE_REMEDIATION", False)
    remediation_default_mode: str = _get_env("REMEDIATION_DEFAULT_MODE", "simulate")
    remediation_safety_mode: str = _get_env("REMEDIATION_SAFETY_MODE", "strict")
    remediation_cooldown_seconds: int = _get_int("REMEDIATION_COOLDOWN_SECONDS", 90)
    cpu_thresholds: ThresholdBand = field(
        default_factory=lambda: ThresholdBand(
            warning=_get_float("CPU_WARNING_THRESHOLD", 70.0),
            critical=_get_float("CPU_CRITICAL_THRESHOLD", 85.0),
            emergency=_get_float("CPU_EMERGENCY_THRESHOLD", 95.0),
        )
    )
    memory_thresholds: ThresholdBand = field(
        default_factory=lambda: ThresholdBand(
            warning=_get_float("MEMORY_WARNING_THRESHOLD", 72.0),
            critical=_get_float("MEMORY_CRITICAL_THRESHOLD", 86.0),
            emergency=_get_float("MEMORY_EMERGENCY_THRESHOLD", 94.0),
        )
    )
    disk_thresholds: ThresholdBand = field(
        default_factory=lambda: ThresholdBand(
            warning=_get_float("DISK_WARNING_THRESHOLD", 78.0),
            critical=_get_float("DISK_CRITICAL_THRESHOLD", 90.0),
            emergency=_get_float("DISK_EMERGENCY_THRESHOLD", 96.0),
        )
    )
    allowlisted_processes: list[str] = field(
        default_factory=lambda: _get_list("ALLOWED_PROCESSES", ["demo-worker.exe", "stress-ng"])
    )
    demo_terminatable_processes: list[str] = field(
        default_factory=lambda: _get_list("DEMO_TERMINATABLE_PROCESSES", ["demo-worker.exe"])
    )
    denied_processes: list[str] = field(
        default_factory=lambda: _get_list(
            "DENIED_PROCESSES",
            [
                "system",
                "system idle process",
                "wininit.exe",
                "csrss.exe",
                "services.exe",
                "lsass.exe",
                "svchost.exe",
                "registry",
                "python.exe",
                "pythonw.exe",
            ],
        )
    )
    cleanup_paths: list[Path] = field(
        default_factory=lambda: [
            Path(path).expanduser().resolve()
            for path in _get_list(
                "ALLOWED_CLEANUP_PATHS",
                [str(ROOT_DIR / "backend" / "demo_temp"), str(ROOT_DIR / "frontend-react" / "dist")],
            )
        ]
    )
    hostname: str = socket.gethostname()
    model_version: str = _get_env("MODEL_VERSION", "hybrid-rf-v2")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.database_path.as_posix()}"


settings = Settings()
