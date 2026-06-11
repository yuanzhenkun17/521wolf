"""Operational metrics payloads for health probes and lightweight alerting."""

from __future__ import annotations

from typing import Any

from app.util.time import beijing_now_iso
from ui.backend.constants import BACKGROUND_ACTIVE_STATUSES
from ui.backend.health import build_health_payload

_OK = "ok"
_DEGRADED = "degraded"
_ERROR = "error"
_UNKNOWN = "unknown"
_LIVE_GAME_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted", "stopped", "error"}


def build_ops_metrics_payload(store: Any) -> dict[str, Any]:
    """Build a compact, public operational metrics snapshot.

    This endpoint intentionally reuses the public health payload and local
    in-memory counters. It does not include raw task payloads, filesystem paths,
    worker ids, API keys, or other operator secrets.
    """
    health = build_health_payload(store)
    checks = _mapping(health.get("checks"))
    gates = _mapping(health.get("gates"))
    task_queue = _mapping(checks.get("task_queue"))
    task_worker = _mapping(checks.get("task_worker"))
    artifact_root = _mapping(checks.get("artifact_root"))
    llm_config = _mapping(checks.get("llm_config"))
    llm_connectivity = _mapping(checks.get("llm_connectivity"))
    langfuse_config = _mapping(checks.get("langfuse_config"))
    tts_config = _mapping(checks.get("tts_config"))
    queue_counts = _int_mapping(task_queue.get("queue_status_counts"))
    background_counts = _background_counts(store)
    gate_ready = {
        key: bool(_mapping(gate).get("ready"))
        for key, gate in gates.items()
    }
    payload = {
        "kind": "ops_metrics",
        "schema_version": 1,
        "generated_at": beijing_now_iso(),
        "status": str(health.get("status") or _UNKNOWN),
        "ready": bool(health.get("ready")),
        "summary": str(health.get("summary") or ""),
        "release": _mapping(health.get("release")),
        "metrics": {
            "health_ready": 1 if health.get("ready") else 0,
            "health_check_status_counts": _status_counts(checks.values()),
            "health_gate_ready": gate_ready,
            "health_gate_blocked_count": sum(1 for ready in gate_ready.values() if not ready),
            "degraded_feature_count": len(_list(health.get("degraded_features"))),
            "action_count": len(_list(health.get("actions"))),
            "live_game_active_count": len(_mapping(getattr(store, "live_sessions", {}))),
            "game_status_counts": _status_counts(_mapping(getattr(store, "games", {})).values()),
            "background_active_count": background_counts["active"],
            "background_status_counts": background_counts["statuses"],
            "task_queue_status_counts": queue_counts,
            "task_queue_stale_running_count": _safe_int(task_queue.get("stale_running_count")),
            "task_worker_fresh": 1 if task_worker.get("worker_fresh") else 0,
            "task_worker_count": _safe_int(task_worker.get("worker_count")),
            "artifact_root_writable": 1 if artifact_root.get("writable") else 0,
        },
        "checks": {
            key: {"status": str(value.get("status") or _UNKNOWN)}
            for key, value in checks.items()
            if isinstance(value, dict)
        },
        "tasks": {
            "queue_status_counts": queue_counts,
            "stale_running_count": _safe_int(task_queue.get("stale_running_count")),
            "worker_fresh": bool(task_worker.get("worker_fresh")),
            "worker_count": _safe_int(task_worker.get("worker_count")),
            "artifact_root_writable": bool(artifact_root.get("writable")),
        },
        "runtime": {
            "live_game_active_count": len(_mapping(getattr(store, "live_sessions", {}))),
            "game_status_counts": _status_counts(_mapping(getattr(store, "games", {})).values()),
            "background_active_count": background_counts["active"],
            "background_status_counts": background_counts["statuses"],
        },
        "llm": {
            "config_status": str(llm_config.get("status") or _UNKNOWN),
            "config_source": str(llm_config.get("source") or ""),
            "connectivity_status": str(llm_connectivity.get("status") or _UNKNOWN),
            "connectivity_source": str(llm_connectivity.get("source") or ""),
        },
        "integrations": {
            "langfuse": {
                "status": str(langfuse_config.get("status") or _UNKNOWN),
                "enabled": bool(langfuse_config.get("enabled")),
                "capture_input_output": bool(langfuse_config.get("capture_input_output")),
                "warning_count": len(_list(langfuse_config.get("warnings"))),
            },
            "tts": {
                "status": str(tts_config.get("status") or _UNKNOWN),
                "provider": str(tts_config.get("provider") or ""),
                "mode": str(tts_config.get("mode") or ""),
            },
        },
    }
    payload["alerts"] = _alerts_from(payload=payload, checks=checks, gates=gates)
    return payload


def _background_counts(store: Any) -> dict[str, Any]:
    entities = [
        *_mapping(getattr(store, "evolution_runs", {})).values(),
        *_mapping(getattr(store, "evolution_batches", {})).values(),
    ]
    statuses = _status_counts(entities)
    active = sum(count for status, count in statuses.items() if status in BACKGROUND_ACTIVE_STATUSES)
    return {"active": active, "statuses": statuses}


def _alerts_from(*, payload: dict[str, Any], checks: dict[str, Any], gates: dict[str, Any]) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if not payload.get("ready"):
        alerts.append(_alert("health_not_ready", _ERROR, "API health is not ready."))
    for key, gate in gates.items():
        raw = _mapping(gate)
        if raw and not raw.get("ready", False):
            alerts.append(_alert(f"gate_blocked.{key}", _ERROR, f"{key} gate is blocked."))
    task_queue = _mapping(checks.get("task_queue"))
    if _safe_int(task_queue.get("stale_running_count")) > 0:
        alerts.append(_alert("task_queue.stale_running", _ERROR, "Task queue has stale running tasks."))
    task_worker = _mapping(checks.get("task_worker"))
    if not task_worker.get("worker_fresh"):
        severity = _ERROR if str(task_worker.get("status") or "") == _ERROR else _DEGRADED
        alerts.append(_alert("task_worker.not_fresh", severity, "Task worker heartbeat is missing or stale."))
    artifact_root = _mapping(checks.get("artifact_root"))
    if artifact_root and artifact_root.get("writable") is False:
        alerts.append(_alert("artifact_root.not_writable", _ERROR, "Task artifact root is not writable."))
    langfuse = _mapping(checks.get("langfuse_config"))
    if str(langfuse.get("status") or "") == _ERROR:
        alerts.append(_alert("langfuse.config_error", _DEGRADED, "Langfuse is configured incorrectly."))
    if langfuse.get("enabled") and langfuse.get("capture_input_output") is False:
        alerts.append(_alert("langfuse.capture_input_output_disabled", _DEGRADED, "Langfuse input/output capture is disabled."))
    return alerts


def _alert(code: str, severity: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "message": message}


def _status_counts(values: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in values if isinstance(values, list | tuple | set) else list(values or []):
        status = _status_for(item)
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _status_for(item: Any) -> str:
    if isinstance(item, dict):
        status = str(item.get("status") or "").strip().lower()
    else:
        status = str(getattr(item, "status", "") or "").strip().lower()
    if not status:
        status = "active" if item is not None else _UNKNOWN
    if status in _LIVE_GAME_TERMINAL_STATUSES:
        return status
    return status or _UNKNOWN


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _int_mapping(value: Any) -> dict[str, int]:
    raw = _mapping(value)
    return {str(key): _safe_int(item) for key, item in sorted(raw.items())}
