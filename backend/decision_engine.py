from __future__ import annotations

from dataclasses import dataclass

from backend.config import ThresholdBand, settings
from backend.utils import clamp, normalize_confidence


@dataclass
class DecisionResult:
    severity: str
    confidence: float
    explanation: str
    recommended_action: str
    alert_message: str
    score: float
    should_remediate: bool
    risk_factors: list[str]


def _threshold_points(value: float, band: ThresholdBand, weights: tuple[int, int, int]) -> tuple[float, str | None]:
    if value >= band.emergency:
        return float(weights[2]), "emergency"
    if value >= band.critical:
        return float(weights[1]), "critical"
    if value >= band.warning:
        return float(weights[0]), "warning"
    return 0.0, None


def evaluate_decision(metrics: list, prediction) -> DecisionResult:
    latest = metrics[-1]
    risk_score = max(0.0, 100.0 - float(prediction.health_score or 100.0))
    risk_factors: list[str] = []

    cpu_points, cpu_flag = _threshold_points(latest.cpu, settings.cpu_thresholds, (10, 18, 30))
    mem_points, mem_flag = _threshold_points(latest.memory, settings.memory_thresholds, (8, 14, 22))
    disk_points, disk_flag = _threshold_points(latest.disk, settings.disk_thresholds, (8, 14, 24))
    pred_points, pred_flag = _threshold_points(float(prediction.predicted_cpu or latest.cpu), settings.cpu_thresholds, (10, 18, 28))

    risk_score += cpu_points + mem_points + disk_points + pred_points

    if cpu_flag:
        risk_factors.append(f"CPU is operating in the {cpu_flag} band at {latest.cpu:.1f}%")
    if mem_flag:
        risk_factors.append(f"Memory pressure is {mem_flag} at {latest.memory:.1f}%")
    if disk_flag:
        risk_factors.append(f"Disk utilization is {disk_flag} at {latest.disk:.1f}%")
    if pred_flag:
        risk_factors.append(f"Predicted CPU enters the {pred_flag} band at {float(prediction.predicted_cpu or 0.0):.1f}%")

    cpu_trend = float(prediction.trend.get("cpu_delta", 0.0))
    memory_trend = float(prediction.trend.get("memory_delta", 0.0))
    disk_trend = float(prediction.trend.get("disk_delta", 0.0))

    if cpu_trend > 0:
        risk_score += min(cpu_trend * 1.8, 12.0)
        risk_factors.append(f"CPU trend is rising by {cpu_trend:.1f} points across the recent window")
    if memory_trend > 0:
        risk_score += min(memory_trend * 1.1, 6.0)
    if disk_trend > 1.5:
        risk_score += min(disk_trend * 1.1, 8.0)

    if prediction.anomaly:
        risk_score += 16.0
        risk_factors.append("Anomaly detection marked the latest sample as an outlier")

    risk_score = clamp(risk_score)

    if risk_score >= 78:
        severity = "emergency"
    elif risk_score >= 56:
        severity = "critical"
    elif risk_score >= 30:
        severity = "warning"
    else:
        severity = "normal"

    if latest.disk >= settings.disk_thresholds.critical:
        recommended_action = "cleanup_temp"
    elif severity in {"critical", "emergency"}:
        recommended_action = "inspect_top_processes"
    elif prediction.anomaly:
        recommended_action = "inspect_top_processes"
    else:
        recommended_action = "observe"

    should_remediate = severity in {"critical", "emergency"} and recommended_action != "observe"

    explanation = (
        " | ".join(risk_factors[:4])
        if risk_factors
        else "Current metrics, forecast, and trend direction are all within stable operating bands."
    )

    if severity == "emergency":
        alert_message = "Immediate operator attention is advised to prevent resource exhaustion."
    elif severity == "critical":
        alert_message = "The system is under sustained pressure and the advisor recommends targeted manual action."
    elif severity == "warning":
        alert_message = "The platform is stable for now, but resource pressure is building and should be trimmed early."
    else:
        alert_message = "The platform is healthy and no intervention is necessary."

    signal_bonus = min(0.18, len(risk_factors) * 0.03)
    confidence = normalize_confidence(float(prediction.confidence) * 0.72 + 0.18 + signal_bonus)

    return DecisionResult(
        severity=severity,
        confidence=round(confidence, 3),
        explanation=explanation,
        recommended_action=recommended_action,
        alert_message=alert_message,
        score=round(risk_score, 2),
        should_remediate=should_remediate,
        risk_factors=risk_factors,
    )
