from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

import psutil

from backend.config import ROOT_DIR, settings
from backend.logger import get_logger
from backend.schemas import (
    AdvisorResponse,
    MetricRecord,
    ProcessInsight,
    RecommendationImpact,
    RecommendationRecord,
    ResourceProjection,
    ScenarioAction,
    SummaryResponse,
    TopProcess,
    WhatIfScenario,
)
from backend.utils import clamp, normalize_confidence, safe_round


logger = get_logger("backend.advisor")

_STORAGE_CACHE_SECONDS = 90.0
_storage_cache: dict[str, object] = {"expires_at": 0.0, "targets": []}
_storage_lock = Lock()


@dataclass(frozen=True)
class ProcessProfile:
    category: str
    business_impact: str
    lane: str
    action_style: str
    operator_hint: str
    steps: tuple[str, ...]


@dataclass(frozen=True)
class StorageProfile:
    key: str
    label: str
    target_kind: str
    lane: str
    effort: str
    action_style: str
    sources: tuple[Path, ...]
    manual_steps: tuple[str, ...]


SYSTEM_PROFILE = ProcessProfile(
    category="system",
    business_impact="high",
    lane="Protected workload",
    action_style="review",
    operator_hint="Avoid closing protected system services directly.",
    steps=(
        "Leave the protected process running.",
        "Reduce pressure around it by trimming optional apps first.",
        "Investigate only if it stays elevated for multiple refresh cycles.",
    ),
)

DEFAULT_PROFILE = ProcessProfile(
    category="background",
    business_impact="medium",
    lane="Optimize carefully",
    action_style="review",
    operator_hint="Check whether this app is still needed before closing it.",
    steps=(
        "Confirm the app is not supporting an active task.",
        "Close idle windows or stop the background task.",
        "Watch the next refresh cycle to confirm the drop.",
    ),
)

PROFILE_MAP: tuple[tuple[tuple[str, ...], ProcessProfile], ...] = (
    (
        ("chrome", "msedge", "firefox", "opera", "brave"),
        ProcessProfile(
            category="browser",
            business_impact="high",
            lane="Protect workflow",
            action_style="trim",
            operator_hint="Trim unused tabs and extensions before considering a full close.",
            steps=(
                "Close unused tabs, especially video, AI, and streaming tabs.",
                "Disable heavy extensions or suspend inactive tabs.",
                "Keep the browser open only for the work items you still need.",
            ),
        ),
    ),
    (
        ("spotify", "discord", "steam", "epicgames", "vlc", "music", "netflix", "itunes"),
        ProcessProfile(
            category="entertainment",
            business_impact="low",
            lane="Fast reclaim",
            action_style="close",
            operator_hint="Low-risk candidate if you are not actively using it.",
            steps=(
                "Pause the current session if needed.",
                "Exit the app completely from the taskbar or tray.",
                "Check the next refresh to confirm reclaimed headroom.",
            ),
        ),
    ),
    (
        ("onedrive", "dropbox", "googledrive", "googledrivesync", "creative cloud", "ccxprocess"),
        ProcessProfile(
            category="sync",
            business_impact="medium",
            lane="Pause background work",
            action_style="pause",
            operator_hint="Background sync can usually be paused during heavy work.",
            steps=(
                "Pause sync or backup temporarily.",
                "Finish the heavy task or demo sequence first.",
                "Resume sync once the system returns to a healthy band.",
            ),
        ),
    ),
    (
        ("teams", "zoom", "slack", "telegram", "whatsapp", "skype"),
        ProcessProfile(
            category="collaboration",
            business_impact="medium",
            lane="Close when idle",
            action_style="review",
            operator_hint="Useful during meetings, but often safe to close after the session ends.",
            steps=(
                "Check whether a meeting, call, or chat session is still active.",
                "Close the app if it is only sitting idle in the background.",
                "Reopen it later if communication needs resume.",
            ),
        ),
    ),
    (
        ("code", "pycharm", "idea64", "webstorm", "studio64", "docker", "devenv", "powershell", "cmd"),
        ProcessProfile(
            category="development",
            business_impact="high",
            lane="Protect workflow",
            action_style="review",
            operator_hint="Treat development tools as protected unless the workload is clearly idle.",
            steps=(
                "Shut down unused terminals, containers, or extra IDE windows.",
                "Finish the active task before closing the main tool.",
                "Prefer trimming side workloads instead of quitting the core tool.",
            ),
        ),
    ),
)

