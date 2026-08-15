from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.utils import clamp


class TopProcess(BaseModel):
    pid: int = Field(..., ge=0)
    name: str = Field(..., min_length=1, max_length=200)
    cpu_percent: float = Field(0.0, ge=0.0)
    memory_percent: float = Field(0.0, ge=0.0, le=100.0)
    memory_mb: float = Field(0.0, ge=0.0)
    runtime_minutes: float = Field(0.0, ge=0.0)
    read_mb: float = Field(0.0, ge=0.0)
    write_mb: float = Field(0.0, ge=0.0)
    status: str | None = Field(default=None, max_length=120)
    username: str | None = None


class MetricIngestRequest(BaseModel):
    cpu: float = Field(..., ge=0.0, le=100.0)
    memory: float = Field(..., ge=0.0, le=100.0)
    disk: float = Field(..., ge=0.0, le=100.0)
    load_average: float | None = Field(default=0.0, ge=0.0)
    process_count: int | None = Field(default=0, ge=0)
    hostname: str | None = Field(default=None, max_length=255)
    environment: str | None = Field(default=None, max_length=255)
    source: str | None = Field(default="agent", max_length=100)
    timestamp: str | None = None
    top_processes: list[TopProcess] = Field(default_factory=list)

    @field_validator("cpu", "memory", "disk", mode="before")
    @classmethod
    def _normalize_percent(cls, value: float | int) -> float:
        return round(clamp(float(value)), 2)


class TrendSummary(BaseModel):
    cpu_delta: float = 0.0
    memory_delta: float = 0.0
    disk_delta: float = 0.0
    cpu_direction: str = "stable"
    memory_direction: str = "stable"
    disk_direction: str = "stable"


class MetricRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    timestamp: str
    received_at: str | None = None
    cpu: float
    memory: float
    disk: float
    load_average: float | None = None
    process_count: int | None = None
    hostname: str | None = None
    environment: str | None = None
    source: str | None = None
    top_processes: list[TopProcess] = Field(default_factory=list)
    predicted_cpu: float | None = None
    anomaly_flag: bool = False
    health_score: float | None = None
    severity_level: str | None = None
    confidence_score: float | None = None
    trend_cpu: float | None = None
    trend_memory: float | None = None
    trend_disk: float | None = None
    alert_message: str | None = None
    recommended_action: str | None = None
    decision_explanation: str | None = None
    remediation_suggested: bool = False
    remediation_executed: bool = False
    remediation_notes: str | None = None
    action_taken: str | None = None
    action_status: str | None = None
    action_timestamp: str | None = None
    model_version: str | None = None
    metric_window_size: int | None = None
    ingestion_status: str | None = None


class PredictionResponse(BaseModel):
    predicted_cpu: float | None = None
    anomaly: bool = False
    health_score: float | None = None
    severity: str = "normal"
    alert_message: str | None = None
    recommendation: str | None = None
    confidence: float = 0.0
    explanation: str = ""
    trend: TrendSummary = Field(default_factory=TrendSummary)
    model_version: str | None = None
    window_size: int = 0


class RecommendationImpact(BaseModel):
    cpu_points: float = 0.0
    memory_mb: float = 0.0
    disk_mb: float = 0.0
    health_points: float = 0.0


class ProcessInsight(BaseModel):
    pid: int = Field(..., ge=0)
    name: str = Field(..., min_length=1, max_length=200)
    category: str = Field(default="background", max_length=120)
    business_impact: str = Field(default="medium", max_length=40)
    action_style: str = Field(default="review", max_length=40)
    cpu_percent: float = Field(0.0, ge=0.0)
    memory_percent: float = Field(0.0, ge=0.0, le=100.0)
    memory_mb: float = Field(0.0, ge=0.0)
    runtime_minutes: float = Field(0.0, ge=0.0)
    read_mb: float = Field(0.0, ge=0.0)
    write_mb: float = Field(0.0, ge=0.0)
    status: str | None = Field(default=None, max_length=120)
    attention_score: float = Field(0.0, ge=0.0)
    operator_hint: str = ""


