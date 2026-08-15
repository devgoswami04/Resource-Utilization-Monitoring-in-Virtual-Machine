from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest, RandomForestRegressor

from backend.config import settings
from backend.logger import get_logger
from backend.utils import clamp, delta, normalize_confidence, safe_round, trend_direction


logger = get_logger("backend.predictor")


@dataclass
class PredictorResult:
    predicted_cpu: float | None
    anomaly: bool
    health_score: float | None
    severity: str
    alert_message: str | None
    recommendation: str | None
    confidence: float
    explanation: str
    trend: dict[str, float | str]
    window_size: int
    model_version: str


def _build_feature_matrix(metrics: list) -> tuple[np.ndarray, np.ndarray]:
    samples: list[list[float]] = []
    targets: list[float] = []

    for index in range(len(metrics) - 1):
        current = metrics[index]
        previous = metrics[index - 1] if index > 0 else current
        samples.append(
            [
                current.cpu,
                current.memory,
                current.disk,
                float(current.load_average or 0.0),
                float(current.process_count or 0),
                current.cpu - previous.cpu,
                current.memory - previous.memory,
                current.disk - previous.disk,
            ]
        )
        targets.append(metrics[index + 1].cpu)

    return np.array(samples, dtype=float), np.array(targets, dtype=float)


def _fallback_prediction(metrics: list) -> float:
    cpus = [metric.cpu for metric in metrics]
    baseline = cpus[-1]
    trend_boost = delta(cpus, window=min(6, len(cpus)))
    rolling = float(np.mean(cpus[-min(4, len(cpus)) :]))
    return clamp((baseline * 0.55) + (rolling * 0.35) + (trend_boost * 1.5))


def _predict_next_cpu(metrics: list, features: np.ndarray, targets: np.ndarray) -> float:
    if len(features) < 6:
        return _fallback_prediction(metrics)

    model = RandomForestRegressor(
        n_estimators=120,
        max_depth=6,
        min_samples_leaf=2,
        random_state=42,
    )
    model.fit(features, targets)
    prediction = model.predict(features[-1].reshape(1, -1))[0]
    return clamp(prediction)


def _detect_anomaly(features: np.ndarray, latest_vector: np.ndarray, metrics: list) -> bool:
    if len(features) >= 8:
        contamination = min(0.18, max(0.08, 2 / max(len(features), 1)))
        detector = IsolationForest(
            n_estimators=120,
            contamination=contamination,
            random_state=42,
        )
        detector.fit(features)
        return bool(detector.predict(latest_vector.reshape(1, -1))[0] == -1)

    cpu_values = np.array([metric.cpu for metric in metrics], dtype=float)
    mean_cpu = float(cpu_values.mean())
    std_cpu = float(cpu_values.std()) or 1.0
    z_score = abs((metrics[-1].cpu - mean_cpu) / std_cpu)
    return bool(z_score > 1.8 or metrics[-1].cpu >= settings.cpu_thresholds.critical)


def _derive_health_score(metrics: list, predicted_cpu: float, anomaly: bool) -> float:
    latest = metrics[-1]
    cpu_trend = max(delta([metric.cpu for metric in metrics], window=min(6, len(metrics))), 0.0)
    utilization_penalty = (latest.cpu * 0.42) + (latest.memory * 0.33) + (latest.disk * 0.25)
    predictive_penalty = max(predicted_cpu - latest.cpu, 0.0) * 0.28
    trend_penalty = cpu_trend * 1.45
    anomaly_penalty = 12.0 if anomaly else 0.0
    score = 100.0 - utilization_penalty - predictive_penalty - trend_penalty - anomaly_penalty
    return clamp(score)


def _derive_severity(predicted_cpu: float, health_score: float, anomaly: bool) -> str:
    if predicted_cpu >= settings.cpu_thresholds.emergency or health_score <= 25:
        return "emergency"
    if predicted_cpu >= settings.cpu_thresholds.critical or health_score <= 45 or anomaly:
        return "critical"
    if predicted_cpu >= settings.cpu_thresholds.warning or health_score <= 65:
        return "warning"
    return "normal"


