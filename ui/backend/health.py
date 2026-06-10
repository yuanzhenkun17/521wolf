"""Health payloads and runtime probes for the UI backend."""

from __future__ import annotations

import os
import time
from typing import Any

from app.config import load_llm_config
from app.services.llm import create_llm
from app.util.redaction import redact_text
from app.util.time import beijing_now_iso

_OK = "ok"
_DEGRADED = "degraded"
_ERROR = "error"
_UNKNOWN = "unknown"
_STALE = "stale"
_PROBE_PROMPT = "Return exactly: ok"


def build_health_payload(store: Any) -> dict[str, Any]:
    """Build the public /api/health payload.

    The endpoint is intentionally read-mostly. It exposes cached probe state and
    cheap local checks; expensive network probes are triggered through explicit
    probe/preflight calls.
    """
    startup_checks = _mapping(getattr(store, "startup_checks", None))
    task_control = _task_control_health(store)
    llm_config = llm_config_check(store)
    llm_connectivity = llm_connectivity_status(store)
    checks = _checks_from(startup_checks, task_control, llm_config, llm_connectivity)
    gates = build_runtime_gates(checks)
    status = _overall_status(checks, gates)
    ready = status != _ERROR
    degraded_features = _dedupe(
        [
            *_list(startup_checks.get("degraded_features")),
            *_task_degraded_features(task_control),
            *_gate_degraded_features(gates),
        ]
    )
    actions = _dedupe(
        [
            *_list(startup_checks.get("actions")),
            *_list(task_control.get("actions")),
            *_actions_from_checks(checks),
            *_actions_from_gates(gates),
        ]
    )
    return {
        "schema_version": 2,
        "ok": ready,
        "status": status,
        "ready": ready,
        "mode": "api",
        "summary": _summary_for(status),
        "checks": checks,
        "gates": gates,
        "degraded_features": degraded_features,
        "actions": actions,
        "external": {
            "provider": "app-langgraph",
            "supports_human": True,
            "supports_sse": True,
            "active_game_id": _active_game_id(store),
            "llm": _legacy_llm_status(store),
            "tts": _legacy_tts_status(store),
            "tts_streaming": _legacy_tts_streaming_available(store),
            "startup_checks": startup_checks,
            "task_control": task_control,
        },
    }


def llm_config_check(store: Any) -> dict[str, Any]:
    """Return a local-only LLM configuration check."""
    if getattr(store, "model", None) is not None:
        return {
            "status": _OK,
            "message": "LLM is provided by the UI backend process.",
            "source": "injected_model",
        }
    if _env_true("UI_BACKEND_USE_FAKE_LLM"):
        return {
            "status": _DEGRADED,
            "message": "UI backend is explicitly using the fake LLM.",
            "source": "fake_model",
            "degraded_features": ["real model play", "benchmark", "evolution"],
            "actions": ["Unset UI_BACKEND_USE_FAKE_LLM for real model runs."],
        }
    settings_runtime = _settings_model_runtime(store, scope="game_decision")
    if settings_runtime is not None:
        runtime = settings_runtime.get("model_runtime") if isinstance(settings_runtime.get("model_runtime"), dict) else {}
        return {
            "status": _OK,
            "message": "LLM configuration is available from local Settings.",
            "source": "settings_profile",
            "model": str(settings_runtime.get("model_id") or ""),
            "model_profile_id": runtime.get("model_profile_id"),
            "base_url_host": runtime.get("base_url_host"),
            "model_config_hash": settings_runtime.get("model_config_hash"),
        }
    try:
        config = load_llm_config()
    except Exception as exc:  # noqa: BLE001 - health diagnostics should fail open to payloads.
        return {
            "status": _ERROR,
            "message": "LLM configuration is missing or invalid.",
            "source": "missing_config",
            "error": _safe_error(exc),
            "degraded_features": ["real model play", "benchmark", "evolution"],
            "actions": [
                "Set WEREWOLF_LLM_API_KEY, WEREWOLF_LLM_BASE_URL, and WEREWOLF_LLM_MODEL.",
                "Open Settings and test the model connection.",
            ],
        }
    return {
        "status": _OK,
        "message": "LLM configuration is available.",
        "source": "configured",
        "model": str(config.get("model") or ""),
        "base_url": _public_url(str(config.get("base_url") or "")),
        "timeout": config.get("timeout"),
        "runtime_timeout": config.get("runtime_timeout"),
    }


