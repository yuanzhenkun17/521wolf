"""Health payloads and runtime probes for the UI backend."""

from __future__ import annotations

import importlib.util
import os
import time
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

from dotenv import load_dotenv

from app.config import LLM_ENV_PATH, load_llm_config, load_tts_config
from app.services.llm import create_llm
from app.util.redaction import redact_text
from app.util.time import beijing_now_iso
from ui.backend.settings_runtime_variables import runtime_setting_bool_for_store, runtime_setting_float_for_store

_OK = "ok"
_DEGRADED = "degraded"
_ERROR = "error"
_UNKNOWN = "unknown"
_STALE = "stale"
_PROBE_PROMPT = "Return exactly: ok"
_DOTENV_LOADED = False


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
    langfuse_config = langfuse_config_check()
    tts_config = tts_config_check()
    checks = _checks_from(
        startup_checks,
        task_control,
        llm_config,
        llm_connectivity,
        langfuse_config,
        tts_config,
        store=store,
    )
    gates = build_runtime_gates(checks, store=store)
    status = _overall_status(checks, gates, store=store)
    ready = status != _ERROR
    degraded_features = _dedupe(
        [
            *_list(startup_checks.get("degraded_features")),
            *_task_degraded_features(task_control),
            *_checks_degraded_features(checks),
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


def langfuse_config_check() -> dict[str, Any]:
    """Return a local-only Langfuse configuration check."""
    _load_project_env_once()
    tracing_enabled = _env_true("LANGFUSE_TRACING_ENABLED")
    if not tracing_enabled:
        return {
            "status": _OK,
            "message": "Langfuse tracing is disabled.",
            "enabled": False,
            "source": "disabled",
        }

    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.environ.get("LANGFUSE_SECRET_KEY", "").strip()
    base_url = os.environ.get("LANGFUSE_BASE_URL", "").strip().rstrip("/")
    missing = [
        name
        for name, value in (
            ("LANGFUSE_PUBLIC_KEY", public_key),
            ("LANGFUSE_SECRET_KEY", secret_key),
            ("LANGFUSE_BASE_URL", base_url),
        )
        if not value
    ]
    if missing:
        return {
            "status": _ERROR,
            "message": "Langfuse tracing is enabled but required configuration is missing.",
            "enabled": True,
            "source": "environment",
            "missing": missing,
            "degraded_features": ["langfuse"],
            "actions": [
                "Set LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL.",
                "Disable LANGFUSE_TRACING_ENABLED if observability is not required.",
            ],
        }

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "status": _ERROR,
            "message": "Langfuse base URL is invalid.",
            "enabled": True,
            "source": "environment",
            "base_url": _public_url(base_url),
            "degraded_features": ["langfuse"],
            "actions": ["Set LANGFUSE_BASE_URL to a valid http(s) URL."],
        }

    capture_input_output = _env_bool("LANGFUSE_CAPTURE_INPUT_OUTPUT", default=False)
    sample_rate = _langfuse_sample_rate()
    warnings: list[str] = []
    actions: list[str] = []
    if not capture_input_output:
        warnings.append("capture_input_output_disabled")
        actions.append("Set LANGFUSE_CAPTURE_INPUT_OUTPUT=true if trace input/output should be visible.")
    if sample_rate.get("status") != _OK:
        warnings.append(str(sample_rate["reason"]))
        actions.extend(sample_rate.get("actions") or [])
    if not os.environ.get("LANGFUSE_ENVIRONMENT", "").strip():
        warnings.append("environment_missing")
    if not os.environ.get("LANGFUSE_RELEASE", "").strip():
        warnings.append("release_missing")

    status = _DEGRADED if warnings else _OK
    return {
        "status": status,
        "message": (
            "Langfuse tracing is configured with warnings."
            if warnings
            else "Langfuse tracing is configured."
        ),
        "enabled": True,
        "source": "environment",
        "base_url": _public_url(base_url),
        "capture_input_output": capture_input_output,
        "sample_rate": sample_rate.get("value"),
        "environment_configured": bool(os.environ.get("LANGFUSE_ENVIRONMENT", "").strip()),
        "release_configured": bool(os.environ.get("LANGFUSE_RELEASE", "").strip()),
        "warnings": warnings,
        "degraded_features": ["langfuse"] if warnings else [],
        "actions": _dedupe(actions),
    }


def tts_config_check() -> dict[str, Any]:
    """Return a local-only TTS configuration check."""
    try:
        config = load_tts_config()
    except Exception as exc:  # noqa: BLE001 - optional audio should report diagnostics without breaking health.
        return {
            "status": _DEGRADED,
            "message": "TTS is not configured.",
            "source": "missing_config",
            "error": _safe_error(exc),
            "degraded_features": ["tts"],
            "actions": ["Set WEREWOLF_TTS_API_KEY to enable speech playback."],
        }

    dependency = _dashscope_tts_dependency_check()
    payload = {
        "status": dependency["status"],
        "message": dependency["message"],
        "source": "environment",
        "provider": "dashscope",
        "model": str(config.get("model") or ""),
        "voice": str(config.get("voice") or ""),
        "voice_pool_size": len(config.get("voice_pool") if isinstance(config.get("voice_pool"), list) else []),
        "ws_url": _public_url(str(config.get("ws_url") or "")),
        "mode": str(config.get("mode") or ""),
        "sample_rate": config.get("sample_rate"),
        "max_chars": config.get("max_chars"),
    }
    if dependency["status"] != _OK:
        payload["degraded_features"] = ["tts"]
        payload["actions"] = list(dependency.get("actions") or [])
        if dependency.get("error"):
            payload["error"] = dependency["error"]
    return payload


def llm_config_check(
    store: Any,
    *,
    model_scope: str = "game_decision",
    model_profile_id: str | None = None,
) -> dict[str, Any]:
    """Return a local-only LLM configuration check."""
    normalized_profile_id = str(model_profile_id or "").strip() or None
    if getattr(store, "model", None) is not None and normalized_profile_id is None:
        return {
            "status": _OK,
            "message": "LLM is provided by the UI backend process.",
            "source": "injected_model",
        }
    if _env_true("UI_BACKEND_USE_FAKE_LLM") and normalized_profile_id is None:
        return {
            "status": _DEGRADED,
            "message": "UI backend is explicitly using the fake LLM.",
            "source": "fake_model",
            "degraded_features": ["real model play", "benchmark", "evolution"],
            "actions": ["Unset UI_BACKEND_USE_FAKE_LLM for real model runs."],
        }
    try:
        settings_runtime = _settings_model_runtime(
            store,
            scope=model_scope,
            model_profile_id=normalized_profile_id,
            strict=normalized_profile_id is not None,
        )
    except Exception as exc:  # noqa: BLE001 - converted to redacted health diagnostics.
        return {
            "status": _ERROR,
            "message": "Selected Settings model profile is unavailable.",
            "source": "settings_profile",
            "model_scope": model_scope,
            "model_profile_id": normalized_profile_id,
            "error": _safe_error(exc),
            "degraded_features": ["real model play", "benchmark", "evolution"],
            "actions": ["Open Settings and test the selected model profile."],
        }
    if settings_runtime is not None:
        runtime = settings_runtime.get("model_runtime") if isinstance(settings_runtime.get("model_runtime"), dict) else {}
        return {
            "status": _OK,
            "message": "LLM configuration is available from local Settings.",
            "source": "settings_profile",
            "model_scope": model_scope,
            "model": str(settings_runtime.get("model_id") or ""),
            "model_profile_id": runtime.get("model_profile_id"),
            "base_url_host": runtime.get("base_url_host"),
            "model_config_hash": settings_runtime.get("model_config_hash"),
        }
    if normalized_profile_id is not None:
        return {
            "status": _ERROR,
            "message": "Selected Settings model profile did not resolve to a usable runtime.",
            "source": "settings_profile",
            "model_scope": model_scope,
            "model_profile_id": normalized_profile_id,
            "degraded_features": ["real model play", "benchmark", "evolution"],
            "actions": ["Open Settings and test the selected model profile."],
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
        "model_scope": model_scope,
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


async def probe_llm_connectivity(
    store: Any,
    *,
    scope: str = "game_start",
    model_scope: str | None = None,
    model_profile_id: str | None = None,
    cache: bool = True,
) -> dict[str, Any]:
    """Probe the effective LLM and cache a redacted result."""
    resolved_model_scope = model_scope or _model_scope_for_runtime_scope(scope)
    normalized_profile_id = str(model_profile_id or "").strip() or None
    config = llm_config_check(
        store,
        model_scope=resolved_model_scope,
        model_profile_id=normalized_profile_id,
    )
    if config.get("status") == _ERROR:
        result = {
            "status": _ERROR,
            "scope": scope,
            "model_scope": resolved_model_scope,
            "checked_at": beijing_now_iso(),
            "message": "LLM configuration is missing or invalid.",
            "source": config.get("source"),
            "model": config.get("model"),
            "model_profile_id": config.get("model_profile_id"),
            "model_config_hash": config.get("model_config_hash"),
            "actions": list(config.get("actions") or []),
            "error": config.get("error"),
        }
        if cache:
            _set_llm_probe_cache(store, result, success=False)
        return result

    started = time.perf_counter()
    try:
        llm = _probe_model(
            store,
            model_scope=resolved_model_scope,
            model_profile_id=normalized_profile_id,
        )
        await llm.ainvoke(_PROBE_PROMPT)
        result = {
            "status": _OK,
            "scope": scope,
            "model_scope": resolved_model_scope,
            "checked_at": beijing_now_iso(),
            "latency_ms": int(round((time.perf_counter() - started) * 1000)),
            "message": "LLM connectivity probe succeeded.",
            "source": config.get("source") or "configured",
            "model": config.get("model"),
            "model_profile_id": config.get("model_profile_id"),
            "model_config_hash": config.get("model_config_hash"),
            "base_url_host": config.get("base_url_host"),
            "base_url": config.get("base_url"),
        }
        if cache:
            _set_llm_probe_cache(store, result, success=True)
        return result
    except Exception as exc:  # noqa: BLE001 - converted to runtime gate diagnostics.
        result = {
            "status": _ERROR,
            "scope": scope,
            "model_scope": resolved_model_scope,
            "checked_at": beijing_now_iso(),
            "latency_ms": int(round((time.perf_counter() - started) * 1000)),
            "message": "LLM connectivity probe failed.",
            "source": config.get("source") or "configured",
            "model": config.get("model"),
            "model_profile_id": config.get("model_profile_id"),
            "model_config_hash": config.get("model_config_hash"),
            "base_url_host": config.get("base_url_host"),
            "base_url": config.get("base_url"),
            "error": _safe_error(exc),
            "actions": [
                "Check the configured model API key, base URL, and model name.",
                "Open Settings and run the model connection test.",
            ],
        }
        if cache:
            _set_llm_probe_cache(store, result, success=False)
        return result


def build_runtime_gates(checks: dict[str, Any], *, store: Any | None = None) -> dict[str, dict[str, Any]]:
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
            extra_required=_task_required_checks(store),
            allow_unknown_connectivity=True,
        ),
        "evolution_start": _gate(
            "evolution_start",
            checks,
            required=("llm_config", "llm_connectivity"),
            extra_required=_task_required_checks(store),
            allow_unknown_connectivity=True,
        ),
    }


