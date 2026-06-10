"""Runtime gates used before starting user-visible work."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from ui.backend.health import build_health_payload, probe_llm_connectivity

_LLM_SCOPES = {"game_start", "benchmark_start", "evolution_start", "settings_model_test"}


async def check_runtime_ready(store: Any, *, scope: str) -> dict[str, Any]:
    """Return the runtime gate for *scope*, probing the LLM when required."""
    health = build_health_payload(store)
    gate = _gate_for(health, scope)
    if scope in _LLM_SCOPES and _needs_llm_probe(gate, health):
        await probe_llm_connectivity(store, scope=scope)
        health = build_health_payload(store)
        gate = _gate_for(health, scope)
    return {
        "scope": scope,
        "ready": bool(gate.get("ready")),
        "status": gate.get("status") or "unknown",
        "gate": gate,
        "checks": health.get("checks") if isinstance(health.get("checks"), dict) else {},
        "actions": gate.get("actions") if isinstance(gate.get("actions"), list) else [],
    }


async def require_runtime_ready(store: Any, *, scope: str) -> dict[str, Any]:
    """Raise HTTP 503 when a runtime gate is not ready."""
    result = await check_runtime_ready(store, scope=scope)
    if result["ready"]:
        return result
    gate = result["gate"] if isinstance(result.get("gate"), dict) else {}
    blockers = list(gate.get("blockers") or [])
    checks = result["checks"] if isinstance(result.get("checks"), dict) else {}
    raise HTTPException(
        status_code=503,
        detail={
            "code": "runtime_not_ready",
            "message": _message_for(scope, blockers),
            "scope": scope,
            "blockers": blockers,
            "checks": {name: checks.get(name) for name in blockers if name in checks},
            "actions": result["actions"],
        },
    )


def _gate_for(health: dict[str, Any], scope: str) -> dict[str, Any]:
    gates = health.get("gates") if isinstance(health.get("gates"), dict) else {}
    gate = gates.get(scope)
    return dict(gate) if isinstance(gate, dict) else {
        "ready": False,
        "status": "error",
        "blockers": ["health_gate_missing"],
        "warnings": [],
        "actions": [f"Health gate {scope} is missing."],
    }


def _needs_llm_probe(gate: dict[str, Any], health: dict[str, Any]) -> bool:
    checks = health.get("checks") if isinstance(health.get("checks"), dict) else {}
    llm_config = checks.get("llm_config") if isinstance(checks.get("llm_config"), dict) else {}
    if llm_config.get("status") == "error":
        return False
    llm_connectivity = checks.get("llm_connectivity") if isinstance(checks.get("llm_connectivity"), dict) else {}
    status = str(llm_connectivity.get("status") or "unknown")
    if status in {"unknown", "stale", "error"}:
        return True
    return "llm_connectivity" in set(gate.get("warnings") or [])


def _message_for(scope: str, blockers: list[str]) -> str:
    if "llm_config" in blockers or "llm_connectivity" in blockers:
        if scope == "game_start":
            return "模型连接不可用，不能开始游戏。"
        if scope == "benchmark_start":
            return "模型连接不可用，不能启动 Benchmark。"
        if scope == "evolution_start":
            return "模型连接不可用，不能启动进化任务。"
        return "模型连接不可用。"
    if "task_worker" in blockers:
        return "任务 worker 不可用，不能启动长任务。"
    if "artifact_root" in blockers:
        return "任务产物目录不可写，不能启动长任务。"
    return "运行环境未就绪。"
