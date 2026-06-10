"""Benchmark run planning, queueing, and execution service."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any, Protocol

from fastapi import HTTPException

from app.config import load_llm_config
from app.lib.benchmark_spec import BenchmarkSpec
from app.lib.version import VersionRegistryProtocol, registry_version_release_stage
from app.run import LANGFUSE_EVAL_CONFIG_KEYS
from app.util.time import beijing_now_iso
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.errors import domain_error_detail, release_stage_diagnostic
from ui.backend.schemas import BenchmarkRequest
from ui.backend.services.benchmark_catalog_service import BenchmarkCatalogService
from ui.backend.services.task_service import BackgroundTaskServiceProtocol
from ui.backend.task_state import _set_task_contract

_BENCHMARK_PLAYER_COUNT = 12
_BENCHMARK_DEFAULT_GAME_CONCURRENCY = 3
_BENCHMARK_DEFAULT_JUDGE_CONCURRENCY = 1
_BENCHMARK_GAME_UNIT_TOKENS = 1120
_BENCHMARK_JUDGE_DECISION_TOKENS = 810
_BENCHMARK_COST_PER_1K_TOKENS = 0.002
_BENCHMARK_CURRENCY = "USD"
_BENCHMARK_GAME_UNIT_SECONDS = 1.2
_BENCHMARK_JUDGE_DECISION_SECONDS = 1.0
_BENCHMARK_EVAL_BATCH_SETUP_SECONDS = 10.0


class BenchmarkRunServiceContextProtocol(Protocol):
    """Context capabilities required by ``BenchmarkRunService``."""

    paths: Any
    model: Any | None
    evolution_batches: dict[str, dict[str, Any]]

    @property
    def registry(self) -> VersionRegistryProtocol:
        ...

    @property
    def task_service(self) -> BackgroundTaskServiceProtocol:
        ...

    def model_for_run(self) -> Any | None:
        ...

    def invalidate_role_overview_cache(self) -> None:
        ...

    async def evaluate_benchmark_batch(
        self,
        *,
        batch_config: dict[str, Any],
        model: Any | None,
        paths: Any,
    ) -> dict[str, Any]:
        ...


class BenchmarkRunService:
    """Own benchmark launch planning, queue admission, and batch execution."""

    def __init__(
        self,
        context: BenchmarkRunServiceContextProtocol,
        *,
        catalog: BenchmarkCatalogService | None = None,
    ) -> None:
        self._context = context
        self._catalog = catalog or BenchmarkCatalogService(context)

    @property
    def _tasks(self) -> BackgroundTaskServiceProtocol:
        return self._context.task_service

    def plan_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        """Return a launch plan and budget estimate for a benchmark request."""
        return self.benchmark_run_plan(request)

    def benchmark_run_plan(self, request: BenchmarkRequest) -> dict[str, Any]:
        """Build the shared dry-run launch plan used by API and queue admission."""
        spec, seed_set = self._catalog.resolve_benchmark_spec(request)
        roles = self.benchmark_roles(request, spec)
        target_type = spec.target_type if spec else request.target_type
        self.validate_benchmark_target_versions(roles, request, target_type=target_type)
        if spec is not None:
            game_count = _benchmark_effective_game_count(int(spec.game_count))
            max_days = int(spec.max_days)
            judge = spec.judge.model_dump(mode="json")
            benchmark = self._catalog.benchmark_summary(spec, seed_set)
            seed_count = int(benchmark.get("seed_count") or game_count)
            seed_set_id = spec.seed_set_id
            cost_tier = str(spec.cost_tier or "standard")
        else:
            game_count = 10 if request.battle_games is None else int(request.battle_games)
            max_days = 5 if request.max_days is None else int(request.max_days)
            judge = {}
            benchmark = None
            seed_count = game_count
            seed_set_id = None
            cost_tier = "ad_hoc"

        eval_batch_count = 1 if target_type == "model" else max(1, len(roles))
        total_games = eval_batch_count * game_count
        judge_enabled = bool(judge.get("enable_decision_judge", False))
        judge_max_decisions = int(judge.get("judge_max_decisions") or 0) if judge_enabled else 0
        judge_decision_units = total_games * judge_max_decisions
        player_count = _BENCHMARK_PLAYER_COUNT
        game_decision_units = total_games * max_days * player_count
        estimated_units = game_decision_units + judge_decision_units
        estimated_tokens = _benchmark_estimated_tokens(
            game_decision_units=game_decision_units,
            judge_decision_units=judge_decision_units,
        )
        estimated_cost = _benchmark_estimated_cost(estimated_tokens)
        concurrency_policy = _benchmark_concurrency_policy(
            eval_batch_count=eval_batch_count,
            game_count=game_count,
            max_days=max_days,
            player_count=player_count,
            judge_enabled=judge_enabled,
            judge_decision_units=judge_decision_units,
            judge_concurrency=judge.get("judge_concurrency"),
        )
        expected_duration_seconds = int(concurrency_policy["expected_duration_seconds"])
        budget = _benchmark_budget_payload(
            request,
            estimated_units=estimated_units,
            estimated_tokens=estimated_tokens,
            estimated_cost=estimated_cost,
        )
        budget_exceeded = _benchmark_budget_exceeded(budget)
        warnings: list[dict[str, Any]] = []
        if budget_exceeded:
            exceeded = budget.get("exceeded") if isinstance(budget.get("exceeded"), dict) else {}
            warnings.append(
                {
                    "kind": "budget_exceeded",
                    "message": "estimated benchmark cost exceeds budget limit",
                    "estimated_units": estimated_units,
                    "limit_units": request.budget_limit_units,
                    "estimated_cost": estimated_cost,
                    "limit_cost": request.budget_limit_cost,
                    "reasons": exceeded.get("reasons", []) if isinstance(exceeded, dict) else [],
                    "evidence": exceeded.get("evidence", []) if isinstance(exceeded, dict) else [],
                }
            )
        if request.stop_after_budget_units is not None and estimated_units > int(request.stop_after_budget_units):
            warnings.append(
                {
                    "kind": "stop_after_budget_will_trigger",
                    "message": "estimated benchmark units exceed stop-after threshold",
                    "estimated_units": estimated_units,
                    "stop_after_budget_units": int(request.stop_after_budget_units),
                }
            )
        if not request.benchmark_id:
            warnings.append(
                {
                    "kind": "ad_hoc_benchmark",
                    "message": "ad-hoc benchmark is not isolated by a versioned suite",
                }
            )

        assumptions = [
            "game_decision_units = total_games * max_days * 12 players",
            "judge_decision_units = total_games * judge_max_decisions when decision judge is enabled",
            "estimated_tokens = game units and judge units multiplied by planner token assumptions",
            "estimated_cost uses planner token cost assumptions and is reported before launch",
        ]

        return {
            "kind": "benchmark_run_plan",
            "schema_version": 2,
            "dry_run": True,
            "benchmark": benchmark,
            "target_type": target_type,
            "roles": list(roles),
            "role_count": len(roles),
            "eval_batch_count": eval_batch_count,
            "game_count_per_eval_batch": game_count,
            "max_days": max_days,
            "total_games": total_games,
            "seed_set_id": seed_set_id,
            "seed_count": seed_count,
            "cost_tier": cost_tier,
            "estimated_tokens": estimated_tokens,
            "estimated_cost": estimated_cost,
            "currency": _BENCHMARK_CURRENCY,
            "expected_duration_seconds": expected_duration_seconds,
            "concurrency_policy": concurrency_policy,
            "assumptions": assumptions,
            "judge": {
                "enabled": judge_enabled,
                "max_decisions_per_game": judge_max_decisions,
                "estimated_decisions": judge_decision_units,
                "concurrency": concurrency_policy["judge_concurrency"],
                "timeout_seconds": judge.get("judge_timeout_seconds"),
            },
            "estimates": {
                "player_count": player_count,
                "game_decision_units": game_decision_units,
                "judge_decision_units": judge_decision_units,
                "estimated_llm_call_units": estimated_units,
                "estimated_tokens": estimated_tokens,
                "estimated_cost": estimated_cost,
                "currency": _BENCHMARK_CURRENCY,
                "expected_duration_seconds": expected_duration_seconds,
                "assumptions": assumptions,
            },
            "budget": budget,
            "launchable": not budget_exceeded,
            "warnings": warnings,
        }

    def queue_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        run_plan = self.benchmark_run_plan(request)
        if _benchmark_budget_exceeded(run_plan.get("budget", {})):
            raise HTTPException(status_code=422, detail=_benchmark_budget_error_detail(run_plan))
        spec, seed_set = self._catalog.resolve_benchmark_spec(request)
        benchmark_meta = self._catalog.benchmark_metadata(spec, seed_set) if spec else None
        roles = self.benchmark_roles(request, spec)
        model_runtime = self.benchmark_model_runtime(request)
        request_config = self.benchmark_request_config(request, spec)
        if spec is not None or request.target_type == "model" or request.model_id or request.model_config_hash:
            request_config["model_id"] = model_runtime["model_id"]
            request_config["model_config_hash"] = model_runtime["model_config_hash"]
            request_config["model_runtime"] = _json_clone(model_runtime["model_runtime"])
        batch_id = f"bench_{uuid.uuid4().hex[:10]}"
        now = beijing_now_iso()
        batch = {
            "kind": "benchmark_batch",
            "schema_version": 2 if spec else 1,
            "batch_id": batch_id,
            "benchmark": benchmark_meta,
            "target_type": spec.target_type if spec else request.target_type,
            "model_id": model_runtime["model_id"],
            "model_config_hash": model_runtime["model_config_hash"],
            "model_runtime": _json_clone(model_runtime["model_runtime"]),
            "roles": roles,
            "status": "running",
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "started_at": now,
            "last_heartbeat_at": now,
            "finished_at": None,
            "current_stage": "queued",
            "progress": {
                "stage": "queued",
                "percent": 0.0,
                "completed_roles": 0,
                "role_count": len(roles),
                "total_roles": len(roles),
                "updated_at": now,
            },
            "diagnostics": [],
            "config": request_config,
            "run_plan": run_plan,
            "result": None,
            "error": None,
        }
        self._context.evolution_batches[batch_id] = batch
        self._tasks.persist_background_tasks()
        return batch

    def validate_benchmark_target_versions(
        self,
        roles: list[str],
        request: BenchmarkRequest,
        *,
        target_type: str,
    ) -> None:
        """Allow explicit canary evaluation targets while keeping shadow out of benchmark runs."""
        if target_type != "role_version":
            return
        for role in roles:
            version_id = request.target_versions.get(role)
            if not version_id:
                continue
            try:
                release_stage = registry_version_release_stage(self._context.registry, role, version_id)
            except FileNotFoundError as exc:
                raise HTTPException(
                    status_code=404,
                    detail=domain_error_detail(
                        code="benchmark_target_version_not_found",
                        message="Benchmark target version was not found.",
                        detail=f"benchmark target version not found: {role}/{version_id}",
                        diagnostics=[
                            {
                                "kind": "benchmark_target_version_not_found",
                                "role": str(role),
                                "version_id": str(version_id),
                            }
                        ],
                    ),
                ) from exc
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            if str(release_stage or "").strip().lower() == "shadow":
                raise HTTPException(
                    status_code=409,
                    detail=domain_error_detail(
                        code="benchmark_target_version_not_allowed",
                        message="Benchmark target version is not allowed.",
                        detail=(
                            f"benchmark target version not allowed: {role}/{version_id} "
                            "is release_stage=shadow; promote to canary before explicit evaluation"
                        ),
                        diagnostics=[
                            release_stage_diagnostic(
                                role=role,
                                version_id=version_id,
                                release_stage="shadow",
                                kind="benchmark_target_version_not_allowed",
                                allowed_flow="benchmark_canary_or_baseline",
                            )
                        ],
                    ),
                )

    async def run_queued_benchmark(self, batch_id: str, request: BenchmarkRequest) -> None:
        batch = self._context.evolution_batches.get(batch_id)
        if batch is None:
            return
        if batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "cancelled"}:
            batch["finished_at"] = batch.get("finished_at") or beijing_now_iso()
            batch["error"] = batch.get("error") or MANUAL_STOP_REASON
            _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
            self._tasks.mark_benchmark_stage(
                batch,
                "stopped",
                status="failed",
                percent=self._tasks.task_progress_percent(batch),
                diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
            )
            self._tasks.persist_background_tasks()
            return

        if str(batch.get("target_type") or request.target_type or "role_version") == "model":
            roles: list[str | None] = [None]
        else:
            roles = [r for r in (batch.get("roles") or request.roles or []) if r] or [None]
        role_count = len(roles)
        results: list[dict[str, Any]] = []
        self._tasks.mark_benchmark_stage(
            batch,
            "preparing",
            status="running",
            percent=0.0,
            role_count=role_count,
            completed_roles=0,
        )
        self._tasks.persist_background_tasks()
        try:
            for index, role in enumerate(roles):
                if batch.get("stop_requested") or batch.get("cancelled"):
                    break
                role_label = role or "all"
                self._tasks.mark_benchmark_stage(
                    batch,
                    "evaluating",
                    status="running",
                    percent=index / role_count if role_count else 0.0,
                    role=role_label,
                    role_index=index + 1,
                    role_count=role_count,
                    completed_roles=index,
                )
                self._tasks.persist_background_tasks()
                results.append(
                    await self._context.evaluate_benchmark_batch(
                        batch_config=self.benchmark_batch_config(batch_id, role, request, index),
                        model=self._context.model_for_run(),
                        paths=self._context.paths,
                    )
                )
                self._tasks.mark_benchmark_stage(
                    batch,
                    "evaluating",
                    status="running",
                    percent=(index + 1) / role_count if role_count else 1.0,
                    role=role_label,
                    role_index=index + 1,
                    role_count=role_count,
                    completed_roles=index + 1,
                )
                self._tasks.persist_background_tasks()
        except Exception as exc:  # pragma: no cover - defensive background failure path
            batch["finished_at"] = beijing_now_iso()
            batch["error"] = str(exc)
            _set_task_contract(batch, failed=True, cancelled=False, interrupted=False)
            self._tasks.mark_benchmark_stage(
                batch,
                "failed",
                status="failed",
                percent=self._tasks.task_progress_percent(batch),
                diagnostic={
                    "kind": "benchmark_error",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                },
            )
            self._tasks.persist_background_tasks()
            return

        if batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "cancelled"}:
            batch["finished_at"] = batch.get("finished_at") or beijing_now_iso()
            batch["error"] = batch.get("error") or MANUAL_STOP_REASON
            _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
            self._tasks.mark_benchmark_stage(
                batch,
                "stopped",
                status="failed",
                percent=self._tasks.task_progress_percent(batch),
                completed_roles=len(results),
                role_count=role_count,
                diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
            )
            self._tasks.persist_background_tasks()
            return

        batch["status"] = "completed"
        _set_task_contract(batch, stop_requested=False, cancelled=False, interrupted=False, failed=False)
        batch["started_at"] = (
            (results[0].get("started_at") if results else None)
            or batch.get("started_at")
            or beijing_now_iso()
        )
        batch["finished_at"] = beijing_now_iso()
        batch["result"] = results[0] if results else None
        batch["results"] = results
        self._tasks.mark_benchmark_stage(
            batch,
            "completed",
            status="completed",
            percent=1.0,
            role_count=role_count,
            completed_roles=len(results),
        )
        self._context.invalidate_role_overview_cache()
        self._tasks.persist_background_tasks()

    def benchmark_batch_config(
        self,
        batch_id: str,
        role: str | None,
        request: BenchmarkRequest,
        index: int,
    ) -> dict[str, Any]:
        """Build an eval batch config from benchmark spec metadata or legacy request."""
        batch = self._context.evolution_batches.get(batch_id, {})
        spec_snapshot = _benchmark_spec_snapshot(batch)
        benchmark_meta = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
        target_type = str(batch.get("target_type") or request.target_type or "role_version")
        if spec_snapshot:
            game_count = _benchmark_effective_game_count(int(spec_snapshot.get("game_count", 0) or 0))
            max_days = int(spec_snapshot.get("max_days", request.max_days or 5) or request.max_days or 5)
            seed_sequence = _benchmark_seed_sequence(spec_snapshot, game_count)
            seed_start = (
                int(seed_sequence[0])
                if seed_sequence
                else int(spec_snapshot.get("seed_start", 0) or 0) + index * game_count
            )
            paired_seed = bool(spec_snapshot.get("paired_seed", True))
            gates = spec_snapshot.get("gates") if isinstance(spec_snapshot.get("gates"), dict) else {}
            judge = spec_snapshot.get("judge") if isinstance(spec_snapshot.get("judge"), dict) else {}
        else:
            game_count = 10 if request.battle_games is None else request.battle_games
            max_days = 5 if request.max_days is None else request.max_days
            seed_sequence = []
            seed_start = None
            paired_seed = False
            gates = {}
            judge = {}

        cfg: dict[str, Any] = {
            "batch_id": _benchmark_eval_batch_id(batch_id, role),
            "comparison_group_id": batch_id,
            "comparison_type": target_type,
            "scope": target_type,
            "game_count": game_count,
            "max_days": max_days,
            "paired_seed": paired_seed,
        }
        frozen_config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
        frozen_runtime = batch.get("model_runtime")
        if not isinstance(frozen_runtime, dict) or not frozen_runtime:
            frozen_runtime = frozen_config.get("model_runtime")
        if isinstance(frozen_runtime, dict) and frozen_runtime:
            cfg["model_id"] = batch.get("model_id") or frozen_config.get("model_id") or frozen_runtime.get("model_id")
            cfg["model_config_hash"] = (
                batch.get("model_config_hash")
                or frozen_config.get("model_config_hash")
                or frozen_runtime.get("model_config_hash")
            )
            cfg["model_runtime"] = _json_clone(frozen_runtime)
        else:
            model_runtime = self.benchmark_model_runtime(request)
            cfg["model_id"] = model_runtime["model_id"]
            cfg["model_config_hash"] = model_runtime["model_config_hash"]
            cfg["model_runtime"] = model_runtime["model_runtime"]
            if isinstance(batch, dict):
                batch["model_id"] = model_runtime["model_id"]
                batch["model_config_hash"] = model_runtime["model_config_hash"]
                batch["model_runtime"] = _json_clone(model_runtime["model_runtime"])
                if isinstance(batch.get("config"), dict):
                    batch["config"]["model_id"] = model_runtime["model_id"]
                    batch["config"]["model_config_hash"] = model_runtime["model_config_hash"]
                    batch["config"]["model_runtime"] = _json_clone(model_runtime["model_runtime"])
        for key, value in (
            ("evaluation_set_id", benchmark_meta.get("evaluation_set_id")),
            ("seed_set_id", benchmark_meta.get("seed_set_id")),
            ("benchmark_id", benchmark_meta.get("id")),
            ("benchmark_version", benchmark_meta.get("version")),
            ("benchmark_config_hash", benchmark_meta.get("config_hash")),
        ):
            if value is not None:
                cfg[key] = value
        _apply_benchmark_langfuse_config_defaults(cfg, frozen_config=frozen_config, request=request)
        if seed_start is not None:
            cfg["seed_start"] = seed_start
        if seed_sequence:
            cfg["seeds"] = seed_sequence
        _apply_benchmark_gates(cfg, gates)
        _apply_benchmark_judge(cfg, judge)
        for key in (
            "game_concurrency",
            "runner_game_timeout",
            "game_timeout",
            "eval_judge_concurrency",
            "judge_concurrency",
            "eval_judge_timeout_seconds",
            "judge_timeout_seconds",
        ):
            if frozen_config.get(key) is not None:
                cfg[key] = frozen_config[key]
        if role and target_type == "role_version":
            explicit_target = request.target_versions.get(role)
            if explicit_target:
                self.validate_benchmark_target_versions([role], request, target_type=target_type)
            target_version = explicit_target or self._context.registry.get_baseline(role)
            if target_version:
                cfg["target_role"] = role
                cfg["target_version_id"] = target_version
        return cfg

    def benchmark_roles(self, request: BenchmarkRequest, spec: BenchmarkSpec | None) -> list[str]:
        if spec is None:
            return list(request.roles)
        if spec.target_type == "model":
            return list(spec.roles)
        if not request.roles:
            return list(spec.roles)
        allowed = set(spec.roles)
        unsupported = [role for role in request.roles if role not in allowed]
        if unsupported:
            raise HTTPException(
                status_code=422,
                detail=f"roles not in benchmark spec: {', '.join(unsupported)}",
            )
        return list(request.roles)

    @staticmethod
    def benchmark_request_config(request: BenchmarkRequest, spec: BenchmarkSpec | None = None) -> dict[str, Any]:
        payload = request.model_dump(exclude_none=True)
        if spec is not None:
            payload["target_type"] = spec.target_type
        if not payload.get("target_versions"):
            payload.pop("target_versions", None)
        if payload.get("target_type") == "role_version" and not payload.get("benchmark_id"):
            payload.pop("target_type", None)
        return payload

    def benchmark_model_runtime(self, request: BenchmarkRequest | None = None) -> dict[str, Any]:
        """Return model identity used to attribute model-scope benchmark runs."""
        request_model_id = str(getattr(request, "model_id", "") or "").strip() if request else ""
        request_config_hash = str(getattr(request, "model_config_hash", "") or "").strip() if request else ""
        if request_model_id and request_config_hash:
            return _benchmark_model_runtime_payload(
                source="request",
                model_id=request_model_id,
                model_config_hash=request_config_hash,
                hash_input=None,
                hash_provided=True,
            )

        model = self._context.model
        if model is not None:
            model_id = request_model_id or _model_identifier(model) or model.__class__.__name__
            hash_input = _injected_model_runtime_hash_input(model, model_id=model_id)
            runtime_hash = request_config_hash or _stable_runtime_hash(hash_input)
            return _benchmark_model_runtime_payload(
                source="injected_model",
                model_id=model_id,
                model_config_hash=runtime_hash,
                hash_input=hash_input,
                hash_provided=bool(request_config_hash),
            )

        use_fake = os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}
        if use_fake:
            model_id = request_model_id or "ui-backend-fake-llm"
            hash_input = {"source": "fake", "model_id": model_id}
            return _benchmark_model_runtime_payload(
                source="fake",
                model_id=model_id,
                model_config_hash=request_config_hash or _stable_runtime_hash(hash_input),
                hash_input=hash_input,
                hash_provided=bool(request_config_hash),
            )

        try:
            cfg = load_llm_config()
            public_cfg = {
                key: cfg.get(key)
                for key in (
                    "base_url",
                    "model",
                    "timeout",
                    "temperature",
                    "thinking",
                    "max_retries",
                    "runtime_max_attempts",
                    "runtime_timeout",
                    "runtime_retry_initial_delay",
                    "runtime_retry_max_delay",
                    "runtime_circuit_failures",
                    "runtime_circuit_cooldown",
                )
            }
            model_id = request_model_id or str(cfg.get("model") or "configured-llm")
            public_cfg["model"] = model_id
            public_cfg["source"] = "configured_llm"
            return _benchmark_model_runtime_payload(
                source="configured_llm",
                model_id=model_id,
                model_config_hash=request_config_hash or _stable_runtime_hash(public_cfg),
                hash_input=public_cfg,
                hash_provided=bool(request_config_hash),
            )
        except RuntimeError:
            model_id = request_model_id or "ui-backend-fallback-llm"
            hash_input = {"source": "fallback", "model_id": model_id}
            return _benchmark_model_runtime_payload(
                source="fallback",
                model_id=model_id,
                model_config_hash=request_config_hash or _stable_runtime_hash(hash_input),
                hash_input=hash_input,
                hash_provided=bool(request_config_hash),
            )


def _ceil_div(numerator: int, denominator: int) -> int:
    if numerator <= 0:
        return 0
    safe_denominator = max(1, int(denominator or 1))
    return (int(numerator) + safe_denominator - 1) // safe_denominator


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _rounded_cost(value: Any) -> float:
    try:
        return round(float(value or 0.0), 6)
    except (TypeError, ValueError):
        return 0.0


def _benchmark_estimated_tokens(*, game_decision_units: int, judge_decision_units: int) -> int:
    return (
        int(game_decision_units or 0) * _BENCHMARK_GAME_UNIT_TOKENS
        + int(judge_decision_units or 0) * _BENCHMARK_JUDGE_DECISION_TOKENS
    )


def _benchmark_estimated_cost(estimated_tokens: int) -> float:
    return _rounded_cost((int(estimated_tokens or 0) / 1000.0) * _BENCHMARK_COST_PER_1K_TOKENS)


def _benchmark_concurrency_policy(
    *,
    eval_batch_count: int,
    game_count: int,
    max_days: int,
    player_count: int,
    judge_enabled: bool,
    judge_decision_units: int,
    judge_concurrency: Any,
) -> dict[str, Any]:
    game_concurrency = max(1, min(_BENCHMARK_DEFAULT_GAME_CONCURRENCY, max(1, int(game_count or 1))))
    effective_judge_concurrency = 0
    if judge_enabled:
        effective_judge_concurrency = _positive_int(judge_concurrency) or _BENCHMARK_DEFAULT_JUDGE_CONCURRENCY
    game_units_per_eval_batch = int(game_count or 0) * int(max_days or 0) * int(player_count or 0)
    game_waves_per_eval_batch = _ceil_div(game_units_per_eval_batch, game_concurrency)
    judge_waves = _ceil_div(int(judge_decision_units or 0), effective_judge_concurrency) if judge_enabled else 0
    expected_duration_seconds = round(
        int(eval_batch_count or 0) * _BENCHMARK_EVAL_BATCH_SETUP_SECONDS
        + game_waves_per_eval_batch * int(eval_batch_count or 0) * _BENCHMARK_GAME_UNIT_SECONDS
        + judge_waves * _BENCHMARK_JUDGE_DECISION_SECONDS
    )
    return {
        "policy": "bounded_sequential_eval_batches",
        "role_batch_concurrency": 1,
        "eval_batch_count": int(eval_batch_count or 0),
        "game_concurrency": game_concurrency,
        "judge_concurrency": effective_judge_concurrency,
        "judge_enabled": bool(judge_enabled),
        "game_waves_per_eval_batch": game_waves_per_eval_batch,
        "judge_waves": judge_waves,
        "expected_duration_seconds": max(0, int(expected_duration_seconds)),
        "notes": [
            "role-version benchmarks run one evaluation batch per role",
            "model benchmarks run one full-role evaluation batch",
            "games inside each evaluation batch use bounded game concurrency",
        ],
    }


def _benchmark_budget_payload(
    request: BenchmarkRequest,
    *,
    estimated_units: int,
    estimated_tokens: int,
    estimated_cost: float,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    reasons: list[str] = []
    if request.budget_limit_units is not None and int(estimated_units) > int(request.budget_limit_units):
        reasons.append("estimated_units_exceed_limit_units")
        evidence.append(
            {
                "metric": "estimated_units",
                "estimated": int(estimated_units),
                "limit": int(request.budget_limit_units),
                "delta": int(estimated_units) - int(request.budget_limit_units),
                "unit": "llm_call_unit",
            }
        )
    if request.budget_limit_cost is not None and float(estimated_cost) > float(request.budget_limit_cost):
        reasons.append("estimated_cost_exceed_limit_cost")
        evidence.append(
            {
                "metric": "estimated_cost",
                "estimated": _rounded_cost(estimated_cost),
                "limit": _rounded_cost(request.budget_limit_cost),
                "delta": _rounded_cost(float(estimated_cost) - float(request.budget_limit_cost)),
                "unit": _BENCHMARK_CURRENCY,
            }
        )
    return {
        "limit_units": request.budget_limit_units,
        "estimated_units": int(estimated_units),
        "limit_cost": _rounded_cost(request.budget_limit_cost) if request.budget_limit_cost is not None else None,
        "estimated_cost": _rounded_cost(estimated_cost),
        "estimated_tokens": int(estimated_tokens),
        "currency": _BENCHMARK_CURRENCY,
        "stop_after_budget_units": request.stop_after_budget_units,
        "stop_after_predicted": (
            request.stop_after_budget_units is not None
            and int(estimated_units) > int(request.stop_after_budget_units)
        ),
        "exceeded": {
            "value": bool(evidence),
            "reasons": reasons,
            "evidence": evidence,
        },
    }


def _benchmark_budget_exceeded(budget: dict[str, Any]) -> bool:
    exceeded = budget.get("exceeded")
    if isinstance(exceeded, dict):
        return bool(exceeded.get("value"))
    return bool(exceeded)


def _benchmark_budget_error_detail(run_plan: dict[str, Any]) -> dict[str, Any]:
    budget = run_plan.get("budget") if isinstance(run_plan.get("budget"), dict) else {}
    exceeded = budget.get("exceeded") if isinstance(budget.get("exceeded"), dict) else {}
    return domain_error_detail(
        code="benchmark_budget_exceeded",
        message="Benchmark budget exceeded.",
        detail={
            "message": "benchmark budget exceeded",
            "estimated": {
                "units": budget.get("estimated_units"),
                "tokens": budget.get("estimated_tokens"),
                "cost": budget.get("estimated_cost"),
                "currency": budget.get("currency"),
            },
            "limit": {
                "units": budget.get("limit_units"),
                "cost": budget.get("limit_cost"),
                "currency": budget.get("currency"),
            },
            "budget": budget,
        },
        diagnostics=[
            {
                "kind": "budget_exceeded",
                "estimated_units": budget.get("estimated_units"),
                "limit_units": budget.get("limit_units"),
                "estimated_tokens": budget.get("estimated_tokens"),
                "estimated_cost": budget.get("estimated_cost"),
                "limit_cost": budget.get("limit_cost"),
                "currency": budget.get("currency"),
                "reasons": exceeded.get("reasons", []) if isinstance(exceeded, dict) else [],
                "evidence": exceeded.get("evidence", []) if isinstance(exceeded, dict) else [],
            }
        ],
    )


def _benchmark_effective_game_count(spec_game_count: int) -> int:
    return max(0, int(spec_game_count or 0))


def _benchmark_eval_batch_id(batch_id: str, role: str | None) -> str:
    return f"{batch_id}_{role}" if role else batch_id


def _apply_benchmark_langfuse_config_defaults(
    cfg: dict[str, Any],
    *,
    frozen_config: dict[str, Any],
    request: BenchmarkRequest,
) -> None:
    for key in LANGFUSE_EVAL_CONFIG_KEYS:
        value = _optional_text(frozen_config.get(key)) or _optional_text(getattr(request, key, None))
        if value is not None:
            cfg[key] = value

    evaluation_set_id = _optional_text(cfg.get("evaluation_set_id"))
    benchmark_id = _optional_text(cfg.get("benchmark_id"))
    if _optional_text(cfg.get("langfuse_dataset_name")) is None and evaluation_set_id is not None:
        cfg["langfuse_dataset_name"] = evaluation_set_id
    if _optional_text(cfg.get("langfuse_experiment_name")) is None:
        experiment_name = benchmark_id or evaluation_set_id
        if experiment_name is not None:
            cfg["langfuse_experiment_name"] = experiment_name
    if _optional_text(cfg.get("langfuse_run_name")) is None:
        run_name = _optional_text(cfg.get("batch_id"))
        if run_name is not None:
            cfg["langfuse_run_name"] = run_name


def _benchmark_spec_snapshot(batch: dict[str, Any]) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    snapshot = benchmark.get("spec_snapshot") if isinstance(benchmark.get("spec_snapshot"), dict) else {}
    return dict(snapshot)


def _benchmark_seed_sequence(spec_snapshot: dict[str, Any], game_count: int) -> list[int]:
    seeds = spec_snapshot.get("seeds")
    if not isinstance(seeds, list):
        return []
    normalized: list[int] = []
    for item in seeds[:game_count]:
        try:
            normalized.append(int(item))
        except (TypeError, ValueError):
            continue
    return normalized if len(normalized) >= game_count else []


def _apply_benchmark_gates(cfg: dict[str, Any], gates: dict[str, Any]) -> None:
    if not gates:
        return
    if gates.get("min_completed_games") is not None:
        cfg["data_sufficient_min_games"] = gates["min_completed_games"]
        cfg["leaderboard_min_games"] = gates["min_completed_games"]
    if gates.get("min_valid_game_rate") is not None:
        cfg["data_sufficient_min_valid_game_rate"] = gates["min_valid_game_rate"]
        cfg["leaderboard_min_valid_game_rate"] = gates["min_valid_game_rate"]
    if gates.get("max_llm_error_rate") is not None:
        cfg["max_llm_error_rate"] = gates["max_llm_error_rate"]
        cfg["leaderboard_llm_error_rate_ceiling"] = gates["max_llm_error_rate"]
    if gates.get("max_fallback_rate") is not None:
        cfg["max_fallback_rate"] = gates["max_fallback_rate"]
        cfg["leaderboard_fallback_rate_ceiling"] = gates["max_fallback_rate"]
    if gates.get("max_policy_adjusted_rate") is not None:
        cfg["max_policy_adjusted_rate"] = gates["max_policy_adjusted_rate"]
        cfg["leaderboard_policy_adjusted_rate_ceiling"] = gates["max_policy_adjusted_rate"]


def _apply_benchmark_judge(cfg: dict[str, Any], judge: dict[str, Any]) -> None:
    if not judge:
        return
    if judge.get("enable_decision_judge") is not None:
        cfg["eval_decision_judge"] = bool(judge.get("enable_decision_judge"))
    if judge.get("judge_max_decisions") is not None:
        cfg["eval_judge_max_decisions"] = judge["judge_max_decisions"]
    if judge.get("judge_concurrency") is not None:
        cfg["eval_judge_concurrency"] = judge["judge_concurrency"]
    if judge.get("judge_timeout_seconds") is not None:
        cfg["eval_judge_timeout_seconds"] = judge["judge_timeout_seconds"]


def _model_identifier(model: Any) -> str | None:
    for attr in ("model_name", "model", "model_id", "deployment_name", "azure_deployment", "name"):
        value = getattr(model, attr, None)
        if value:
            return str(value)
    return None


def _runtime_public_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        values: list[Any] = []
        for item in value:
            public_item = _runtime_public_value(item)
            if public_item is not None:
                values.append(public_item)
        return values
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key or "").strip()
            if not key_text or any(secret in key_text.lower() for secret in ("key", "secret", "token", "password")):
                continue
            public_item = _runtime_public_value(item)
            if public_item is not None:
                sanitized[key_text] = public_item
        return sanitized
    return str(value)


def _injected_model_runtime_hash_input(model: Any, *, model_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source": "injected_model",
        "model_id": model_id,
        "class": f"{model.__class__.__module__}.{model.__class__.__qualname__}",
    }
    for attr in (
        "temperature",
        "top_p",
        "max_tokens",
        "timeout",
        "request_timeout",
        "max_retries",
        "model_kwargs",
    ):
        value = getattr(model, attr, None)
        public_value = _runtime_public_value(value)
        if public_value not in (None, "", {}, []):
            payload[attr] = public_value
    return payload


def _benchmark_model_runtime_payload(
    *,
    source: str,
    model_id: str,
    model_config_hash: str,
    hash_input: dict[str, Any] | None,
    hash_provided: bool,
) -> dict[str, Any]:
    runtime = {
        "schema_version": 1,
        "source": source,
        "hash_source": source,
        "hash_algorithm": "sha256",
        "hash_input_schema_version": 1,
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "hash_provided": bool(hash_provided),
        "externally_provided": bool(hash_provided),
        "hash_input": _json_clone(hash_input or {}),
    }
    return {
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "model_runtime": runtime,
    }


def _stable_runtime_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


__all__ = ["BenchmarkRunService", "BenchmarkRunServiceContextProtocol"]
