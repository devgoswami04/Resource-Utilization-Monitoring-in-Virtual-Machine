from __future__ import annotations

from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import WRITE_LOCK, run_with_retry
from backend.decision_engine import DecisionResult, evaluate_decision
from backend.logger import get_logger
from backend.models import IncidentEvent, Metrics, RemediationAction
from backend.predictor import PredictorResult, build_prediction
from backend.remediation import RemediationEngine, action_details
from backend.schemas import (
    ActionRecord,
    IncidentRecord,
    MetricIngestRequest,
    MetricRecord,
    PredictionResponse,
    SummaryResponse,
    TopProcess,
    TrendSummary,
)
from backend.utils import health_label, json_dumps, json_loads, now_minus_hours, parse_timestamp, utcnow, utcnow_iso


logger = get_logger("backend.monitor")


def serialize_metric(metric: Metrics) -> MetricRecord:
    top_processes = [TopProcess.model_validate(item) for item in json_loads(metric.top_processes_json, [])]
    return MetricRecord(
        id=metric.id,
        timestamp=metric.timestamp,
        received_at=metric.received_at,
        cpu=metric.cpu,
        memory=metric.memory,
        disk=metric.disk,
        load_average=metric.load_average,
        process_count=metric.process_count,
        hostname=metric.hostname,
        environment=metric.environment,
        source=metric.source,
        top_processes=top_processes,
        predicted_cpu=metric.predicted_cpu,
        anomaly_flag=bool(metric.anomaly_flag),
        health_score=metric.health_score,
        severity_level=metric.severity_level,
        confidence_score=metric.confidence_score,
        trend_cpu=metric.trend_cpu,
        trend_memory=metric.trend_memory,
        trend_disk=metric.trend_disk,
        alert_message=metric.alert_message,
        recommended_action=metric.recommended_action,
        decision_explanation=metric.decision_explanation,
        remediation_suggested=bool(metric.remediation_suggested),
        remediation_executed=bool(metric.remediation_executed),
        remediation_notes=metric.remediation_notes,
        action_taken=metric.action_taken,
        action_status=metric.action_status,
        action_timestamp=metric.action_timestamp,
        model_version=metric.model_version,
        metric_window_size=metric.metric_window_size,
        ingestion_status=metric.ingestion_status,
    )


def serialize_incident(incident: IncidentEvent) -> IncidentRecord:
    return IncidentRecord(
        id=incident.id,
        metric_id=incident.metric_id,
        event_type=incident.event_type,
        severity=incident.severity,
        status=incident.status,
        title=incident.title,
        message=incident.message,
        confidence_score=incident.confidence_score,
        created_at=incident.created_at,
        metadata=json_loads(incident.metadata_json, {}),
    )


def serialize_action(action: RemediationAction) -> ActionRecord:
    return ActionRecord(
        id=action.id,
        metric_id=action.metric_id,
        requested_action=action.requested_action,
        action_type=action.action_type,
        mode=action.mode,
        triggered_by=action.triggered_by,
        severity=action.severity,
        status=action.status,
        notes=action.notes,
        result_summary=action.result_summary,
        details=action_details(action),
        created_at=action.created_at,
        completed_at=action.completed_at,
    )


def fetch_recent_metrics(db: Session, limit: int) -> list[Metrics]:
    records = run_with_retry(
        lambda: db.query(Metrics).order_by(Metrics.id.desc()).limit(limit).all(),
        session=db,
    )
    return list(reversed(records))


def fetch_metrics_history(db: Session, *, limit: int = 50, hours: int | None = None) -> list[MetricRecord]:
    query_limit = max(limit * 4, limit)
    records = run_with_retry(
        lambda: db.query(Metrics).order_by(Metrics.id.desc()).limit(query_limit).all(),
        session=db,
    )
    cutoff = now_minus_hours(hours)

    filtered: list[MetricRecord] = []
    for metric in records:
        if cutoff:
            parsed = parse_timestamp(metric.timestamp)
            if parsed and parsed < cutoff:
                continue
        filtered.append(serialize_metric(metric))
        if len(filtered) >= limit:
            break
    return filtered


