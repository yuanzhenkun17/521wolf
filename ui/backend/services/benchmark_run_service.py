"""Benchmark run planning, queueing, and execution service."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from urllib.parse import urlparse

from fastapi import HTTPException

from app.config import load_llm_config
from app.lib.benchmark_spec import BenchmarkSpec
from app.lib.version import VersionRegistryProtocol, registry_version_release_stage
from app.util.time import beijing_now_iso
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.errors import domain_error_detail, release_stage_diagnostic
from ui.backend.schemas import BenchmarkRequest
from ui.backend.services.benchmark_catalog_service import BenchmarkCatalogService
from ui.backend.services.task_service import BackgroundTaskServiceProtocol
from ui.backend.services.benchmark_run_payloads import (
    _BENCHMARK_CURRENCY,
    _BENCHMARK_PLAYER_COUNT,
    _apply_benchmark_gates,
    _apply_benchmark_judge,
    _apply_benchmark_langfuse_config_defaults,
    _benchmark_budget_error_detail,
    _benchmark_budget_exceeded,
    _benchmark_budget_payload,
    _benchmark_concurrency_policy,
    _benchmark_effective_game_count,
    _benchmark_estimated_cost,
    _benchmark_estimated_tokens,
    _benchmark_eval_batch_id,
    _benchmark_model_runtime_payload,
    _benchmark_seed_sequence,
    _benchmark_spec_snapshot,
    _injected_model_runtime_hash_input,
    _json_clone,
    _model_identifier,
    _stable_runtime_hash,
)
from ui.backend.task_state import _set_task_contract

_BENCHMARK_QUEUE_HEARTBEAT_SECONDS = 30.0


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

    def model_for_run(
        self,
        *,
        scope: str = "game_decision",
        model_profile_id: str | None = None,
    ) -> Any | None:
        ...

    def settings_model_runtime_for_scope(
        self,
        scope: str,
        *,
        model_profile_id: str | None = None,
    ) -> dict[str, Any] | None:
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

    def model_for_benchmark_run(self, request: BenchmarkRequest) -> Any:
        model_factory = getattr(self._context, "model_for_run")
        try:
            return model_factory(
                scope="benchmark",
                model_profile_id=request.model_profile_id,
            )
        except TypeError:
            return model_factory()

    def benchmark_run_plan(self, request: BenchmarkRequest) -> dict[str, Any]:
        """Build the shared dry-run launch plan used by API and queue admission."""
        spec, seed_set = self._catalog.resolve_benchmark_spec(request)
        roles = self.benchmark_roles(request, spec)
        target_type = spec.target_type if spec else request.target_type
        self.validate_benchmark_target_versions(roles, request, target_type=target_type)
        model_runtime = self.benchmark_model_runtime(request)
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
            "model_id": model_runtime["model_id"],
            "model_config_hash": model_runtime["model_config_hash"],
            "model_runtime": _json_clone(model_runtime["model_runtime"]),
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
        model_runtime = self._benchmark_model_runtime_from_plan(run_plan) or self.benchmark_model_runtime(request)
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

    def queue_benchmark_task(self, batch: dict[str, Any], request: BenchmarkRequest) -> dict[str, Any]:
        batch_id = str(batch.get("batch_id") or "")
        if not batch_id:
            raise HTTPException(status_code=500, detail="benchmark batch is missing batch_id")
        task = self._tasks.enqueue_task(
            task_id=batch_id,
            kind="benchmark_batch",
            payload={
                "batch_id": batch_id,
                "request": request.model_dump(mode="json", exclude_none=True),
            },
            priority=50,
            idempotency_key=f"benchmark_batch:{batch_id}",
            source="ui_benchmark",
            metadata={
                "batch_id": batch_id,
                "target_type": batch.get("target_type"),
                "roles": list(batch.get("roles") or []),
                "benchmark_id": (batch.get("benchmark") or {}).get("id") if isinstance(batch.get("benchmark"), dict) else None,
            },
        )
        batch["task_id"] = task["task_id"]
        batch["task_queue_status"] = task["status"]
        self._tasks.persist_background_tasks()
        return task

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

    async def run_queued_benchmark(
        self,
        batch_id: str,
        request: BenchmarkRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        batch = self._context.evolution_batches.get(batch_id)
        if batch is None:
            return

        def queue_progress(stage: str | None = None) -> None:
            if progress_sink is None:
                return
            progress = batch.get("progress") if isinstance(batch.get("progress"), dict) else {}
            payload = dict(progress)
            if stage:
                payload["stage"] = stage
            payload["batch_id"] = batch_id
            progress_sink(payload)

        def stop_requested() -> bool:
            if cancel_check is not None and cancel_check():
                batch["stop_requested"] = True
                batch["cancelled"] = True
                batch["error"] = batch.get("error") or MANUAL_STOP_REASON
            return bool(batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "cancelled"})

        if stop_requested():
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
            queue_progress("stopped")
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
        queue_progress("preparing")
        try:
            for index, role in enumerate(roles):
                if stop_requested():
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
                queue_progress("evaluating")
                results.append(
                    await self._await_benchmark_step(
                        self._context.evaluate_benchmark_batch(
                            batch_config=self.benchmark_batch_config(batch_id, role, request, index),
                            model=self.model_for_benchmark_run(request),
                            paths=self._context.paths,
                        ),
                        batch=batch,
                        batch_id=batch_id,
                        cancel_check=cancel_check,
                        progress_sink=progress_sink,
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
                queue_progress("evaluating")
        except Exception as exc:  # pragma: no cover - defensive background failure path
            if stop_requested() or str(exc) == MANUAL_STOP_REASON:
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
                queue_progress("stopped")
                return
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
            queue_progress("failed")
            return

        if stop_requested():
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
            queue_progress("stopped")
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
        queue_progress("completed")

    async def _await_benchmark_step(
        self,
        awaitable: Awaitable[dict[str, Any]],
        *,
        batch: dict[str, Any],
        batch_id: str,
        cancel_check: Callable[[], bool] | None,
        progress_sink: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        task = asyncio.create_task(awaitable)
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(task), timeout=_BENCHMARK_QUEUE_HEARTBEAT_SECONDS)
            except TimeoutError:
                if progress_sink is not None:
                    progress = batch.get("progress") if isinstance(batch.get("progress"), dict) else {}
                    payload = dict(progress)
                    payload.setdefault("stage", batch.get("current_stage") or "evaluating")
                    payload["batch_id"] = batch_id
                    progress_sink(payload)
                if cancel_check is not None and cancel_check():
                    batch["stop_requested"] = True
                    batch["cancelled"] = True
                    batch["error"] = batch.get("error") or MANUAL_STOP_REASON
                    task.cancel()
                    try:
                        await task
                    except BaseException:  # noqa: BLE001 - cancellation cleanup must not mask manual stop
                        pass
                    raise RuntimeError(MANUAL_STOP_REASON) from None

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

    @staticmethod
    def _benchmark_model_runtime_from_plan(run_plan: dict[str, Any]) -> dict[str, Any] | None:
        runtime = run_plan.get("model_runtime") if isinstance(run_plan.get("model_runtime"), dict) else {}
        model_id = str(run_plan.get("model_id") or runtime.get("model_id") or "").strip()
        model_config_hash = str(
            run_plan.get("model_config_hash")
            or runtime.get("model_config_hash")
            or ""
        ).strip()
        if not model_id or not model_config_hash or not runtime:
            return None
        return {
            "model_id": model_id,
            "model_config_hash": model_config_hash,
            "model_runtime": _json_clone(runtime),
        }

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

        settings_resolver = getattr(self._context, "settings_model_runtime_for_scope", None)
        if callable(settings_resolver):
            try:
                settings_runtime = settings_resolver(
                    "benchmark",
                    model_profile_id=str(getattr(request, "model_profile_id", "") or "").strip() or None,
                )
            except (FileNotFoundError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail=domain_error_detail(
                        code="benchmark_model_profile_invalid",
                        message="Benchmark model profile is unavailable.",
                        detail=str(exc),
                        diagnostics=[
                            {
                                "kind": "benchmark_model_profile_invalid",
                                "model_profile_id": str(getattr(request, "model_profile_id", "") or ""),
                                "reason": str(exc),
                            }
                        ],
                    ),
                ) from exc
        else:
            settings_runtime = None
        if settings_runtime is not None:
            return settings_runtime

        try:
            cfg = load_llm_config()
            public_cfg = {
                key: cfg.get(key)
                for key in (
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
            public_cfg["base_url_host"] = _runtime_base_url_host(cfg.get("base_url"))
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


def _runtime_base_url_host(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return host
    return text.split("?", 1)[0].split("#", 1)[0].split("/")[0]


__all__ = ["BenchmarkRunService", "BenchmarkRunServiceContextProtocol"]