def llm_connectivity_status(store: Any) -> dict[str, Any]:
    cached = _llm_probe_cache(store)
    if cached:
        return dict(cached)
    config = llm_config_check(store)
    if config.get("status") == _ERROR:
        return {
            "status": _ERROR,
            "message": "LLM connectivity cannot be checked because configuration is invalid.",
            "source": config.get("source"),
            "actions": list(config.get("actions") or []),
        }
    return {
        "status": _UNKNOWN,
        "message": "LLM connectivity has not been probed yet.",
        "source": config.get("source") or "configured",
        "actions": ["Run the LLM probe from Settings or start a flow that requires the model."],
    }


async def probe_llm_connectivity(store: Any, *, scope: str = "game_start") -> dict[str, Any]:
    """Probe the effective LLM and cache a redacted result."""
    config = llm_config_check(store)
    if config.get("status") == _ERROR:
        result = {
            "status": _ERROR,
            "scope": scope,
            "checked_at": beijing_now_iso(),
            "message": "LLM configuration is missing or invalid.",
            "source": config.get("source"),
            "actions": list(config.get("actions") or []),
            "error": config.get("error"),
        }
        _set_llm_probe_cache(store, result, success=False)
        return result

    started = time.perf_counter()
    try:
        llm = _probe_model(store)
        await llm.ainvoke(_PROBE_PROMPT)
        result = {
            "status": _OK,
            "scope": scope,
            "checked_at": beijing_now_iso(),
            "latency_ms": int(round((time.perf_counter() - started) * 1000)),
            "message": "LLM connectivity probe succeeded.",
            "source": config.get("source") or "configured",
            "model": config.get("model"),
            "base_url": config.get("base_url"),
        }
        _set_llm_probe_cache(store, result, success=True)
        return result
    except Exception as exc:  # noqa: BLE001 - converted to runtime gate diagnostics.
        result = {
            "status": _ERROR,
            "scope": scope,
            "checked_at": beijing_now_iso(),
            "latency_ms": int(round((time.perf_counter() - started) * 1000)),
            "message": "LLM connectivity probe failed.",
            "source": config.get("source") or "configured",
            "model": config.get("model"),
            "base_url": config.get("base_url"),
            "error": _safe_error(exc),
            "actions": [
                "Check the configured model API key, base URL, and model name.",
                "Open Settings and run the model connection test.",
            ],
        }
        _set_llm_probe_cache(store, result, success=False)
        return result


def build_runtime_gates(checks: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "game_start": _gate(
            "game_start",
            checks,
            required=("llm_config", "llm_connectivity"),
            allow_unknown_connectivity=True,
        ),
        "benchmark_start": _gate(
            "benchmark_start",
            checks,
            required=("llm_config", "llm_connectivity"),
            extra_required=_task_required_checks(),
            allow_unknown_connectivity=True,
        ),
        "evolution_start": _gate(
            "evolution_start",
            checks,
            required=("llm_config", "llm_connectivity"),
            extra_required=_task_required_checks(),
            allow_unknown_connectivity=True,
        ),
    }


def _checks_from(
    startup_checks: dict[str, Any],
    task_control: dict[str, Any],
    llm_config: dict[str, Any],
    llm_connectivity: dict[str, Any],
) -> dict[str, Any]:
    startup = _mapping(startup_checks.get("checks"))
    artifact_root = _mapping(task_control.get("artifact_root"))
    task_status = str(task_control.get("status") or _UNKNOWN)
    return {
        **startup,
        "llm_config": llm_config,
        "llm_connectivity": llm_connectivity,
        "task_queue": {
            "status": task_status,
            "message": task_control.get("message") or "Task control status is unknown.",
            "queue_status_counts": _mapping(task_control.get("queue_status_counts")),
            "stale_running_count": int(task_control.get("stale_running_count") or 0),
        },
        "task_worker": {
            "status": _worker_status(task_control),
            "message": _worker_message(task_control),
            "worker_fresh": bool(task_control.get("worker_fresh")),
            "workers": _list(task_control.get("workers")),
        },
        "artifact_root": artifact_root or {
            "status": _UNKNOWN,
            "message": "Artifact root status is unknown.",
        },
    }