SYSTEM_KEYWORDS = (
    "audiodg",
    "antimalware",
    "dwm",
    "runtimebroker",
    "msmpeng",
    "securityhealth",
    "search",
    "taskhost",
    "conhost",
    "rundll32",
    "textinputhost",
    "widgets",
    "wudfhost",
    "lockapp",
    "shellexperiencehost",
    "startmenu",
    "explorer",
)


def _friendly_name(name: str) -> str:
    stem = name.strip()
    if stem.lower().endswith(".exe"):
        stem = stem[:-4]
    if not stem:
        return "Unknown app"
    return stem[:1].upper() + stem[1:]


def _impact_penalty(level: str) -> float:
    return {"low": 0.0, "medium": 7.0, "high": 15.0}.get(level, 7.0)


def _classify_process(name: str) -> ProcessProfile:
    lowered = name.lower()
    denied = {item.lower() for item in settings.denied_processes}
    if lowered in denied or any(keyword in lowered for keyword in SYSTEM_KEYWORDS):
        return SYSTEM_PROFILE

    for keywords, profile in PROFILE_MAP:
        if any(keyword in lowered for keyword in keywords):
            return profile
    return DEFAULT_PROFILE


def _process_to_dict(process: TopProcess | dict) -> dict:
    if isinstance(process, dict):
        return process
    return process.model_dump()


def _hydrate_process(process: dict) -> dict:
    pid = int(process.get("pid") or 0)
    if not pid:
        return process

    try:
        live_process = psutil.Process(pid)
        if float(process.get("memory_percent") or 0.0) <= 0.0:
            process["memory_percent"] = round(float(live_process.memory_percent()), 2)
        if float(process.get("memory_mb") or 0.0) <= 0.0:
            process["memory_mb"] = round(float(live_process.memory_info().rss) / (1024 * 1024), 2)
        if float(process.get("runtime_minutes") or 0.0) <= 0.0:
            process["runtime_minutes"] = round(max(time.time() - live_process.create_time(), 0.0) / 60.0, 1)
        if float(process.get("read_mb") or 0.0) <= 0.0 or float(process.get("write_mb") or 0.0) <= 0.0:
            io_counters = live_process.io_counters() if hasattr(live_process, "io_counters") else None
            process["read_mb"] = round(float(getattr(io_counters, "read_bytes", 0.0)) / (1024 * 1024), 2)
            process["write_mb"] = round(float(getattr(io_counters, "write_bytes", 0.0)) / (1024 * 1024), 2)
        if not process.get("status"):
            process["status"] = live_process.status()
        if not process.get("name"):
            process["name"] = live_process.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return process

    return process


def _attention_score(process: dict, profile: ProcessProfile) -> float:
    cpu_percent = float(process.get("cpu_percent") or 0.0)
    memory_percent = float(process.get("memory_percent") or 0.0)
    memory_mb = float(process.get("memory_mb") or 0.0)
    runtime_minutes = float(process.get("runtime_minutes") or 0.0)
    read_mb = float(process.get("read_mb") or 0.0)
    write_mb = float(process.get("write_mb") or 0.0)

    score = (
        (cpu_percent * 1.8)
        + (memory_percent * 1.25)
        + min(memory_mb / 48.0, 22.0)
        + min(runtime_minutes / 30.0, 12.0)
        + min((read_mb + write_mb) / 128.0, 8.0)
    )

    if runtime_minutes >= 120 and cpu_percent < 2.0:
        score += 6.0
    if profile.business_impact == "low":
        score += 10.0
    if profile.action_style == "trim":
        score += 3.0

    score -= _impact_penalty(profile.business_impact)
    return round(max(score, 0.0), 2)