def _build_prediction_response(prediction: PredictorResult, decision: DecisionResult) -> PredictionResponse:
    return PredictionResponse(
        predicted_cpu=prediction.predicted_cpu,
        anomaly=prediction.anomaly,
        health_score=prediction.health_score,
        severity=decision.severity,
        alert_message=decision.alert_message or prediction.alert_message,
        recommendation=decision.recommended_action,
        confidence=decision.confidence,
        explanation=f"{prediction.explanation} {decision.explanation}".strip(),
        trend=TrendSummary(**prediction.trend),
        model_version=prediction.model_version,
        window_size=prediction.window_size,
    )


def assess_recent_metrics(metrics: list[Metrics]) -> tuple[PredictorResult, DecisionResult]:
    prediction = build_prediction(metrics)
    if not metrics:
        decision = DecisionResult(
            severity="normal",
            confidence=prediction.confidence,
            explanation="No metrics are available yet.",
            recommended_action="await_metrics",
            alert_message=prediction.alert_message or "Waiting for telemetry.",
            score=0.0,
            should_remediate=False,
            risk_factors=[],
        )
        return prediction, decision
    decision = evaluate_decision(metrics, prediction)
    return prediction, decision


def _create_incidents(
    db: Session,
    metric: Metrics,
    prediction: PredictorResult,
    decision: DecisionResult,
) -> list[IncidentEvent]:
    created: list[IncidentEvent] = []
    if decision.severity in {"warning", "critical", "emergency"}:
        incident = IncidentEvent(
            metric_id=metric.id,
            event_type="resource_pressure",
            severity=decision.severity,
            status="open",
            title=f"{decision.severity.title()} resource pressure",
            message=decision.explanation,
            confidence_score=decision.confidence,
            created_at=utcnow_iso(),
            metadata_json=json_dumps({"risk_factors": decision.risk_factors}),
        )
        db.add(incident)
        created.append(incident)

    if prediction.anomaly:
        anomaly_incident = IncidentEvent(
            metric_id=metric.id,
            event_type="anomaly",
            severity=decision.severity,
            status="open",
            title="Anomaly detected",
            message=prediction.alert_message or "The platform detected an anomalous telemetry sample.",
            confidence_score=prediction.confidence,
            created_at=utcnow_iso(),
            metadata_json=json_dumps(prediction.trend),
        )
        db.add(anomaly_incident)
        created.append(anomaly_incident)

    return created


def _can_auto_remediate(db: Session, action_name: str) -> bool:
    if not settings.auto_remediation_enabled:
        return False

    last_action = run_with_retry(
        lambda: db.query(RemediationAction).order_by(RemediationAction.id.desc()).first(),
        session=db,
    )
    if not last_action:
        return True

    created_at = parse_timestamp(last_action.created_at)
    if not created_at:
        return True

    seconds_since = (utcnow() - created_at).total_seconds()
    if last_action.action_type == action_name and seconds_since < settings.remediation_cooldown_seconds:
        return False
    return True