def _gate(
    scope: str,
    checks: dict[str, Any],
    *,
    required: tuple[str, ...],
    extra_required: tuple[str, ...] = (),
    allow_unknown_connectivity: bool = False,
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    for name in (*required, *extra_required):
        check = _mapping(checks.get(name))
        status = str(check.get("status") or _UNKNOWN)
        if status == _ERROR:
            blockers.append(name)
        elif status in {_DEGRADED, _STALE}:
            warnings.append(name)
        elif status == _UNKNOWN:
            if allow_unknown_connectivity and name == "llm_connectivity":
                warnings.append(name)
            else:
                blockers.append(name)
    ready = not blockers
    return {
        "ready": ready,
        "status": _OK if ready and not warnings else _DEGRADED if ready else _ERROR,
        "blockers": blockers,
        "warnings": warnings,
        "actions": _gate_actions(scope, blockers, checks),
    }


def _overall_status(checks: dict[str, Any], gates: dict[str, Any]) -> str:
    statuses = {str(check.get("status") or _UNKNOWN) for check in checks.values() if isinstance(check, dict)}
    if _ERROR in statuses:
        return _ERROR
    if _env_true("TASK_WORKER_REQUIRED"):
        worker_gate = gates.get("benchmark_start") or {}
        if not worker_gate.get("ready", False):
            return _ERROR
    if _DEGRADED in statuses or _STALE in statuses:
        return _DEGRADED
    if any(not gate.get("ready", False) for gate in gates.values()):
        return _DEGRADED
    if _UNKNOWN in statuses:
        return _DEGRADED
    return _OK


def _task_required_checks() -> tuple[str, ...]:
    if _env_true("TASK_WORKER_REQUIRED") or _env_true("WOLF_USE_PG_TASK_QUEUE"):
        return ("task_queue", "task_worker", "artifact_root")
    return ()


def _worker_status(task_control: dict[str, Any]) -> str:
    if str(task_control.get("status") or "") == _ERROR:
        return _ERROR
    if task_control.get("worker_fresh"):
        return _OK
    return _ERROR if _task_worker_required() else _DEGRADED


def _worker_message(task_control: dict[str, Any]) -> str:
    if task_control.get("worker_fresh"):
        return "Task worker heartbeat is fresh."
    if _task_worker_required():
        return "Task worker heartbeat is missing or stale."
    return "Task worker heartbeat is missing or stale; long-running queue tasks may be delayed."


def _task_worker_required() -> bool:
    return _env_true("TASK_WORKER_REQUIRED") or _env_true("WOLF_USE_PG_TASK_QUEUE")


def _probe_model(store: Any) -> Any:
    if getattr(store, "model", None) is not None:
        return store.model
    if _env_true("UI_BACKEND_USE_FAKE_LLM"):
        return store.model_for_run()
    model_for_run = getattr(store, "model_for_run", None)
    if callable(model_for_run):
        return model_for_run(scope="game_decision")
    return create_llm()


def _settings_model_runtime(store: Any, *, scope: str) -> dict[str, Any] | None:
    resolver = getattr(store, "settings_model_runtime_for_scope", None)
    if not callable(resolver):
        return None
    try:
        runtime = resolver(scope)
    except Exception:  # noqa: BLE001 - health must keep reporting public fallback diagnostics.
        return None
    return runtime if isinstance(runtime, dict) and runtime else None


def _llm_probe_cache(store: Any) -> dict[str, Any] | None:
    cached = getattr(store, "_llm_connectivity_cache", None)
    if not isinstance(cached, dict):
        return None
    expires_at = float(cached.get("_expires_monotonic") or 0)
    if expires_at and expires_at < time.monotonic():
        public = {key: value for key, value in cached.items() if not key.startswith("_")}
        public["status"] = _STALE
        public["message"] = "LLM connectivity probe is stale."
        return public
    return {key: value for key, value in cached.items() if not key.startswith("_")}


def _set_llm_probe_cache(store: Any, result: dict[str, Any], *, success: bool) -> None:
    ttl = _env_float(
        "HEALTH_LLM_PROBE_TTL_SECONDS" if success else "HEALTH_LLM_PROBE_FAILURE_TTL_SECONDS",
        300.0 if success else 60.0,
    )
    cached = dict(result)
    cached["_expires_monotonic"] = time.monotonic() + max(0.0, ttl)
    setattr(store, "_llm_connectivity_cache", cached)


def _task_control_health(store: Any) -> dict[str, Any]:
    try:
        return _mapping(store.task_service.task_control_health())
    except Exception as exc:  # noqa: BLE001 - health endpoint must return diagnostics.
        return {
            "status": _ERROR,
            "message": "Task control health check failed.",
            "error": _safe_error(exc),
            "queue_status_counts": {},
            "stale_running_count": 0,
            "worker_fresh": False,
            "workers": [],
        }


def _legacy_llm_status(store: Any) -> str:
    try:
        return str(store.llm_status())
    except Exception:
        return "unknown"


def _legacy_tts_status(store: Any) -> str:
    try:
        return str(store.tts_status())
    except Exception:
        return "unknown"


def _legacy_tts_streaming_available(store: Any) -> bool:
    try:
        return bool(store.tts_streaming_available())
    except Exception:
        return False


def _active_game_id(store: Any) -> str | None:
    for game_id, session in getattr(store, "live_sessions", {}).items():
        if getattr(session, "status", None) == "running":
            return str(game_id)
    return None


def _gate_actions(scope: str, blockers: list[str], checks: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    if "llm_config" in blockers or "llm_connectivity" in blockers:
        actions.append("Open Settings and test the model connection.")
    if "task_worker" in blockers:
        actions.append("Start the task worker and wait for a fresh heartbeat.")
    if "artifact_root" in blockers:
        actions.append("Verify the task artifact root exists and is writable.")
    for name in blockers:
        actions.extend(_list(_mapping(checks.get(name)).get("actions")))
    if not actions and blockers:
        actions.append(f"Resolve blockers before starting {scope}.")
    return _dedupe(actions)


def _actions_from_checks(checks: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for check in checks.values():
        if isinstance(check, dict):
            actions.extend(_list(check.get("actions")))
    return actions


def _actions_from_gates(gates: dict[str, Any]) -> list[str]:
    actions: list[str] = []
    for gate in gates.values():
        if isinstance(gate, dict):
            actions.extend(_list(gate.get("actions")))
    return actions


def _task_degraded_features(task_control: dict[str, Any]) -> list[str]:
    features: list[str] = []
    if str(task_control.get("status") or "") != _OK:
        features.append("task control")
    artifact_root = _mapping(task_control.get("artifact_root"))
    if str(artifact_root.get("status") or "") == _ERROR:
        features.append("task artifacts")
    if not task_control.get("worker_fresh"):
        features.append("durable task worker")
    return features


def _gate_degraded_features(gates: dict[str, Any]) -> list[str]:
    return [
        scope
        for scope, gate in gates.items()
        if isinstance(gate, dict) and not gate.get("ready", False)
    ]


def _safe_error(exc: Exception) -> dict[str, str]:
    return {
        "type": type(exc).__name__,
        "message": redact_text(str(exc) or type(exc).__name__, context="diagnostic"),
    }


def _public_url(value: str) -> str:
    return redact_text(value.rstrip("/"), context="public") if value else ""


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _summary_for(status: str) -> str:
    if status == _OK:
        return "API health checks passed."
    if status == _DEGRADED:
        return "API is available with degraded features."
    if status == _ERROR:
        return "One or more critical runtime checks failed."
    return "API health status is unknown."


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _dedupe(values: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result
