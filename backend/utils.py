from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any, Iterable, Sequence


def utcnow() -> datetime:
    return datetime.now(UTC)


def utcnow_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


def clamp(value: float | int | None, minimum: float = 0.0, maximum: float = 100.0) -> float:
    if value is None:
        return minimum
    return max(minimum, min(float(value), maximum))


def safe_round(value: float | int | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def moving_average(values: Sequence[float], window: int) -> float:
    if not values:
        return 0.0
    target = list(values[-window:]) if len(values) >= window else list(values)
    return float(mean(target))


def delta(values: Sequence[float], window: int = 6) -> float:
    if len(values) < 2:
        return 0.0
    target = list(values[-window:]) if len(values) >= window else list(values)
    half = max(1, len(target) // 2)
    first = target[:half]
    second = target[half:]
    if not second:
        return 0.0
    return float(mean(second) - mean(first))


def trend_direction(change: float, tolerance: float = 1.5) -> str:
    if change > tolerance:
        return "rising"
    if change < -tolerance:
        return "falling"
    return "stable"


def now_minus_hours(hours: int | None) -> datetime | None:
    if hours is None:
        return None
    return utcnow() - timedelta(hours=hours)


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def json_loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def normalize_confidence(value: float | None) -> float:
    return clamp(value, 0.05, 0.99)


def health_label(score: float | None) -> str:
    if score is None:
        return "Collecting"
    if score >= 85:
        return "Excellent"
    if score >= 70:
        return "Healthy"
    if score >= 55:
        return "Guarded"
    if score >= 35:
        return "Fragile"
    return "At Risk"


def severity_rank(level: str) -> int:
    mapping = {"normal": 0, "warning": 1, "critical": 2, "emergency": 3}
    return mapping.get(level.lower(), 0)


def average(values: Iterable[float]) -> float:
    collected = list(values)
    if not collected:
        return 0.0
    return float(mean(collected))