def ingest_metric(db: Session, payload: MetricIngestRequest) -> dict:
    top_processes = [process.model_dump() for process in payload.top_processes[: settings.top_process_limit]]
    sample_timestamp = payload.timestamp or utcnow_iso()
    received_at = utcnow_iso()
    recent_metrics = fetch_recent_metrics(db, max(settings.prediction_window - 1, 0))
    preview_metric = Metrics(
        timestamp=sample_timestamp,
        received_at=received_at,
        cpu=payload.cpu,
        memory=payload.memory,
        disk=payload.disk,
        load_average=payload.load_average or 0.0,
        process_count=payload.process_count or len(top_processes),
        hostname=payload.hostname or settings.hostname,
        environment=payload.environment or settings.platform_environment,
        source=payload.source or "agent",
        top_processes_json=json_dumps(top_processes),
        ingestion_status="stored",
        model_version=settings.model_version,
    )
    prediction, decision = assess_recent_metrics([*recent_metrics, preview_metric])

    def _persist_metric():
        metric = Metrics(
            timestamp=sample_timestamp,
            received_at=received_at,
            cpu=payload.cpu,
            memory=payload.memory,
            disk=payload.disk,
            load_average=payload.load_average or 0.0,
            process_count=payload.process_count or len(top_processes),
            hostname=payload.hostname or settings.hostname,
            environment=payload.environment or settings.platform_environment,
            source=payload.source or "agent",
            top_processes_json=json_dumps(top_processes),
            model_version=settings.model_version,
            predicted_cpu=prediction.predicted_cpu,
            anomaly_flag=prediction.anomaly,
            health_score=prediction.health_score,
            severity_level=decision.severity,
            confidence_score=decision.confidence,
            trend_cpu=float(prediction.trend.get("cpu_delta", 0.0)),
            trend_memory=float(prediction.trend.get("memory_delta", 0.0)),
            trend_disk=float(prediction.trend.get("disk_delta", 0.0)),
            alert_message=decision.alert_message or prediction.alert_message,
            recommended_action=decision.recommended_action,
            decision_explanation=f"{prediction.explanation} {decision.explanation}".strip(),
            remediation_suggested=decision.should_remediate,
            metric_window_size=prediction.window_size,
            ingestion_status="analyzed",
        )
        db.add(metric)
        db.flush()

        incidents = _create_incidents(db, metric, prediction, decision)

        auto_action = None
        if decision.should_remediate and _can_auto_remediate(db, decision.recommended_action):
            auto_action = RemediationEngine(db).execute(
                action_type=decision.recommended_action,
                metric=metric,
                requested_by="autopilot",
                requested_mode=settings.remediation_default_mode,
                reason=decision.explanation,
                notes="Autonomous remediation triggered by the decision engine.",
            )

        db.commit()
        db.refresh(metric)
        if auto_action:
            db.refresh(auto_action)
        return metric, incidents, auto_action

    with WRITE_LOCK:
        metric, incidents, auto_action = run_with_retry(_persist_metric, session=db)

    logger.info(
        "Metric ingested id=%s cpu=%.1f memory=%.1f disk=%.1f severity=%s",
        metric.id,
        metric.cpu,
        metric.memory,
        metric.disk,
        metric.severity_level,
    )

    return {
        "metric": serialize_metric(metric),
        "prediction": _build_prediction_response(prediction, decision),
        "incidents": [serialize_incident(incident) for incident in incidents],
        "auto_action": serialize_action(auto_action) if auto_action else None,
    }


def build_summary(db: Session) -> SummaryResponse:
    recent_metrics = fetch_recent_metrics(db, settings.prediction_window)
    latest_metric = recent_metrics[-1] if recent_metrics else None
    prediction, decision = assess_recent_metrics(recent_metrics)
    prediction_response = _build_prediction_response(prediction, decision)

    active_alerts = run_with_retry(
        lambda: (
            db.query(IncidentEvent)
            .filter(IncidentEvent.status == "open")
            .order_by(IncidentEvent.id.desc())
            .limit(settings.incident_history_limit)
            .all()
        ),
        session=db,
    )
    action = run_with_retry(
        lambda: db.query(RemediationAction).order_by(RemediationAction.id.desc()).first(),
        session=db,
    )

    live_connection = "connected"
    if latest_metric:
        parsed = parse_timestamp(latest_metric.timestamp)
        if parsed:
            age = (utcnow() - parsed).total_seconds()
            if age > settings.monitor_interval_seconds * 3:
                live_connection = "stale"
    else:
        live_connection = "waiting"

    return SummaryResponse(
        generated_at=utcnow_iso(),
        current_metrics=serialize_metric(latest_metric) if latest_metric else None,
        trends=TrendSummary(**prediction.trend),
        prediction=prediction_response,
        active_alerts=[serialize_incident(item) for item in active_alerts[:8]],
        last_action=serialize_action(action) if action else None,
        system_health=health_label(prediction.health_score),
        live_connection=live_connection,
        remediation_mode=settings.remediation_default_mode,
        auto_remediation_enabled=settings.auto_remediation_enabled,
    )