class RecommendationRecord(BaseModel):
    id: str = Field(..., min_length=3, max_length=120)
    resource_type: Literal["cpu", "memory", "disk", "workflow"] = "workflow"
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    title: str = Field(..., min_length=3, max_length=200)
    summary: str = Field(..., min_length=3, max_length=500)
    target_name: str = Field(..., min_length=2, max_length=200)
    target_kind: str = Field(default="application", max_length=80)
    business_impact: Literal["low", "medium", "high"] = "medium"
    lane: str = Field(default="Optimize carefully", max_length=120)
    action_style: Literal["close", "trim", "pause", "clean", "review"] = "review"
    effort: str = Field(default="Quick win", max_length=120)
    evidence: list[str] = Field(default_factory=list)
    manual_steps: list[str] = Field(default_factory=list)
    rationale: str | None = Field(default=None, max_length=400)
    impact: RecommendationImpact = Field(default_factory=RecommendationImpact)


class ResourceProjection(BaseModel):
    cpu: float = Field(0.0, ge=0.0, le=100.0)
    memory: float = Field(0.0, ge=0.0, le=100.0)
    disk: float = Field(0.0, ge=0.0, le=100.0)
    health_score: float | None = Field(default=None, ge=0.0, le=100.0)


class ScenarioAction(BaseModel):
    recommendation_id: str = Field(..., min_length=3, max_length=120)
    title: str = Field(..., min_length=3, max_length=200)
    action_style: str = Field(default="review", max_length=40)
    resource_type: str = Field(default="workflow", max_length=40)


class WhatIfScenario(BaseModel):
    title: str = Field(default="Impact simulation", max_length=160)
    summary: str = Field(default="", max_length=500)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    before: ResourceProjection = Field(default_factory=ResourceProjection)
    after: ResourceProjection = Field(default_factory=ResourceProjection)
    estimated_gain: RecommendationImpact = Field(default_factory=RecommendationImpact)
    actions: list[ScenarioAction] = Field(default_factory=list)
    differentiator: str = Field(default="", max_length=300)


class AdvisorResponse(BaseModel):
    headline: str = Field(default="Waiting for telemetry", max_length=200)
    subheadline: str = Field(default="", max_length=400)
    differentiator_title: str = Field(default="Intent-aware advisor", max_length=160)
    differentiator_body: str = Field(default="", max_length=400)
    watchlist: list[ProcessInsight] = Field(default_factory=list)
    recommendations: list[RecommendationRecord] = Field(default_factory=list)
    what_if: WhatIfScenario = Field(default_factory=WhatIfScenario)


class IncidentRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    metric_id: int | None = None
    event_type: str
    severity: str
    status: str
    title: str
    message: str
    confidence_score: float | None = None
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ActionRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    metric_id: int | None = None
    requested_action: str
    action_type: str
    mode: str
    triggered_by: str
    severity: str
    status: str
    notes: str | None = None
    result_summary: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    completed_at: str | None = None


class RemediationRequest(BaseModel):
    action_type: Literal[
        "apply_recommendation",
        "inspect_top_processes",
        "lower_priority",
        "cleanup_temp",
        "restart_demo_service",
        "terminate_demo_process",
    ] = "apply_recommendation"
    mode: Literal["simulate", "dry-run", "live"] | None = None
    metric_id: int | None = Field(default=None, ge=1)
    requested_by: str = Field(default="operator", max_length=120)
    reason: str | None = Field(default=None, max_length=500)
    target_process: str | None = Field(default=None, max_length=255)
    target_pid: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=500)


class RemediationResponse(BaseModel):
    action: ActionRecord
    metric: MetricRecord | None = None
    simulated: bool = True
    safe_to_execute: bool = True


class SummaryResponse(BaseModel):
    generated_at: str
    current_metrics: MetricRecord | None = None
    trends: TrendSummary = Field(default_factory=TrendSummary)
    prediction: PredictionResponse = Field(default_factory=PredictionResponse)
    active_alerts: list[IncidentRecord] = Field(default_factory=list)
    last_action: ActionRecord | None = None
    system_health: str = "Collecting"
    live_connection: str = "degraded"
    remediation_mode: str = "simulate"
    auto_remediation_enabled: bool = False


class DashboardResponse(BaseModel):
    generated_at: str
    summary: SummaryResponse
    metrics: list[MetricRecord]
    incidents: list[IncidentRecord]
    actions: list[ActionRecord]
    advisor: AdvisorResponse = Field(default_factory=AdvisorResponse)
    controls: dict[str, Any]