def _priority_from_score(score: float, severity: str) -> str:
    if score >= 48 or severity == "emergency":
        return "critical"
    if score >= 34 or severity == "critical":
        return "high"
    if score >= 22 or severity == "warning":
        return "medium"
    return "low"


def _confidence_from_process(process: dict, profile: ProcessProfile) -> float:
    cpu_percent = float(process.get("cpu_percent") or 0.0)
    memory_percent = float(process.get("memory_percent") or 0.0)
    runtime_minutes = float(process.get("runtime_minutes") or 0.0)
    raw = 0.42 + (cpu_percent / 180.0) + (memory_percent / 240.0) + min(runtime_minutes / 600.0, 0.12)
    if profile.business_impact == "low":
        raw += 0.08
    return round(normalize_confidence(raw), 3)


def _action_title(name: str, resource_type: str, profile: ProcessProfile) -> str:
    if resource_type == "disk":
        return f"Clean {name} to free disk space"
    if resource_type == "workflow":
        if profile.action_style == "close":
            return f"Close {name} to recover headroom"
        if profile.action_style == "trim":
            return f"Trim {name} background activity"
        if profile.action_style == "pause":
            return f"Pause {name} while the workload peaks"
        return f"Review {name} for idle background use"
    if profile.action_style == "close":
        return f"Close {name} to reclaim {resource_type}"
    if profile.action_style == "trim":
        return f"Trim {name} activity before closing it"
    if profile.action_style == "pause":
        return f"Pause {name} background work"
    return f"Review {name} before ending it"


def _action_summary(name: str, resource_type: str, process: dict, profile: ProcessProfile) -> str:
    cpu_percent = float(process.get("cpu_percent") or 0.0)
    memory_mb = float(process.get("memory_mb") or 0.0)
    runtime_minutes = float(process.get("runtime_minutes") or 0.0)

    if resource_type == "cpu":
        return (
            f"{name} is a leading CPU contributor right now and has been active for "
            f"{runtime_minutes:.0f} minutes."
        )
    if resource_type == "memory":
        return (
            f"{name} is holding roughly {memory_mb:.0f} MB of memory, which makes it a useful manual cleanup target."
        )
    return (
        f"{name} is open for long periods with light recent activity, so it is a good low-risk optimization candidate."
    )


def _action_effort(profile: ProcessProfile, resource_type: str) -> str:
    if resource_type == "disk":
        return "Guided cleanup"
    if profile.action_style in {"close", "pause"}:
        return "Quick win"
    if profile.action_style == "trim":
        return "Targeted cleanup"
    return "Operator review"


def _build_enriched_processes(processes: list[TopProcess]) -> list[dict]:
    enriched: list[dict] = []
    for raw_process in processes:
        process = _hydrate_process(_process_to_dict(raw_process))
        profile = _classify_process(str(process.get("name") or "unknown"))
        process["profile"] = profile
        process["friendly_name"] = _friendly_name(str(process.get("name") or "unknown"))
        process["attention_score"] = _attention_score(process, profile)
        enriched.append(process)

    enriched.sort(key=lambda item: item["attention_score"], reverse=True)
    return enriched


