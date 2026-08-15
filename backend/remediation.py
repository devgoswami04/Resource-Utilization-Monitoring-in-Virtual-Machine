from __future__ import annotations

import psutil
import time
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import settings
from backend.logger import get_logger
from backend.models import IncidentEvent, Metrics, RemediationAction
from backend.utils import json_dumps, json_loads, utcnow_iso


logger = get_logger("backend.remediation")


@dataclass
class RemediationExecutionResult:
    status: str
    simulated: bool
    safe_to_execute: bool
    notes: str
    result_summary: str
    details: dict
    action_type: str
    mode: str


class RemediationEngine:
    def __init__(self, db: Session):
        self.db = db

    def _safe_mode(self, requested_mode: str | None) -> tuple[str, bool, bool]:
        mode = requested_mode or settings.remediation_default_mode
        safe_to_execute = mode != "live" or settings.allow_live_remediation
        simulated = mode != "live" or not safe_to_execute
        return mode, simulated, safe_to_execute

    def _top_processes(self, limit: int | None = None) -> list[dict]:
        # Batched attribute read (single oneshot() per process) keeps this fast
        # enough to run under the write lock without stalling the sampler.
        process_limit = limit or settings.top_process_limit
        processes: list[dict] = []
        snapshot_time = time.time()
        for proc in psutil.process_iter(
            ["pid", "name", "username", "cpu_percent", "memory_percent", "memory_info", "create_time"]
        ):
            try:
                info = proc.info
                memory_info = info.get("memory_info")
                create_time = info.get("create_time") or snapshot_time
                processes.append(
                    {
                        "pid": int(info.get("pid") or 0),
                        "name": str(info.get("name") or "unknown"),
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
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        processes.sort(key=lambda item: (item["cpu_percent"], item["memory_percent"]), reverse=True)
        return processes[:process_limit]

    def _is_process_allowed(self, process_name: str) -> bool:
        lowered = process_name.lower()
        if lowered in {name.lower() for name in settings.denied_processes}:
            return False
        return lowered in {name.lower() for name in settings.allowlisted_processes}

    def _cleanup_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        suffix_allowlist = {".tmp", ".cache", ".log"}
        for base_path in settings.cleanup_paths:
            base_path.mkdir(parents=True, exist_ok=True)
            for child in base_path.rglob("*"):
                if child.is_file() and child.suffix.lower() in suffix_allowlist:
                    candidates.append(child)
        return candidates[:50]

    def execute(
        self,
        *,
        action_type: str,
        metric: Metrics | None,
        requested_by: str,
        requested_mode: str | None,
        reason: str | None = None,
        target_process: str | None = None,
        target_pid: int | None = None,
        notes: str | None = None,
    ) -> RemediationAction:
        mode, simulated, safe_to_execute = self._safe_mode(requested_mode)
        resolved_action = action_type

        if action_type == "apply_recommendation":
            resolved_action = metric.recommended_action if metric and metric.recommended_action else "inspect_top_processes"

        logger.info(
            "Executing remediation action=%s mode=%s simulated=%s metric_id=%s",
            resolved_action,
            mode,
            simulated,
            getattr(metric, "id", None),
        )

        execution = self._run_action(
            action_type=resolved_action,
            metric=metric,
            mode=mode,
            simulated=simulated,
            safe_to_execute=safe_to_execute,
            target_process=target_process,
            target_pid=target_pid,
            reason=reason,
            notes=notes,
        )

        action_record = RemediationAction(
            metric_id=getattr(metric, "id", None),
            requested_action=action_type,
            action_type=execution.action_type,
            mode=execution.mode,
            triggered_by=requested_by,
            severity=getattr(metric, "severity_level", "normal") or "normal",
            status=execution.status,
            notes=execution.notes,
            result_summary=execution.result_summary,
            details_json=json_dumps(execution.details),
            created_at=utcnow_iso(),
            completed_at=utcnow_iso(),
        )
        self.db.add(action_record)
        self.db.flush()

        if metric:
            metric.remediation_suggested = True
            metric.remediation_executed = execution.status in {"completed", "simulated"}
            metric.remediation_notes = execution.notes
            metric.action_taken = execution.action_type
            metric.action_status = execution.status
            metric.action_timestamp = action_record.completed_at

        incident = IncidentEvent(
            metric_id=getattr(metric, "id", None),
            event_type="remediation",
            severity=getattr(metric, "severity_level", "normal") or "normal",
            status="open" if execution.status in {"failed", "blocked"} else "resolved",
            title=f"Remediation {execution.action_type}",
            message=execution.result_summary,
            confidence_score=getattr(metric, "confidence_score", None),
            created_at=utcnow_iso(),
            metadata_json=json_dumps(execution.details),
        )
        self.db.add(incident)

        return action_record

    def _run_action(
        self,
        *,
        action_type: str,
        metric: Metrics | None,
        mode: str,
        simulated: bool,
        safe_to_execute: bool,
        target_process: str | None,
        target_pid: int | None,
        reason: str | None,
        notes: str | None,
    ) -> RemediationExecutionResult:
        if action_type == "cleanup_temp":
            candidates = self._cleanup_candidates()
            if simulated or not safe_to_execute:
                status = "simulated" if simulated else "blocked"
                return RemediationExecutionResult(
                    status=status,
                    simulated=simulated,
                    safe_to_execute=safe_to_execute,
                    notes=notes or "Temporary-file cleanup prepared in safe mode only.",
                    result_summary=f"Identified {len(candidates)} cleanup candidates without deleting files.",
                    details={"candidates": [str(path) for path in candidates], "reason": reason},
                    action_type=action_type,
                    mode=mode,
                )

            removed: list[str] = []
            for path in candidates:
                try:
                    path.unlink(missing_ok=True)
                    removed.append(str(path))
                except OSError:
                    continue
            return RemediationExecutionResult(
                status="completed",
                simulated=False,
                safe_to_execute=True,
                notes=notes or "Safe cleanup completed on allowlisted demo paths.",
                result_summary=f"Removed {len(removed)} temporary artifacts from allowlisted paths.",
                details={"removed": removed, "reason": reason},
                action_type=action_type,
                mode=mode,
            )

        if action_type in {"inspect_top_processes", "observe"}:
            offenders = self._top_processes()
            return RemediationExecutionResult(
                status="completed" if action_type == "inspect_top_processes" else "simulated",
                simulated=action_type == "observe",
                safe_to_execute=True,
                notes=notes or "Captured the top process offenders for operator review.",
                result_summary="Collected process-level offenders to explain the spike.",
                details={"top_processes": offenders, "reason": reason},
                action_type="inspect_top_processes",
                mode=mode,
            )

        if action_type == "restart_demo_service":
            return RemediationExecutionResult(
                status="simulated",
                simulated=True,
                safe_to_execute=False,
                notes=notes or "Service restart stays simulated unless a demo service hook is configured.",
                result_summary="Restart request was recorded in simulation mode.",
                details={"reason": reason},
                action_type=action_type,
                mode=mode,
            )

        if action_type in {"lower_priority", "terminate_demo_process"}:
            offenders = self._top_processes(limit=10)
            chosen = None
            for offender in offenders:
                if target_pid and offender["pid"] == target_pid:
                    chosen = offender
                    break
                if target_process and offender["name"].lower() == target_process.lower():
                    chosen = offender
                    break
                if self._is_process_allowed(offender["name"]):
                    chosen = offender
                    break

            if not chosen:
                return RemediationExecutionResult(
                    status="blocked",
                    simulated=True,
                    safe_to_execute=False,
                    notes=notes or "No allowlisted demo process matched the request.",
                    result_summary="Remediation was blocked because no safe process target was available.",
                    details={"top_processes": offenders, "reason": reason},
                    action_type=action_type,
                    mode=mode,
                )

            if action_type == "terminate_demo_process" and chosen["name"].lower() not in {
                name.lower() for name in settings.demo_terminatable_processes
            }:
                return RemediationExecutionResult(
                    status="blocked",
                    simulated=True,
                    safe_to_execute=False,
                    notes=notes or "Termination is limited to explicitly allowlisted demo processes.",
                    result_summary=f"Termination for {chosen['name']} was blocked by the safety gate.",
                    details={"target": chosen, "reason": reason},
                    action_type=action_type,
                    mode=mode,
                )

            if simulated or not safe_to_execute:
                status = "simulated" if simulated else "blocked"
                return RemediationExecutionResult(
                    status=status,
                    simulated=simulated,
                    safe_to_execute=safe_to_execute,
                    notes=notes or "The action stayed in safe mode and did not mutate the target process.",
                    result_summary=f"Prepared a {action_type} action for {chosen['name']} without executing it.",
                    details={"target": chosen, "reason": reason},
                    action_type=action_type,
                    mode=mode,
                )

            process = psutil.Process(chosen["pid"])
            if action_type == "lower_priority":
                if hasattr(psutil, "BELOW_NORMAL_PRIORITY_CLASS"):
                    process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
                else:
                    process.nice(10)
                summary = f"Lowered priority for {chosen['name']} (pid {chosen['pid']})."
            else:
                process.terminate()
                summary = f"Sent terminate signal to {chosen['name']} (pid {chosen['pid']})."

            return RemediationExecutionResult(
                status="completed",
                simulated=False,
                safe_to_execute=True,
                notes=notes or "Live demo remediation completed on an allowlisted process.",
                result_summary=summary,
                details={"target": chosen, "reason": reason},
                action_type=action_type,
                mode=mode,
            )

        return RemediationExecutionResult(
            status="blocked",
            simulated=True,
            safe_to_execute=False,
            notes=notes or "Unknown remediation action.",
            result_summary=f"The action '{action_type}' is not implemented by the remediation engine.",
            details={"reason": reason},
            action_type=action_type,
            mode=mode,
        )


def action_details(action: RemediationAction) -> dict:
    return json_loads(action.details_json, {})
