from __future__ import annotations

from contextlib import asynccontextmanager
from threading import Lock
import time

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.advisor import build_advisor
from backend.config import settings
from backend.database import WRITE_LOCK, get_db, init_db, run_with_retry
from backend.logger import get_logger
from backend.models import Metrics, RemediationAction
from backend.monitor import (
    assess_recent_metrics,
    build_summary,
    fetch_metrics_history,
    fetch_recent_metrics,
    ingest_metric,
    serialize_action,
    serialize_metric,
)
from backend.remediation import RemediationEngine
from backend.sampler import TelemetrySampler
from backend.schemas import (
    ActionRecord,
    DashboardResponse,
    MetricIngestRequest,
    MetricRecord,
    PredictionResponse,
    RemediationRequest,
    RemediationResponse,
    SummaryResponse,
)
from backend.utils import utcnow_iso


logger = get_logger("backend.api")
_DASHBOARD_CACHE_SECONDS = 2.0
_dashboard_cache_lock = Lock()
_dashboard_cache: dict[str, object] = {"expires_at": 0.0, "payload": None}


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    logger.info("Backend initialized with database at %s", settings.database_path)

    sampler: TelemetrySampler | None = None
    if settings.enable_local_sampler:
        sampler = TelemetrySampler()
        sampler.start()
    else:
        logger.info("Local telemetry sampler disabled; expecting an external agent.")

    try:
        yield
    finally:
        if sampler is not None:
            sampler.stop()


app = FastAPI(
    title=settings.app_name,
    description="Real-time resource monitoring, prediction, and intent-aware optimization advisor.",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health_check(db: Session = Depends(get_db)) -> dict:
    try:
        run_with_retry(lambda: db.execute(text("SELECT 1")), session=db)
        db_ok = True
    except Exception as exc:  # pragma: no cover - defensive path
        db_ok = False
        logger.exception("Health check failed: %s", exc)

    latest_metric = run_with_retry(
        lambda: db.query(Metrics).order_by(Metrics.id.desc()).first(),
        session=db,
    )
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "connected" if db_ok else "error",
        "demo_mode": settings.demo_mode,
        "auto_remediation_enabled": settings.auto_remediation_enabled,
        "latest_metric_timestamp": getattr(latest_metric, "timestamp", None),
        "version": app.version,
    }


@app.post("/metrics")
def post_metrics(payload: MetricIngestRequest, db: Session = Depends(get_db)) -> dict:
    try:
        return ingest_metric(db, payload)
    except Exception as exc:  # pragma: no cover - defensive path
        logger.exception("Metric ingestion failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to ingest telemetry payload.") from exc


@app.get("/metrics", response_model=list[MetricRecord])
def get_metrics(
    limit: int = Query(default=50, ge=1, le=500),
    hours: int | None = Query(default=None, ge=1, le=168),
    db: Session = Depends(get_db),
) -> list[MetricRecord]:
    return fetch_metrics_history(db, limit=limit, hours=hours)


@app.get("/predict", response_model=PredictionResponse)
def get_prediction(db: Session = Depends(get_db)) -> PredictionResponse:
    recent_metrics = fetch_recent_metrics(db, settings.prediction_window)
    prediction, decision = assess_recent_metrics(recent_metrics)
    return PredictionResponse(
        predicted_cpu=prediction.predicted_cpu,
        anomaly=prediction.anomaly,
        health_score=prediction.health_score,
        severity=decision.severity,
        alert_message=decision.alert_message or prediction.alert_message,
        recommendation=decision.recommended_action,
        confidence=decision.confidence,
        explanation=f"{prediction.explanation} {decision.explanation}".strip(),
        trend=prediction.trend,
        model_version=prediction.model_version,
        window_size=prediction.window_size,
    )


@app.post("/remediate", response_model=RemediationResponse)
def remediate(request: RemediationRequest, db: Session = Depends(get_db)) -> RemediationResponse:
    metric = None
    if request.metric_id:
        metric = run_with_retry(
            lambda: db.query(Metrics).filter(Metrics.id == request.metric_id).first(),
            session=db,
        )
        if not metric:
            raise HTTPException(status_code=404, detail=f"Metric {request.metric_id} was not found.")
    elif request.action_type == "apply_recommendation":
        metric = run_with_retry(
            lambda: db.query(Metrics).order_by(Metrics.id.desc()).first(),
            session=db,
        )
        if not metric:
            raise HTTPException(status_code=404, detail="No metric sample is available for remediation.")

    def _execute_remediation():
        action = RemediationEngine(db).execute(
            action_type=request.action_type,
            metric=metric,
            requested_by=request.requested_by,
            requested_mode=request.mode,
            reason=request.reason,
            target_process=request.target_process,
            target_pid=request.target_pid,
            notes=request.notes,
        )
        db.commit()
        return action

    with WRITE_LOCK:
        action = run_with_retry(_execute_remediation, session=db)

    if metric:
        db.refresh(metric)
    db.refresh(action)

    return RemediationResponse(
        action=serialize_action(action),
        metric=serialize_metric(metric) if metric else None,
        simulated=action.mode != "live" or action.status == "simulated",
        safe_to_execute=action.mode != "live" or settings.allow_live_remediation,
    )


@app.get("/actions", response_model=list[ActionRecord])
def get_actions(
    limit: int = Query(default=settings.action_history_limit, ge=1, le=100),
    db: Session = Depends(get_db),
) -> list[ActionRecord]:
    actions = run_with_retry(
        lambda: db.query(RemediationAction).order_by(RemediationAction.id.desc()).limit(limit).all(),
        session=db,
    )
    return [serialize_action(action) for action in actions]


@app.get("/summary", response_model=SummaryResponse)
def get_summary(db: Session = Depends(get_db)) -> SummaryResponse:
    return build_summary(db)


@app.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    history_limit: int = Query(default=settings.dashboard_history_limit, ge=12, le=200),
    db: Session = Depends(get_db),
) -> DashboardResponse:
    now = time.time()
    with _dashboard_cache_lock:
        cached_payload = _dashboard_cache.get("payload")
        expires_at = float(_dashboard_cache.get("expires_at") or 0.0)
        if cached_payload is not None and now < expires_at:
            return cached_payload.model_copy(deep=True)

    summary = build_summary(db)
    metrics = fetch_metrics_history(db, limit=history_limit)
    actions = get_actions(limit=settings.action_history_limit, db=db)

    payload = DashboardResponse(
        generated_at=utcnow_iso(),
        summary=summary,
        metrics=list(reversed(metrics)),
        incidents=summary.active_alerts,
        actions=actions,
        advisor=build_advisor(summary),
        controls={
            "demo_mode": settings.demo_mode,
            "auto_remediation_enabled": settings.auto_remediation_enabled,
            "default_mode": settings.remediation_default_mode,
            "live_mode_supported": settings.allow_live_remediation,
            "api_base_url": settings.frontend_api_base_url,
        },
    )

    with _dashboard_cache_lock:
        _dashboard_cache["payload"] = payload
        _dashboard_cache["expires_at"] = now + _DASHBOARD_CACHE_SECONDS

    return payload


@app.get("/")
def root() -> dict:
    return {
        "name": settings.app_name,
        "status": "ready",
        "docs": "/docs",
        "frontend_api_base_url": settings.frontend_api_base_url,
    }