def build_prediction(metrics: list) -> PredictorResult:
    if not metrics:
        return PredictorResult(
            predicted_cpu=None,
            anomaly=False,
            health_score=None,
            severity="normal",
            alert_message="No telemetry has been received yet.",
            recommendation="await_metrics",
            confidence=0.1,
            explanation="The platform is waiting for the first metric payload.",
            trend={
                "cpu_delta": 0.0,
                "memory_delta": 0.0,
                "disk_delta": 0.0,
                "cpu_direction": "stable",
                "memory_direction": "stable",
                "disk_direction": "stable",
            },
            window_size=0,
            model_version=settings.model_version,
        )

    recent_metrics = metrics[-settings.prediction_window :]
    cpu_delta = delta([metric.cpu for metric in recent_metrics], window=min(8, len(recent_metrics)))
    memory_delta = delta([metric.memory for metric in recent_metrics], window=min(8, len(recent_metrics)))
    disk_delta = delta([metric.disk for metric in recent_metrics], window=min(8, len(recent_metrics)))

    trend = {
        "cpu_delta": safe_round(cpu_delta) or 0.0,
        "memory_delta": safe_round(memory_delta) or 0.0,
        "disk_delta": safe_round(disk_delta) or 0.0,
        "cpu_direction": trend_direction(cpu_delta),
        "memory_direction": trend_direction(memory_delta, tolerance=1.0),
        "disk_direction": trend_direction(disk_delta, tolerance=0.8),
    }

    if len(recent_metrics) < 4:
        latest = recent_metrics[-1]
        baseline_score = clamp(100 - ((latest.cpu * 0.45) + (latest.memory * 0.35) + (latest.disk * 0.20)))
        return PredictorResult(
            predicted_cpu=safe_round(latest.cpu),
            anomaly=False,
            health_score=safe_round(baseline_score),
            severity="warning" if latest.cpu >= settings.cpu_thresholds.warning else "normal",
            alert_message="Collecting additional samples to stabilize the forecast.",
            recommendation="observe",
            confidence=0.32,
            explanation="The predictor is using a bootstrap heuristic until enough history is available for ML scoring.",
            trend=trend,
            window_size=len(recent_metrics),
            model_version=settings.model_version,
        )

    features, targets = _build_feature_matrix(recent_metrics)
    latest_vector = features[-1]
    predicted_cpu = _predict_next_cpu(recent_metrics, features, targets)
    anomaly = _detect_anomaly(features, latest_vector, recent_metrics)
    health_score = _derive_health_score(recent_metrics, predicted_cpu, anomaly)
    severity = _derive_severity(predicted_cpu, health_score, anomaly)

    confidence = normalize_confidence(0.42 + (len(recent_metrics) * 0.012) - (0.08 if anomaly else 0.0))

    if severity in {"critical", "emergency"}:
        alert_message = "Resource pressure is accelerating and likely to breach safe operating bands soon."
    elif anomaly:
        alert_message = "The latest sample deviates from the recent operating baseline."
    elif severity == "warning":
        alert_message = "Utilization is climbing and should be watched closely."
    else:
        alert_message = "Forecast is stable and no immediate risk is predicted."

    if predicted_cpu >= settings.cpu_thresholds.critical:
        recommendation = "inspect_top_processes"
    elif recent_metrics[-1].disk >= settings.disk_thresholds.critical:
        recommendation = "cleanup_temp"
    else:
        recommendation = "observe"

    explanation = (
        f"Predicted CPU is {predicted_cpu:.1f}% from a {len(recent_metrics)}-sample hybrid window; "
        f"CPU trend is {trend['cpu_direction']} ({cpu_delta:+.1f}), "
        f"memory trend is {trend['memory_direction']} ({memory_delta:+.1f}), "
        f"and anomaly detection returned {'outlier' if anomaly else 'normal'}."
    )

    logger.info(
        "Generated prediction: cpu=%s anomaly=%s health=%s severity=%s",
        f"{predicted_cpu:.1f}",
        anomaly,
        f"{health_score:.1f}",
        severity,
    )

    return PredictorResult(
        predicted_cpu=safe_round(predicted_cpu),
        anomaly=anomaly,
        health_score=safe_round(health_score),
        severity=severity,
        alert_message=alert_message,
        recommendation=recommendation,
        confidence=safe_round(confidence, 3) or 0.0,
        explanation=explanation,
        trend=trend,
        window_size=len(recent_metrics),
        model_version=settings.model_version,
    )