def _collect_live_processes(limit: int = 8) -> list[dict]:
    snapshot_time = time.time()
    processes: list[dict] = []

    for process in psutil.process_iter(["pid", "name", "username"]):
        try:
            info = process.info
            process_name = str(info.get("name") or "unknown")
            if int(info.get("pid") or 0) == 0 or process_name.lower() == "system idle process":
                continue

            memory_info = process.memory_info()
            io_counters = process.io_counters() if hasattr(process, "io_counters") else None
            processes.append(
                {
                    "pid": int(info.get("pid") or 0),
                    "name": process_name,
                    "cpu_percent": round(float(process.cpu_percent(interval=None) or 0.0), 2),
                    "memory_percent": round(float(process.memory_percent() or 0.0), 2),
                    "memory_mb": round(float(memory_info.rss) / (1024 * 1024), 2),
                    "runtime_minutes": round(max(snapshot_time - process.create_time(), 0.0) / 60.0, 1),
                    "read_mb": round(float(getattr(io_counters, "read_bytes", 0.0)) / (1024 * 1024), 2),
                    "write_mb": round(float(getattr(io_counters, "write_bytes", 0.0)) / (1024 * 1024), 2),
                    "status": process.status(),
                    "username": info.get("username"),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, PermissionError, OSError):
            continue

    processes.sort(
        key=lambda item: (
            float(item.get("cpu_percent") or 0.0),
            float(item.get("memory_mb") or 0.0),
            float(item.get("memory_percent") or 0.0),
        ),
        reverse=True,
    )
    return processes[:limit]


def _merge_process_sources(primary: list[dict], fallback: list[dict]) -> list[dict]:
    merged: dict[int, dict] = {}
    for process in [*primary, *fallback]:
        pid = int(process.get("pid") or 0)
        if not pid:
            continue
        existing = merged.get(pid)
        if not existing or float(process.get("attention_score") or 0.0) > float(existing.get("attention_score") or 0.0):
            merged[pid] = process
    values = list(merged.values())
    values.sort(key=lambda item: float(item.get("attention_score") or 0.0), reverse=True)
    return values


def _build_watchlist(processes: list[dict]) -> list[ProcessInsight]:
    watchlist: list[ProcessInsight] = []
    for process in processes[:6]:
        profile: ProcessProfile = process["profile"]
        watchlist.append(
            ProcessInsight(
                pid=int(process.get("pid") or 0),
                name=process["friendly_name"],
                category=profile.category,
                business_impact=profile.business_impact,
                action_style=profile.action_style,
                cpu_percent=round(float(process.get("cpu_percent") or 0.0), 2),
                memory_percent=round(float(process.get("memory_percent") or 0.0), 2),
                memory_mb=round(float(process.get("memory_mb") or 0.0), 2),
                runtime_minutes=round(float(process.get("runtime_minutes") or 0.0), 1),
                read_mb=round(float(process.get("read_mb") or 0.0), 2),
                write_mb=round(float(process.get("write_mb") or 0.0), 2),
                status=process.get("status"),
                attention_score=round(float(process.get("attention_score") or 0.0), 2),
                operator_hint=profile.operator_hint,
            )
        )
    return watchlist


def _resource_type_for_process(process: dict) -> str:
    cpu_weight = float(process.get("cpu_percent") or 0.0) * 1.6
    memory_weight = (float(process.get("memory_mb") or 0.0) / 42.0) + (float(process.get("memory_percent") or 0.0) * 1.8)
    runtime_weight = float(process.get("runtime_minutes") or 0.0) / 20.0
    if cpu_weight >= memory_weight and cpu_weight >= runtime_weight:
        return "cpu"
    if memory_weight >= runtime_weight:
        return "memory"
    return "workflow"


def _projected_impact(process: dict, resource_type: str, profile: ProcessProfile) -> RecommendationImpact:
    cpu_percent = float(process.get("cpu_percent") or 0.0)
    memory_mb = float(process.get("memory_mb") or 0.0)
    reclaim_factor = {
        "close": (0.84, 0.82),
        "pause": (0.68, 0.52),
        "trim": (0.48, 0.32),
        "review": (0.24, 0.22),
    }.get(profile.action_style, (0.24, 0.22))

    projected_cpu = cpu_percent * reclaim_factor[0] if resource_type in {"cpu", "workflow"} else cpu_percent * 0.18
    projected_memory = memory_mb * reclaim_factor[1]
    health_gain = (projected_cpu * 0.55) + ((projected_memory / 1024.0) * 7.0)

    return RecommendationImpact(
        cpu_points=round(max(projected_cpu, 0.0), 1),
        memory_mb=round(max(projected_memory, 0.0), 1),
        disk_mb=0.0,
        health_points=round(max(health_gain, 0.0), 1),
    )


def _process_evidence(process: dict, resource_type: str) -> list[str]:
    evidence = [
        f"CPU: {float(process.get('cpu_percent') or 0.0):.1f}%",
        f"Memory: {float(process.get('memory_mb') or 0.0):.0f} MB",
        f"Runtime: {float(process.get('runtime_minutes') or 0.0):.0f} min",
    ]
    status = process.get("status")
    if status:
        evidence.append(f"Status: {status}")

    if resource_type == "workflow":
        evidence.append("Low recent activity compared with how long it has been open")
    return evidence


def _build_process_recommendations(current: MetricRecord, processes: list[dict]) -> list[RecommendationRecord]:
    recommendations: list[RecommendationRecord] = []

    for process in processes:
        profile: ProcessProfile = process["profile"]
        if profile.category == "system":
            continue

        resource_type = _resource_type_for_process(process)
        score = float(process.get("attention_score") or 0.0)
        cpu_percent = float(process.get("cpu_percent") or 0.0)
        memory_mb = float(process.get("memory_mb") or 0.0)
        runtime_minutes = float(process.get("runtime_minutes") or 0.0)

        if score < 18 and not (profile.business_impact == "low" and runtime_minutes >= 90 and memory_mb >= 140):
            continue
        if resource_type == "cpu" and cpu_percent < 3.0 and current.cpu < 65:
            continue
        if resource_type == "memory" and memory_mb < 180 and current.memory < 65:
            continue

        name = process["friendly_name"]
        impact = _projected_impact(process, resource_type, profile)
        recommendations.append(
            RecommendationRecord(
                id=f"{resource_type}-{int(process.get('pid') or 0)}",
                resource_type=resource_type,
                priority=_priority_from_score(score, current.severity_level or "normal"),
                confidence=_confidence_from_process(process, profile),
                title=_action_title(name, resource_type, profile),
                summary=_action_summary(name, resource_type, process, profile),
                target_name=name,
                target_kind="application",
                business_impact=profile.business_impact,
                lane=profile.lane,
                action_style=profile.action_style,
                effort=_action_effort(profile, resource_type),
                evidence=_process_evidence(process, resource_type),
                manual_steps=list(profile.steps),
                rationale=profile.operator_hint,
                impact=impact,
            )
        )

    recommendations.sort(
        key=lambda item: (
            {"critical": 3, "high": 2, "medium": 1, "low": 0}[item.priority],
            item.impact.cpu_points + (item.impact.memory_mb / 256.0),
            item.confidence,
        ),
        reverse=True,
    )
    return recommendations[:4]


def _directory_size_mb(path: Path, *, max_depth: int = 5, max_files: int = 9000) -> float:
    if not path.exists() or not path.is_dir():
        return 0.0

    total_size = 0
    visited = 0
    stack: list[tuple[Path, int]] = [(path, 0)]

    while stack and visited < max_files:
        current_path, depth = stack.pop()
        if depth > max_depth:
            continue

        try:
            entries = os.scandir(current_path)
        except OSError:
            continue

        with entries:
            for entry in entries:
                if visited >= max_files:
                    break
                try:
                    if entry.is_symlink():
                        continue
                    if entry.is_file():
                        total_size += entry.stat().st_size
                        visited += 1
                    elif entry.is_dir():
                        stack.append((Path(entry.path), depth + 1))
                except OSError:
                    continue

    return round(total_size / (1024 * 1024), 2)


def _top_level_large_downloads(path: Path, minimum_mb: float = 150.0) -> dict | None:
    if not path.exists() or not path.is_dir():
        return None

    large_files = 0
    total_size = 0
    try:
        entries = os.scandir(path)
    except OSError:
        return None

    with entries:
        for entry in entries:
            try:
                if not entry.is_file():
                    continue
                size_mb = entry.stat().st_size / (1024 * 1024)
                if size_mb >= minimum_mb:
                    large_files += 1
                    total_size += size_mb
            except OSError:
                continue

    if not large_files:
        return None

    return {
        "id": "large-downloads",
        "label": "Large downloads",
        "target_kind": "downloads",
        "lane": "Archive or move",
        "effort": "Guided cleanup",
        "action_style": "clean",
        "size_mb": round(total_size, 1),
        "manual_steps": [
            "Review large installers, videos, or archives in Downloads.",
            "Move the files you still need to external or long-term storage.",
            "Delete only the items you no longer need and refresh the dashboard.",
        ],
        "evidence": [f"{large_files} large top-level files are occupying {total_size:.0f} MB in Downloads"],
        "target_name": "Downloads",
    }


def _storage_profiles() -> list[StorageProfile]:
    home = Path.home()
    local_appdata = Path(os.getenv("LOCALAPPDATA", home))
    temp_path = Path(tempfile.gettempdir())

    return [
        StorageProfile(
            key="temp-files",
            label="Temporary files",
            target_kind="temporary files",
            lane="Safe disk reclaim",
            effort="Quick win",
            action_style="clean",
            sources=(temp_path, ROOT_DIR / "backend" / "demo_temp"),
            manual_steps=(
                "Review temporary files and close apps that may still be using them.",
                "Clear temp artifacts that are no longer needed.",
                "Refresh the dashboard to verify the freed space.",
            ),
        ),
        StorageProfile(
            key="chrome-cache",
            label="Chrome cache",
            target_kind="browser cache",
            lane="Browser cleanup",
            effort="Guided cleanup",
            action_style="clean",
            sources=(local_appdata / "Google" / "Chrome" / "User Data" / "Default" / "Cache",),
            manual_steps=(
                "Close inactive Chrome tabs first.",
                "Use the browser's clear browsing data flow to remove cached files.",
                "Keep cookies and saved sessions if they are still needed for the demo.",
            ),
        ),
        StorageProfile(
            key="edge-cache",
            label="Edge cache",
            target_kind="browser cache",
            lane="Browser cleanup",
            effort="Guided cleanup",
            action_style="clean",
            sources=(local_appdata / "Microsoft" / "Edge" / "User Data" / "Default" / "Cache",),
            manual_steps=(
                "Close inactive Edge tabs first.",
                "Clear cached files from the browser settings page.",
                "Avoid removing passwords or active session data unless you intend to.",
            ),
        ),
    ]


def _collect_storage_targets() -> list[dict]:
    now = time.time()
    with _storage_lock:
        cached_targets = _storage_cache.get("targets", [])
        expires_at = float(_storage_cache.get("expires_at") or 0.0)
        if cached_targets and now < expires_at:
            return list(cached_targets)

        targets: list[dict] = []
        for profile in _storage_profiles():
            size_mb = sum(_directory_size_mb(path) for path in profile.sources)
            if size_mb < 120:
                continue
            targets.append(
                {
                    "id": profile.key,
                    "label": profile.label,
                    "target_kind": profile.target_kind,
                    "lane": profile.lane,
                    "effort": profile.effort,
                    "action_style": profile.action_style,
                    "size_mb": round(size_mb, 1),
                    "manual_steps": list(profile.manual_steps),
                    "evidence": [f"Current footprint: {size_mb:.0f} MB"],
                    "target_name": profile.label,
                }
            )

        downloads_target = _top_level_large_downloads(Path.home() / "Downloads")
        if downloads_target:
            targets.append(downloads_target)

        targets.sort(key=lambda item: float(item["size_mb"]), reverse=True)
        _storage_cache["targets"] = list(targets)
        _storage_cache["expires_at"] = now + _STORAGE_CACHE_SECONDS
        return targets


def _build_disk_recommendations(current: MetricRecord) -> list[RecommendationRecord]:
    recommendations: list[RecommendationRecord] = []
    disk_pressure = float(current.disk or 0.0)

    for target in _collect_storage_targets()[:3]:
        size_mb = float(target["size_mb"])
        projected_disk = size_mb * 0.88
        health_gain = min(12.0, projected_disk / 256.0)
        confidence = normalize_confidence(0.62 + min(size_mb / 4096.0, 0.22))

        if size_mb < 120 and disk_pressure < 72:
            continue

        priority = "high" if disk_pressure >= 88 or size_mb >= 1024 else "medium"
        recommendations.append(
            RecommendationRecord(
                id=str(target["id"]),
                resource_type="disk",
                priority=priority,
                confidence=round(confidence, 3),
                title=_action_title(str(target["label"]), "disk", DEFAULT_PROFILE),
                summary=f"{target['label']} currently accounts for about {size_mb:.0f} MB of reclaimable local storage.",
                target_name=str(target["target_name"]),
                target_kind=str(target["target_kind"]),
                business_impact="low",
                lane=str(target["lane"]),
                action_style="clean",
                effort=str(target["effort"]),
                evidence=list(target["evidence"]),
                manual_steps=list(target["manual_steps"]),
                rationale="This recommendation focuses on removable cache or transient storage rather than installed software.",
                impact=RecommendationImpact(
                    cpu_points=0.0,
                    memory_mb=0.0,
                    disk_mb=round(projected_disk, 1),
                    health_points=round(health_gain, 1),
                ),
            )
        )

    return recommendations


def _fallback_recommendation(current: MetricRecord) -> RecommendationRecord:
    evidence = [
        f"CPU currently at {float(current.cpu or 0.0):.1f}%",
        f"Memory currently at {float(current.memory or 0.0):.1f}%",
        f"Disk currently at {float(current.disk or 0.0):.1f}%",
    ]
    if current.decision_explanation:
        evidence.append(current.decision_explanation[:180])

    return RecommendationRecord(
        id="baseline-review",
        resource_type="workflow",
        priority="low",
        confidence=0.58,
        title="Keep optional background apps minimal during peak work",
        summary="No single user application dominates the system right now, so the best move is to keep non-essential apps and extra tabs to a minimum.",
        target_name="System baseline",
        target_kind="operating context",
        business_impact="medium",
        lane="Stable posture",
        action_style="review",
        effort="30-second check",
        evidence=evidence,
        manual_steps=[
            "Close optional entertainment or launcher apps you do not need for the task.",
            "Reduce extra browser tabs before starting the demo or heavy workload.",
            "Refresh once more and watch whether the trend lines flatten.",
        ],
        rationale="This fallback appears only when the advisor does not find a stronger real-time offender.",
        impact=RecommendationImpact(cpu_points=2.0, memory_mb=128.0, disk_mb=0.0, health_points=1.8),
    )


def _build_what_if(current: MetricRecord, recommendations: list[RecommendationRecord]) -> WhatIfScenario:
    top_actions = recommendations[:3]
    before = ResourceProjection(
        cpu=round(float(current.cpu or 0.0), 1),
        memory=round(float(current.memory or 0.0), 1),
        disk=round(float(current.disk or 0.0), 1),
        health_score=safe_round(current.health_score),
    )

    if not top_actions:
        return WhatIfScenario(
            title="Impact simulation",
            summary="Waiting for enough advice signals to build a scenario.",
            confidence=0.0,
            before=before,
            after=before,
            estimated_gain=RecommendationImpact(),
            actions=[],
            differentiator="The simulation will appear once the advisor has at least one high-signal recommendation.",
        )

    memory_total_mb = max(psutil.virtual_memory().total / (1024 * 1024), 1.0)
    disk_total_mb = max(psutil.disk_usage(Path.cwd().anchor or "/").total / (1024 * 1024), 1.0)

    cpu_gain = sum(action.impact.cpu_points for action in top_actions)
    memory_gain_mb = sum(action.impact.memory_mb for action in top_actions)
    disk_gain_mb = sum(action.impact.disk_mb for action in top_actions)
    health_gain = sum(action.impact.health_points for action in top_actions)

    after = ResourceProjection(
        cpu=round(clamp(before.cpu - cpu_gain, 0.0, 100.0), 1),
        memory=round(clamp(before.memory - ((memory_gain_mb / memory_total_mb) * 100.0), 0.0, 100.0), 1),
        disk=round(clamp(before.disk - ((disk_gain_mb / disk_total_mb) * 100.0), 0.0, 100.0), 1),
        health_score=round(clamp(float(before.health_score or 60.0) + health_gain, 0.0, 100.0), 1),
    )

    confidence = normalize_confidence(sum(action.confidence for action in top_actions) / len(top_actions))
    memory_gain_gb = memory_gain_mb / 1024.0
    disk_gain_gb = disk_gain_mb / 1024.0

    return WhatIfScenario(
        title="Intent-aware recovery pack",
        summary=(
            f"Following the top {len(top_actions)} steps could reclaim about {cpu_gain:.1f} CPU points, "
            f"{memory_gain_gb:.2f} GB of memory, and {disk_gain_gb:.2f} GB of disk capacity."
        ),
        confidence=round(confidence, 3),
        before=before,
        after=after,
        estimated_gain=RecommendationImpact(
            cpu_points=round(cpu_gain, 1),
            memory_mb=round(memory_gain_mb, 1),
            disk_mb=round(disk_gain_mb, 1),
            health_points=round(health_gain, 1),
        ),
        actions=[
            ScenarioAction(
                recommendation_id=action.id,
                title=action.title,
                action_style=action.action_style,
                resource_type=action.resource_type,
            )
            for action in top_actions
        ],
        differentiator=(
            "Aegis ranks actions by actual local app behavior and protects work-critical tools before suggesting a cleanup path."
        ),
    )


def build_advisor(summary: SummaryResponse) -> AdvisorResponse:
    current = summary.current_metrics
    if not current:
        return AdvisorResponse(
            headline="Waiting for live telemetry",
            subheadline="Once the agent sends resource samples, the advisor will rank the best manual actions for CPU, memory, and disk pressure.",
            differentiator_title="Workload intent lens",
            differentiator_body="The advisor favors safe human decisions instead of blind process termination.",
        )

    enriched_processes = _build_enriched_processes(current.top_processes)
    non_system_count = sum(1 for process in enriched_processes if process["profile"].category != "system")
    if non_system_count < 3:
        live_processes = _build_enriched_processes(_collect_live_processes(settings.top_process_limit))
        enriched_processes = _merge_process_sources(enriched_processes, live_processes)

    watchlist = _build_watchlist(enriched_processes)

    recommendations = _build_process_recommendations(current, enriched_processes)
    recommendations.extend(_build_disk_recommendations(current))

    recommendations.sort(
        key=lambda item: (
            {"critical": 3, "high": 2, "medium": 1, "low": 0}[item.priority],
            item.impact.cpu_points + item.impact.health_points + (item.impact.disk_mb / 512.0),
            item.confidence,
        ),
        reverse=True,
    )
    recommendations = recommendations[:6]

    if not recommendations:
        recommendations = [_fallback_recommendation(current)]

    what_if = _build_what_if(current, recommendations)
    top_count = min(3, len(recommendations))
    top_cpu = what_if.estimated_gain.cpu_points
    top_memory = what_if.estimated_gain.memory_mb / 1024.0

    return AdvisorResponse(
        headline=f"{len(recommendations)} live suggestions are ready for operator review.",
        subheadline=(
            f"The top {top_count} moves could recover roughly {top_cpu:.1f} CPU points and "
            f"{top_memory:.2f} GB of memory while protecting work-critical tools."
        ),
        differentiator_title="Workload intent lens",
        differentiator_body=(
            "Unlike generic cloud dashboards, this advisor scores actual local apps, tags their business importance, "
            "and shows the projected payoff before anyone takes action."
        ),
        watchlist=watchlist,
        recommendations=recommendations,
        what_if=what_if,
    )
