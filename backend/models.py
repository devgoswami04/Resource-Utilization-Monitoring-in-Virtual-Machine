from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.database import Base


class Metrics(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(String, index=True, nullable=False)
    received_at = Column(String, nullable=True)
    cpu = Column(Float, nullable=False)
    memory = Column(Float, nullable=False)
    disk = Column(Float, nullable=False)
    load_average = Column(Float, nullable=True)
    process_count = Column(Integer, nullable=True)
    hostname = Column(String, nullable=True)
    environment = Column(String, nullable=True)
    source = Column(String, nullable=True)
    top_processes_json = Column(Text, nullable=True)
    predicted_cpu = Column(Float, nullable=True)
    anomaly_flag = Column(Boolean, default=False, nullable=True)
    health_score = Column(Float, nullable=True)
    severity_level = Column(String, nullable=True)
    confidence_score = Column(Float, nullable=True)
    trend_cpu = Column(Float, nullable=True)
    trend_memory = Column(Float, nullable=True)
    trend_disk = Column(Float, nullable=True)
    alert_message = Column(Text, nullable=True)
    recommended_action = Column(String, nullable=True)
    decision_explanation = Column(Text, nullable=True)
    remediation_suggested = Column(Boolean, default=False, nullable=True)
    remediation_executed = Column(Boolean, default=False, nullable=True)
    remediation_notes = Column(Text, nullable=True)
    action_taken = Column(String, nullable=True)
    action_status = Column(String, nullable=True)
    action_timestamp = Column(String, nullable=True)
    model_version = Column(String, nullable=True)
    metric_window_size = Column(Integer, nullable=True)
    ingestion_status = Column(String, nullable=True)

    incidents = relationship("IncidentEvent", back_populates="metric", cascade="all, delete-orphan")
    actions = relationship("RemediationAction", back_populates="metric")


class IncidentEvent(Base):
    __tablename__ = "incident_events"

    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=True)
    event_type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="normal")
    status = Column(String, nullable=False, default="open")
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    confidence_score = Column(Float, nullable=True)
    created_at = Column(String, nullable=False)
    metadata_json = Column(Text, nullable=True)

    metric = relationship("Metrics", back_populates="incidents")


class RemediationAction(Base):
    __tablename__ = "remediation_actions"

    id = Column(Integer, primary_key=True, index=True)
    metric_id = Column(Integer, ForeignKey("metrics.id"), nullable=True)
    requested_action = Column(String, nullable=False)
    action_type = Column(String, nullable=False)
    mode = Column(String, nullable=False)
    triggered_by = Column(String, nullable=False, default="system")
    severity = Column(String, nullable=False, default="normal")
    status = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)
    details_json = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)
    completed_at = Column(String, nullable=True)

    metric = relationship("Metrics", back_populates="actions")