def _checks_from(
    startup_checks: dict[str, Any],
    task_control: dict[str, Any],
    llm_config: dict[str, Any],
    llm_connectivity: dict[str, Any],
    langfuse_config: dict[str, Any],
    tts_config: dict[str, Any],
    *,
    store: Any | None = None,
) -> dict[str, Any]:
    startup = _mapping(startup_checks.get("checks"))
    artifact_root = _mapping(task_control.get("artifact_root"))
    task_status = str(task_control.get("status") or _UNKNOWN)
    return {
        **startup,
        "llm_config": llm_config,
        "llm_connectivity": llm_connectivity,
        "langfuse_config": langfuse_config,
        "tts_config": tts_config,
        "task_queue": {
            "status": task_status,
            "message": task_control.get("message") or "Task control status is unknown.",
            "queue_status_counts": _mapping(task_control.get("queue_status_counts")),
            "stale_running_count": int(task_control.get("stale_running_count") or 0),
        },
        "task_worker": {
            "status": _worker_status(task_control, store=store),
            "message": _worker_message(task_control, store=store),
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


def _overall_status(checks: dict[str, Any], gates: dict[str, Any], *, store: Any | None = None) -> str:
    statuses = {str(check.get("status") or _UNKNOWN) for check in checks.values() if isinstance(check, dict)}
    if _ERROR in statuses:
        return _ERROR
    if _task_worker_required(store):
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


def _task_required_checks(store: Any | None = None) -> tuple[str, ...]:
    if _task_worker_required(store) or runtime_setting_bool_for_store(store, "WOLF_USE_PG_TASK_QUEUE", default=False):
        return ("task_queue", "task_worker", "artifact_root")
    return ()


def _worker_status(task_control: dict[str, Any], *, store: Any | None = None) -> str:
    if str(task_control.get("status") or "") == _ERROR:
        return _ERROR
    if task_control.get("worker_fresh"):
        return _OK
    return _ERROR if _task_worker_required(store) else _DEGRADED


def _worker_message(task_control: dict[str, Any], *, store: Any | None = None) -> str:
    if task_control.get("worker_fresh"):
        return "Task worker heartbeat is fresh."
    if _task_worker_required(store):
        return "Task worker heartbeat is missing or stale."
    return "Task worker heartbeat is missing or stale; long-running queue tasks may be delayed."


def _task_worker_required(store: Any | None = None) -> bool:
    return runtime_setting_bool_for_store(store, "TASK_WORKER_REQUIRED", default=False) or runtime_setting_bool_for_store(
        store,
        "WOLF_USE_PG_TASK_QUEUE",
        default=False,
    )


def _probe_model(
    store: Any,
    *,
    model_scope: str = "game_decision",
    model_profile_id: str | None = None,
) -> Any:
    normalized_profile_id = str(model_profile_id or "").strip() or None
    if getattr(store, "model", None) is not None and normalized_profile_id is None:
        return store.model
    if _env_true("UI_BACKEND_USE_FAKE_LLM") and normalized_profile_id is None:
        return store.model_for_run()
    model_for_run = getattr(store, "model_for_run", None)
    if callable(model_for_run):
        return model_for_run(scope=model_scope, model_profile_id=normalized_profile_id)
    if normalized_profile_id is not None:
        raise RuntimeError("model profile resolver is unavailable")
    return create_llm()


def _settings_model_runtime(
    store: Any,
    *,
    scope: str,
    model_profile_id: str | None = None,
    strict: bool = False,
) -> dict[str, Any] | None:
    resolver = getattr(store, "settings_model_runtime_for_scope", None)
    if not callable(resolver):
        return None
    try:
        runtime = resolver(scope, model_profile_id=model_profile_id)
    except Exception:  # noqa: BLE001 - health must keep reporting public fallback diagnostics.
        if strict:
            raise
        return None
    return runtime if isinstance(runtime, dict) and runtime else None


def _model_scope_for_runtime_scope(scope: str) -> str:
    return {
        "game_start": "game_decision",
        "benchmark_start": "benchmark",
        "evolution_start": "evolution",
        "settings_model_test": "prompt_test",
    }.get(str(scope or "").strip(), "game_decision")


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
    ttl = runtime_setting_float_for_store(
        store,
        "HEALTH_LLM_PROBE_TTL_SECONDS" if success else "HEALTH_LLM_PROBE_FAILURE_TTL_SECONDS",
        default=300.0 if success else 60.0,
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


def _checks_degraded_features(checks: dict[str, Any]) -> list[str]:
    features: list[str] = []
    for check in checks.values():
        if isinstance(check, dict) and str(check.get("status") or "") != _OK:
            features.extend(_list(check.get("degraded_features")))
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
        "message": "Health check error details were redacted.",
    }


def _public_url(value: str) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        text = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except ValueError:
        text = text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return redact_text(text, context="public") if text else ""


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on", "enabled"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _load_project_env_once() -> None:
    global _DOTENV_LOADED
    if _DOTENV_LOADED:
        return
    load_dotenv(LLM_ENV_PATH, override=False)
    _DOTENV_LOADED = True


def _langfuse_sample_rate() -> dict[str, Any]:
    raw = os.environ.get("LANGFUSE_SAMPLE_RATE")
    if raw is None or raw == "":
        return {
            "status": _DEGRADED,
            "value": None,
            "reason": "sample_rate_missing",
            "actions": ["Set LANGFUSE_SAMPLE_RATE to a value above 0 if sampling should be explicit."],
        }
    try:
        value = float(raw)
    except ValueError:
        return {
            "status": _DEGRADED,
            "value": None,
            "reason": "sample_rate_invalid",
            "actions": ["Set LANGFUSE_SAMPLE_RATE to a numeric value between 0 and 1."],
        }
    if value <= 0:
        return {
            "status": _DEGRADED,
            "value": value,
            "reason": "sample_rate_zero",
            "actions": ["Set LANGFUSE_SAMPLE_RATE above 0 so traces are not sampled out."],
        }
    return {"status": _OK, "value": value, "reason": ""}


def _dashscope_tts_dependency_check() -> dict[str, Any]:
    if importlib.util.find_spec("dashscope") is None:
        return {
            "status": _DEGRADED,
            "message": "DashScope realtime TTS dependency is not installed.",
            "actions": ["Install the dashscope package to enable TTS streaming."],
        }
    try:
        from ui.backend.tts_dashscope import ensure_dashscope_realtime_dependency

        ensure_dashscope_realtime_dependency()
    except Exception as exc:  # noqa: BLE001 - dependency checks are diagnostics only.
        return {
            "status": _DEGRADED,
            "message": "DashScope realtime TTS dependency is unavailable.",
            "error": _safe_error(exc),
            "actions": ["Install a dashscope version that includes qwen_tts_realtime."],
        }
    return {
        "status": _OK,
        "message": "DashScope realtime TTS is configured.",
    }


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
