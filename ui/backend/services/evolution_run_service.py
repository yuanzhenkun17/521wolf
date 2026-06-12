"""Evolution run queueing, progress, and background execution service."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import HTTPException

from app.util.json import to_jsonable
from app.util.time import beijing_now_iso
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.errors import domain_error_detail
from ui.backend.evolution_serializers import _evolution_gate_report
from ui.backend.preflight import require_runtime_ready
from ui.backend.schemas import EvolutionStartRequest, automatic_evolution_request
from ui.backend.settings_runtime_variables import (
    EVOLUTION_ROLE_CONCURRENCY_KEY,
    WORKFLOW_GAME_CONCURRENCY_KEY,
    runtime_setting_int_for_store,
)
from ui.backend.services.evolution_read_service import EvolutionReadService
from ui.backend.task_state import _set_task_contract

MAX_EVOLUTION_ROLE_CONCURRENCY = 4

_EVOLUTION_STAGE_START = {
    "queued": 0.0,
    "init": 0.0,
    "training": 0.0,
    "consolidating": 0.45,
    "applying": 0.60,
    "scenario_replay": 0.70,
    "battling": 0.70,
    "decide": 0.95,
    "reviewing": 1.0,
    "promoted": 1.0,
    "rejected": 1.0,
    "completed": 1.0,
}


class EvolutionRunService:
    """Own evolution run lifecycle while BackendStore remains the composition root."""

    def __init__(self, context: Any) -> None:
        self._context = context

    def __getattr__(self, name: str) -> Any:
        return getattr(self._context, name)

    def evolution_model_runtime(self, request: EvolutionStartRequest) -> dict[str, Any] | None:
        resolver = getattr(self._context, "settings_model_runtime_for_scope", None)
        if not callable(resolver):
            return None
        try:
            return resolver(
                "evolution",
                model_profile_id=str(request.model_profile_id or "").strip() or None,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail=domain_error_detail(
                    code="evolution_model_profile_invalid",
                    message="Evolution model profile is unavailable.",
                    detail=str(exc),
                    diagnostics=[
                        {
                            "kind": "evolution_model_profile_invalid",
                            "model_profile_id": str(request.model_profile_id or ""),
                            "reason": str(exc),
                        }
                    ],
                ),
            ) from exc

    def model_for_evolution_run(self, request: EvolutionStartRequest) -> Any:
        model_factory = getattr(self._context, "model_for_run")
        try:
            return model_factory(
                scope="evolution",
                model_profile_id=request.model_profile_id,
            )
        except TypeError:
            return model_factory()

    def queue_evolution(self, request: EvolutionStartRequest) -> dict[str, Any]:
        request = automatic_evolution_request(request)
        roles = request.roles or ["villager"]
        request_config = request.model_dump(exclude_none=True)
        workflow_game_concurrency = self.workflow_game_concurrency()
        if workflow_game_concurrency is not None:
            request_config["game_concurrency"] = workflow_game_concurrency
        request_config["role_concurrency"] = self.configured_evolution_role_concurrency(request_config)
        model_runtime = self.evolution_model_runtime(request)
        if model_runtime is not None:
            request_config["model_id"] = model_runtime["model_id"]
            request_config["model_config_hash"] = model_runtime["model_config_hash"]
            request_config["model_runtime"] = to_jsonable(dict(model_runtime["model_runtime"]))
        if len(roles) == 1:
            return self.create_evolution_run(roles[0], request, model_runtime=model_runtime)

        batch_id = f"evo_batch_{uuid.uuid4().hex[:10]}"
        now = beijing_now_iso()
        batch = {
            "kind": "role_evolution_batch",
            "schema_version": 1,
            "batch_id": batch_id,
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
            "overall_progress": {
                "stage": "queued",
                "percent": 0.0,
                "completed_roles": 0,
                "role_count": len(roles),
                "total_roles": len(roles),
                "updated_at": now,
            },
            "diagnostics": [],
            "runs": [],
            "run_summaries": [],
            "config": request_config,
        }
        if model_runtime is not None:
            batch["model_id"] = model_runtime["model_id"]
            batch["model_config_hash"] = model_runtime["model_config_hash"]
            batch["model_runtime"] = to_jsonable(dict(model_runtime["model_runtime"]))
        self.evolution_batches[batch_id] = batch
        for role in roles:
            run = self.create_evolution_run(role, request, batch_id=batch_id, status="queued", model_runtime=model_runtime)
            batch["runs"].append(run["run_id"])
        self._persist_background_tasks()
        return batch

    def queue_evolution_task(self, queued: dict[str, Any], request: EvolutionStartRequest) -> dict[str, Any]:
        task_id = str(queued.get("batch_id") or queued.get("run_id") or "")
        if not task_id:
            raise RuntimeError("queued evolution entity is missing run_id/batch_id")
        kind = "evolution_batch" if queued.get("batch_id") else "evolution_run"
        self.mark_evolution_task_queued(queued, task_id=task_id, task_queue_status="queued")
        task = self.task_service.enqueue_task(
            task_id=task_id,
            kind=kind,
            payload={
                "batch_id": queued.get("batch_id"),
                "run_id": queued.get("run_id"),
                "request": request.model_dump(mode="json", exclude_none=True),
                "snapshot": self.evolution_task_snapshot(queued),
            },
            priority=40,
            idempotency_key=f"{kind}:{task_id}",
            source="ui_evolution",
            metadata={
                "roles": list(queued.get("roles") or ([queued.get("role")] if queued.get("role") else [])),
                "kind": queued.get("kind"),
            },
        )
        self.mark_evolution_task_queued(
            queued,
            task_id=str(task["task_id"]),
            task_queue_status=str(task["status"]),
        )
        self._persist_background_tasks()
        return task

    def mark_evolution_task_queued(
        self,
        queued: dict[str, Any],
        *,
        task_id: str,
        task_queue_status: str,
    ) -> None:
        entities = [queued]
        if queued.get("batch_id"):
            for run_id in queued.get("runs", []) or []:
                run = self.evolution_runs.get(str(run_id))
                if isinstance(run, dict):
                    entities.append(run)
        for entity in entities:
            entity["task_id"] = task_id
            entity["task_queue_status"] = task_queue_status
            if str(task_queue_status).lower() == "queued":
                entity["status"] = "queued"
                entity["current_stage"] = "queued"
                progress = entity.get("progress")
                progress = dict(progress) if isinstance(progress, dict) else {}
                progress["stage"] = "queued"
                progress.setdefault("percent", 0.0)
                progress["updated_at"] = beijing_now_iso()
                entity["progress"] = progress
                if isinstance(entity.get("overall_progress"), dict):
                    entity["overall_progress"] = dict(entity["overall_progress"])
                    entity["overall_progress"]["stage"] = "queued"
                    entity["overall_progress"]["updated_at"] = progress["updated_at"]
                _set_task_contract(entity, stop_requested=False, cancelled=False, interrupted=False, failed=False)

    def evolution_task_snapshot(self, queued: dict[str, Any]) -> dict[str, Any]:
        if queued.get("batch_id"):
            run_ids = [str(run_id) for run_id in queued.get("runs", []) or []]
            return {
                "batch": to_jsonable(dict(queued)),
                "runs": [
                    to_jsonable(dict(self.evolution_runs[run_id]))
                    for run_id in run_ids
                    if run_id in self.evolution_runs
                ],
            }
        run_id = str(queued.get("run_id") or "")
        run = self.evolution_runs.get(run_id, queued)
        return {"run": to_jsonable(dict(run))}

    def task_executors(self) -> dict[str, Any]:
        return {
            "evolution_run": self.execute_evolution_task,
            "evolution_batch": self.execute_evolution_task,
        }

    def execute_evolution_task(self, task: dict[str, Any], context: Any) -> dict[str, Any]:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        request = automatic_evolution_request(EvolutionStartRequest.model_validate(request_payload))
        asyncio.run(
            require_runtime_ready(
                self._context,
                scope="evolution_start",
                model_scope="evolution",
                model_profile_id=request.model_profile_id,
            )
        )
        batch_id = str(payload.get("batch_id") or "")
        run_id = str(payload.get("run_id") or "")
        task_id = batch_id or run_id or str(task.get("task_id") or "")
        self.restore_evolution_task_snapshot(
            payload=payload,
            request=request,
            task_id=task_id,
            batch_id=batch_id,
            run_id=run_id,
        )
        context.heartbeat(progress={"stage": "evolution_running", "task_id": task_id})
        def progress_sink(progress: dict[str, Any]) -> None:
            payload = dict(progress)
            payload.setdefault("stage", "evolution_running")
            payload["task_id"] = task_id
            context.heartbeat(progress=payload)

        def task_cancel_requested() -> bool:
            entity = self.evolution_batches.get(batch_id) if batch_id else self.evolution_runs.get(run_id)
            if isinstance(entity, dict):
                progress_sink(self.evolution_queue_progress(entity, task_id=task_id))
            return bool(context.cancel_requested())

        if batch_id:
            asyncio.run(
                self.run_queued_evolution_batch(
                    batch_id,
                    request,
                    cancel_check=task_cancel_requested,
                    progress_sink=progress_sink,
                )
            )
            entity = self.evolution_batches.get(batch_id, {})
        else:
            asyncio.run(
                self.run_queued_evolution(
                    run_id,
                    request,
                    cancel_check=task_cancel_requested,
                    progress_sink=progress_sink,
                )
            )
            entity = self.evolution_runs.get(run_id, {})
        artifacts = self.persist_evolution_task_artifacts(task_id, entity)
        return {
            "task_id": task_id,
            "status": entity.get("status") if isinstance(entity, dict) else None,
            "artifact_ids": [artifact["artifact_id"] for artifact in artifacts],
        }

    def restore_evolution_task_snapshot(
        self,
        *,
        payload: dict[str, Any],
        request: EvolutionStartRequest,
        task_id: str,
        batch_id: str,
        run_id: str,
    ) -> None:
        snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
        restored = False
        if batch_id:
            batch_snapshot = snapshot.get("batch") if isinstance(snapshot.get("batch"), dict) else {}
            if batch_id not in self.evolution_batches and batch_snapshot:
                self.evolution_batches[batch_id] = dict(batch_snapshot)
                restored = True
            runs = snapshot.get("runs") if isinstance(snapshot.get("runs"), list) else []
            for item in runs:
                if not isinstance(item, dict):
                    continue
                child_run_id = str(item.get("run_id") or "")
                if child_run_id and child_run_id not in self.evolution_runs:
                    self.evolution_runs[child_run_id] = dict(item)
                    restored = True
            batch = self.evolution_batches.get(batch_id)
            roles = request.roles or []
            if isinstance(batch, dict):
                for index, child_run_id in enumerate([str(item) for item in batch.get("runs", []) or []]):
                    if child_run_id in self.evolution_runs:
                        continue
                    role = roles[index] if index < len(roles) else "villager"
                    self.create_evolution_run(
                        role,
                        request,
                        batch_id=batch_id,
                        run_id=child_run_id,
                        status="queued",
                    )
                    restored = True
        elif run_id and run_id not in self.evolution_runs:
            run_snapshot = snapshot.get("run") if isinstance(snapshot.get("run"), dict) else {}
            if run_snapshot:
                self.evolution_runs[run_id] = dict(run_snapshot)
                restored = True
            else:
                role = (request.roles or ["villager"])[0]
                self.create_evolution_run(role, request, run_id=run_id, status="queued")
                restored = True
        if restored:
            entity = self.evolution_batches.get(batch_id) if batch_id else self.evolution_runs.get(run_id)
            if isinstance(entity, dict):
                self.mark_evolution_task_queued(
                    entity,
                    task_id=task_id,
                    task_queue_status="running",
                )
            self._persist_background_tasks()

    def persist_evolution_task_artifacts(self, task_id: str, entity: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(entity, dict) or not task_id:
            return []
        artifacts = [
            self.task_service.put_task_json_artifact(
                task_id=task_id,
                name="evolution-result.json",
                payload=entity,
                artifact_type="evolution_result",
                metadata={
                    "status": entity.get("status"),
                    "kind": entity.get("kind"),
                    "run_id": entity.get("run_id"),
                    "batch_id": entity.get("batch_id"),
                },
            )
        ]
        diagnostics = self.evolution_task_diagnostics(entity)
        if diagnostics:
            artifacts.append(
                self.task_service.put_task_json_artifact(
                    task_id=task_id,
                    name="diagnostics.json",
                    payload=diagnostics,
                    artifact_type="evolution_diagnostics",
                    metadata={
                        "status": entity.get("status"),
                        "kind": entity.get("kind"),
                    },
                )
            )
        for name, artifact_type, payload in self.evolution_task_structured_artifacts(entity):
            artifacts.append(
                self.task_service.put_task_json_artifact(
                    task_id=task_id,
                    name=name,
                    payload=payload,
                    artifact_type=artifact_type,
                    metadata={
                        "status": entity.get("status"),
                        "kind": entity.get("kind"),
                        "run_id": entity.get("run_id"),
                        "batch_id": entity.get("batch_id"),
                    },
                )
            )
        return artifacts

    def evolution_task_diagnostics(self, entity: dict[str, Any]) -> list[dict[str, Any]]:
        diagnostics: list[dict[str, Any]] = []
        raw = entity.get("diagnostics")
        if isinstance(raw, list):
            diagnostics.extend([dict(item) for item in raw if isinstance(item, dict)])
        if entity.get("kind") == "role_evolution_batch":
            for run_id in entity.get("runs", []) or []:
                run = self.evolution_runs.get(str(run_id))
                if not isinstance(run, dict):
                    continue
                for item in run.get("diagnostics", []) or []:
                    if isinstance(item, dict):
                        diagnostic = dict(item)
                        diagnostic.setdefault("run_id", str(run_id))
                        diagnostic.setdefault("role", run.get("role"))
                        diagnostics.append(diagnostic)
        return diagnostics

    def evolution_task_structured_artifacts(self, entity: dict[str, Any]) -> list[tuple[str, str, Any]]:
        children = self.evolution_task_child_runs(entity)
        if children:
            return self.evolution_batch_structured_artifacts(entity, children)
        return self.evolution_run_structured_artifacts(entity)

    def evolution_task_child_runs(self, entity: dict[str, Any]) -> list[dict[str, Any]]:
        if entity.get("kind") != "role_evolution_batch":
            return []
        runs: list[dict[str, Any]] = []
        for run_id in entity.get("runs", []) or []:
            run = self.evolution_runs.get(str(run_id))
            if isinstance(run, dict):
                runs.append(run)
        return runs

    def evolution_batch_structured_artifacts(
        self,
        batch: dict[str, Any],
        children: list[dict[str, Any]],
    ) -> list[tuple[str, str, Any]]:
        grouped: dict[str, tuple[str, list[Any]]] = {
            "gate-report.json": ("evolution_gate_report", []),
            "trust-bundle.json": ("evolution_trust_bundle", []),
            "paired-seed-battle-table.json": ("evolution_paired_seed_battle_table", []),
            "scenario-replay-report.json": ("evolution_scenario_replay_report", []),
        }
        for run in children:
            for name, _artifact_type, payload in self.evolution_run_structured_artifacts(run):
                grouped[name][1].append(payload)
        artifacts: list[tuple[str, str, dict[str, Any]]] = []
        for name, (artifact_type, payloads) in grouped.items():
            if not payloads:
                continue
            artifacts.append(
                (
                    name,
                    artifact_type,
                    {
                        "kind": f"{artifact_type}s",
                        "schema_version": 1,
                        "batch_id": batch.get("batch_id"),
                        "status": batch.get("status"),
                        "count": len(payloads),
                        "items": payloads,
                    },
                )
            )
        return artifacts

    def evolution_run_structured_artifacts(self, run: dict[str, Any]) -> list[tuple[str, str, Any]]:
        artifacts: list[tuple[str, str, Any]] = []
        gate_report = self.evolution_gate_report_artifact(run)
        if gate_report is not None:
            artifacts.append(("gate-report.json", "evolution_gate_report", gate_report))
        trust_bundle = self.evolution_trust_bundle_artifact(run)
        if trust_bundle is not None:
            artifacts.append(("trust-bundle.json", "evolution_trust_bundle", trust_bundle))
        paired_table = self.evolution_paired_seed_battle_table_artifact(run)
        if paired_table is not None:
            artifacts.append(("paired-seed-battle-table.json", "evolution_paired_seed_battle_table", paired_table))
        replay_report = self.evolution_scenario_replay_report_artifact(run)
        if replay_report is not None:
            artifacts.append(("scenario-replay-report.json", "evolution_scenario_replay_report", replay_report))
        return artifacts

    def evolution_gate_report_artifact(self, run: dict[str, Any]) -> dict[str, Any] | None:
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
        report = _first_mapping(
            run.get("gate_report"),
            result.get("gate_report"),
            battle.get("gate_report"),
            run.get("promotion_gate"),
            battle.get("promotion_gate"),
        )
        if report is not None:
            return to_jsonable(dict(report))
        summary = _evolution_gate_report(run)
        if _non_empty_mapping(summary.get("raw")) or _non_empty_mapping(summary.get("release_gate")):
            return to_jsonable(dict(summary))
        return None

    def evolution_trust_bundle_artifact(self, run: dict[str, Any]) -> dict[str, Any] | None:
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
        bundle = _first_mapping(run.get("trust_bundle"), result.get("trust_bundle"), battle.get("trust_bundle"))
        if bundle is not None:
            return to_jsonable(dict(bundle))
        payload = EvolutionReadService.trust_bundle_payload_from_run(run)
        if payload is None:
            return None
        bundle = payload.get("trust_bundle") if isinstance(payload.get("trust_bundle"), dict) else None
        return to_jsonable(dict(bundle)) if bundle is not None else None

    def evolution_paired_seed_battle_table_artifact(self, run: dict[str, Any]) -> list[dict[str, Any]] | None:
        battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
        pairs = _first_list(
            run.get("paired_seed_battle_table"),
            run.get("paired_seed_pairs"),
            run.get("paired_seeds"),
            run.get("battle_pairs"),
            battle.get("paired_seed_battle_table"),
            battle.get("paired_seed_pairs"),
            battle.get("paired_seeds"),
            battle.get("battle_pairs"),
        )
        if not pairs:
            return None
        return [to_jsonable(dict(item)) for item in pairs if isinstance(item, dict)]

    def evolution_scenario_replay_report_artifact(self, run: dict[str, Any]) -> dict[str, Any] | None:
        result = run.get("result") if isinstance(run.get("result"), dict) else {}
        battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
        gate = run.get("gate_report") if isinstance(run.get("gate_report"), dict) else {}
        report = _first_mapping(
            run.get("scenario_replay_report"),
            run.get("scenario_replay"),
            result.get("scenario_replay_report"),
            result.get("scenario_replay"),
            gate.get("scenario_replay_report"),
            gate.get("scenario_replay"),
            battle.get("scenario_replay_report"),
            battle.get("scenario_replay"),
        )
        if report is None:
            return None
        return to_jsonable(dict(report))

    def create_evolution_run(
        self,
        role: str,
        request: EvolutionStartRequest,
        *,
        batch_id: str | None = None,
        run_id: str | None = None,
        status: str = "running",
        model_runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = run_id or f"evolve_{role}_{uuid.uuid4().hex[:8]}"
        now = beijing_now_iso()
        stage = "queued"
        request_config = request.model_dump(exclude_none=True)
        workflow_game_concurrency = self.workflow_game_concurrency()
        if workflow_game_concurrency is not None:
            request_config["game_concurrency"] = workflow_game_concurrency
        if model_runtime is not None:
            request_config["model_id"] = model_runtime["model_id"]
            request_config["model_config_hash"] = model_runtime["model_config_hash"]
            request_config["model_runtime"] = to_jsonable(dict(model_runtime["model_runtime"]))
        run = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": run_id,
            "batch_id": batch_id,
            "role": role,
            "status": status,
            "stop_requested": False,
            "cancelled": False,
            "interrupted": False,
            "failed": False,
            "started_at": now,
            "last_heartbeat_at": now,
            "finished_at": None,
            "current_stage": stage,
            "parent_hash": f"baseline_{role}",
            "candidate_hash": None,
            "training_games": [],
            "training_game_count": int(request.training_games or 0),
            "training_completed": 0,
            "battle_games": [],
            "battle_game_count": int(request.battle_games or 0),
            "battle_completed": 0,
            "battle_result": {},
            "proposals": [],
            "diff": [],
            "errors": [],
            "diagnostics": [],
            "warnings": [],
            "progress": {
                "stage": stage,
                "percent": 0.0,
                "completed_games": 0,
                "target_games": int(request.training_games or 0),
                "updated_at": now,
            },
            "overall_progress": {
                "stage": stage,
                "percent": 0.0,
                "training_completed": 0,
                "training_total": int(request.training_games or 0),
                "battle_completed": 0,
                "battle_total": int(request.battle_games or 0) * 2,
                "battle_requested_per_side": int(request.battle_games or 0),
                "updated_at": now,
            },
            "config": request_config,
        }
        if model_runtime is not None:
            run["model_id"] = model_runtime["model_id"]
            run["model_config_hash"] = model_runtime["model_config_hash"]
            run["model_runtime"] = to_jsonable(dict(model_runtime["model_runtime"]))
        self.evolution_runs[run_id] = run
        self._persist_background_tasks()
        return run

    def workflow_game_concurrency(self) -> int | None:
        value = runtime_setting_int_for_store(self._context, WORKFLOW_GAME_CONCURRENCY_KEY, default=0)
        return value if value > 0 else None

    @staticmethod
    def evolution_role_concurrency(config: dict[str, Any] | None = None) -> int:
        configured = (config or {}).get("role_concurrency")
        if configured in (None, ""):
            configured = os.getenv(EVOLUTION_ROLE_CONCURRENCY_KEY, "1")
        try:
            value = int(configured)
        except (TypeError, ValueError):
            value = 1
        return max(1, min(MAX_EVOLUTION_ROLE_CONCURRENCY, value))

    def configured_evolution_role_concurrency(self, config: dict[str, Any] | None = None) -> int:
        if isinstance(config, dict) and config.get("role_concurrency") not in (None, ""):
            return self.evolution_role_concurrency(config)
        value = runtime_setting_int_for_store(
            self._context,
            EVOLUTION_ROLE_CONCURRENCY_KEY,
            default=self.evolution_role_concurrency(),
        )
        return max(1, min(MAX_EVOLUTION_ROLE_CONCURRENCY, int(value or 1)))

    @staticmethod
    def count_evolution_games(value: Any) -> int:
        if isinstance(value, list):
            return len([item for item in value if isinstance(item, dict)])
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def evolution_overall_progress(self, run: dict[str, Any]) -> dict[str, Any]:
        progress = run.get("progress") if isinstance(run.get("progress"), dict) else {}
        config = run.get("config") if isinstance(run.get("config"), dict) else {}
        training_total = self.count_evolution_games(run.get("training_game_count") or config.get("training_games"))
        battle_per_side = self.count_evolution_games(run.get("battle_game_count") or config.get("battle_games"))
        training_completed = self.count_evolution_games(run.get("training_completed") or run.get("training_games"))
        battle_completed = self.count_evolution_games(run.get("battle_completed") or run.get("battle_games"))
        stage = str(run.get("current_stage") or progress.get("stage") or run.get("status") or "").lower()
        status = str(run.get("status") or "").lower()
        terminal = status in {
            "reviewing", "promoted", "rejected", "completed", "failed", "cancelled", "interrupted",
        }
        if terminal:
            percent = 1.0
        elif stage == "training":
            fraction = training_completed / training_total if training_total > 0 else 1.0
            percent = 0.45 * fraction
        elif stage == "battling":
            battle_total = battle_per_side * 2
            fraction = battle_completed / battle_total if battle_total > 0 else 1.0
            percent = 0.70 + 0.25 * fraction
        else:
            percent = _EVOLUTION_STAGE_START.get(stage, self._task_progress_percent(run))
        return {
            "stage": stage,
            "percent": max(0.0, min(1.0, float(percent))),
            "training_completed": training_completed,
            "training_total": training_total,
            "battle_completed": battle_completed,
            "battle_total": battle_per_side * 2,
            "battle_requested_per_side": battle_per_side,
            "updated_at": run.get("last_heartbeat_at") or progress.get("updated_at") or beijing_now_iso(),
        }

    def sync_evolution_progress(self, run_id: str, snapshot: dict[str, Any]) -> None:
        run = self.evolution_runs.get(run_id)
        if run is None or run.get("stop_requested") or run.get("cancelled"):
            return
        for key in (
            "status",
            "current_stage",
            "parent_hash",
            "candidate_hash",
            "candidate_skill_dir",
            "baseline_skill_dir",
            "battle_result",
            "recommendation",
            "last_heartbeat_at",
        ):
            if key in snapshot and snapshot.get(key) is not None:
                run[key] = snapshot[key]
        for key in ("training_games", "battle_games", "proposals", "diff", "diagnostics", "warnings", "errors"):
            value = snapshot.get(key)
            if isinstance(value, list):
                run[key] = value
        if isinstance(snapshot.get("progress"), dict):
            run["progress"] = dict(snapshot["progress"])
        run["training_game_count"] = self.count_evolution_games(
            snapshot.get("training_game_count") or run.get("training_game_count")
        )
        run["battle_game_count"] = self.count_evolution_games(
            snapshot.get("battle_game_count") or run.get("battle_game_count")
        )
        run["training_completed"] = self.count_evolution_games(run.get("training_games"))
        run["battle_completed"] = self.count_evolution_games(run.get("battle_games"))
        heartbeat = self._touch_background_task(run, timestamp=snapshot.get("last_heartbeat_at"))
        run["overall_progress"] = self.evolution_overall_progress(run)
        run["overall_progress"]["updated_at"] = heartbeat
        self.refresh_evolution_batch(run.get("batch_id"))
        self._persist_background_tasks()

    def evolution_queue_progress(self, entity: dict[str, Any], *, task_id: str) -> dict[str, Any]:
        progress = entity.get("progress") if isinstance(entity.get("progress"), dict) else {}
        overall = entity.get("overall_progress") if isinstance(entity.get("overall_progress"), dict) else {}
        payload = dict(overall)
        payload.update(progress)
        payload.setdefault("stage", entity.get("current_stage") or entity.get("status") or "running")
        payload.setdefault("percent", self._task_progress_percent(entity))
        payload["task_id"] = task_id
        if entity.get("run_id"):
            payload["run_id"] = entity.get("run_id")
        if entity.get("batch_id"):
            payload["batch_id"] = entity.get("batch_id")
        return payload

    def evolution_cancel_check(self, run_id: str, external_cancel_check: Callable[[], bool] | None = None) -> bool:
        if external_cancel_check is not None and external_cancel_check():
            return True
        run = self.evolution_runs.get(run_id)
        if run is None:
            return True
        if run.get("stop_requested") or run.get("cancelled"):
            return True
        batch_id = run.get("batch_id")
        batch = self.evolution_batches.get(str(batch_id)) if batch_id else None
        return bool(batch and (batch.get("stop_requested") or batch.get("cancelled")))

    def run_summary_for_batch(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run.get("run_id"),
            "role": run.get("role"),
            "status": run.get("status"),
            "current_stage": run.get("current_stage"),
            "progress": run.get("progress") if isinstance(run.get("progress"), dict) else {},
            "overall_progress": self.evolution_overall_progress(run),
            "training_completed": self.count_evolution_games(run.get("training_completed") or run.get("training_games")),
            "training_game_count": self.count_evolution_games(run.get("training_game_count")),
            "battle_completed": self.count_evolution_games(run.get("battle_completed") or run.get("battle_games")),
            "battle_game_count": self.count_evolution_games(run.get("battle_game_count")),
            "candidate_hash": run.get("candidate_hash"),
            "parent_hash": run.get("parent_hash"),
            "recommendation": run.get("recommendation"),
            "error": run.get("error"),
            "diagnostic_count": len(run.get("diagnostics", []) or []),
            "warning_count": len(run.get("warnings", []) or []),
            "error_count": len(run.get("errors", []) or []),
            "started_at": run.get("started_at"),
            "finished_at": run.get("finished_at"),
            "last_heartbeat_at": run.get("last_heartbeat_at"),
        }

    def refresh_evolution_batch(self, batch_id: Any) -> None:
        if not batch_id:
            return
        batch = self.evolution_batches.get(str(batch_id))
        if batch is None or batch.get("kind") != "role_evolution_batch":
            return
        run_ids = [str(item) for item in batch.get("runs", []) or []]
        summaries = [
            self.run_summary_for_batch(self.evolution_runs[run_id])
            for run_id in run_ids
            if run_id in self.evolution_runs
        ]
        batch["run_summaries"] = summaries
        total = len(run_ids)
        completed = len([
            item for item in summaries
            if str(item.get("status") or "").lower() in {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}
        ])
        running = next((item for item in summaries if str(item.get("status") or "").lower() in {"queued", "running", "training", "consolidating", "applying", "battling"}), None)
        heartbeat = self._touch_background_task(batch)
        batch_status = str(batch.get("status") or "").lower()
        if batch.get("stop_requested") or batch.get("cancelled"):
            current_stage = "stopped"
        elif batch_status in {"completed", "failed", "interrupted"}:
            current_stage = batch_status
        elif running:
            current_stage = running.get("current_stage")
        else:
            current_stage = batch.get("current_stage") or batch.get("status")
        batch["current_stage"] = current_stage
        batch["progress"] = {
            "stage": current_stage,
            "percent": (
                sum(
                    float((item.get("overall_progress") or {}).get("percent") or 0.0)
                    for item in summaries
                )
                / total
            ) if total else 0.0,
            "completed_roles": completed,
            "role_count": total,
            "total_roles": total,
            "updated_at": heartbeat,
        }
        batch["overall_progress"] = dict(batch["progress"])

    def mark_evolution_stopped(self, entity: dict[str, Any]) -> None:
        entity["status"] = "failed"
        entity["error"] = entity.get("error") or MANUAL_STOP_REASON
        _set_task_contract(entity, stop_requested=True, cancelled=True, interrupted=False, failed=False)
        heartbeat = self._touch_background_task(entity)
        entity["finished_at"] = entity.get("finished_at") or heartbeat
        entity["current_stage"] = "stopped"
        progress = entity.get("progress")
        progress = dict(progress) if isinstance(progress, dict) else {}
        progress["stage"] = "stopped"
        progress.setdefault("percent", self._task_progress_percent(entity))
        progress["updated_at"] = heartbeat
        entity["progress"] = progress
        if entity.get("kind") == "role_evolution_run":
            entity["overall_progress"] = self.evolution_overall_progress(entity)
        elif entity.get("kind") == "role_evolution_batch":
            self.refresh_evolution_batch(entity.get("batch_id"))

    async def run_queued_evolution(
        self,
        run_id: str,
        request: EvolutionStartRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        run = self.evolution_runs.get(run_id)
        if run is None:
            return
        request = automatic_evolution_request(request)
        if self.evolution_cancel_check(run_id, cancel_check):
            self.mark_evolution_stopped(run)
            self._persist_background_tasks()
            return
        role = str(run.get("role") or "villager")
        resume_snapshot = {
            key: to_jsonable(run.get(key))
            for key in (
                "status",
                "current_stage",
                "parent_hash",
                "baseline_config",
                "candidate_hash",
                "candidate_skill_dir",
                "baseline_skill_dir",
                "training_games",
                "battle_games",
                "battle_result",
                "proposals",
                "diff",
                "diagnostics",
                "warnings",
                "errors",
            )
            if run.get(key) not in (None, [], {})
        }
        run["status"] = "training"
        run["current_stage"] = "training"
        run.setdefault("started_at", beijing_now_iso())
        self._touch_background_task(run)
        run["overall_progress"] = self.evolution_overall_progress(run)
        self._persist_background_tasks()
        if progress_sink is not None:
            progress_sink(self.evolution_queue_progress(run, task_id=run.get("task_id") or run_id))
        try:
            def sync_progress(snapshot: dict[str, Any]) -> None:
                self.sync_evolution_progress(run_id, snapshot)
                if progress_sink is not None:
                    current = self.evolution_runs.get(run_id, snapshot)
                    progress_sink(self.evolution_queue_progress(current, task_id=run.get("task_id") or run_id))

            runner_config = dict(run.get("config") or {})
            runner_config["resume_snapshot"] = resume_snapshot
            result = await self.evolution_runner()(
                role=role,
                training_games=request.training_games,
                battle_games=request.battle_games,
                max_days=request.max_days,
                auto_promote=request.auto_promote,
                run_id=run_id,
                model=self.model_for_evolution_run(request),
                paths=self.paths,
                config=runner_config,
                progress_sink=sync_progress,
                cancel_check=lambda: self.evolution_cancel_check(run_id, cancel_check),
            )
        except Exception as exc:  # pragma: no cover - defensive background failure path
            if self.evolution_cancel_check(run_id, cancel_check) or str(exc) == MANUAL_STOP_REASON:
                self.mark_evolution_stopped(run)
                self.refresh_evolution_batch(run.get("batch_id"))
                self._persist_background_tasks()
                return
            run["status"] = "failed"
            _set_task_contract(run, failed=True, cancelled=False, interrupted=False)
            run["finished_at"] = beijing_now_iso()
            run.setdefault("errors", []).append(str(exc))
            run.setdefault("diagnostics", []).append(
                {
                    "kind": "evolution_error",
                    "stage": "evolution.run",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                }
            )
            run["error"] = str(exc)
            self._touch_background_task(run)
            self._persist_background_tasks()
            return

        if self.evolution_cancel_check(run_id, cancel_check):
            self.mark_evolution_stopped(run)
            self.refresh_evolution_batch(run.get("batch_id"))
            self._persist_background_tasks()
            return
        run.update(result)
        run["run_id"] = result.get("run_id") or run_id
        run["role"] = role
        if isinstance(run.get("config"), dict) and isinstance(run["config"].get("model_runtime"), dict):
            run["model_id"] = run["config"].get("model_id")
            run["model_config_hash"] = run["config"].get("model_config_hash")
            run["model_runtime"] = to_jsonable(dict(run["config"]["model_runtime"]))
        run["status"] = result.get("status", "reviewing")
        _set_task_contract(run, failed=run["status"] == "failed", cancelled=False, interrupted=False)
        run["started_at"] = run.get("started_at") or beijing_now_iso()
        run["finished_at"] = result.get("finished_at") or beijing_now_iso()
        self._touch_background_task(run)
        run["training_completed"] = self.count_evolution_games(run.get("training_games"))
        run["battle_completed"] = self.count_evolution_games(run.get("battle_games"))
        run["overall_progress"] = self.evolution_overall_progress(run)
        self.refresh_evolution_batch(run.get("batch_id"))
        self._persist_background_tasks()
        if progress_sink is not None:
            progress_sink(self.evolution_queue_progress(run, task_id=run.get("task_id") or run_id))

    async def run_queued_evolution_batch(
        self,
        batch_id: str,
        request: EvolutionStartRequest,
        *,
        cancel_check: Callable[[], bool] | None = None,
        progress_sink: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        request = automatic_evolution_request(request)
        batch = self.evolution_batches.get(batch_id)
        if batch is None:
            return
        if cancel_check is not None and cancel_check():
            batch["stop_requested"] = True
            batch["cancelled"] = True
        batch["status"] = "running"
        _set_task_contract(
            batch,
            stop_requested=bool(batch.get("stop_requested")),
            cancelled=bool(batch.get("cancelled")),
            failed=False,
            interrupted=False,
        )
        self.refresh_evolution_batch(batch_id)
        self._touch_background_task(batch)
        self._persist_background_tasks()
        if progress_sink is not None:
            progress_sink(self.evolution_queue_progress(batch, task_id=batch_id))
        try:
            run_ids = [str(run_id) for run_id in batch.get("runs", []) or []]
            concurrency = self.configured_evolution_role_concurrency(
                batch.get("config") if isinstance(batch.get("config"), dict) else None
            )
            queue: asyncio.Queue[str] = asyncio.Queue()
            for run_id in run_ids:
                queue.put_nowait(run_id)

            async def run_worker() -> None:
                while not queue.empty():
                    if cancel_check is not None and cancel_check():
                        batch["stop_requested"] = True
                        batch["cancelled"] = True
                    if batch.get("stop_requested") or batch.get("cancelled"):
                        return
                    try:
                        run_id = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    run = self.evolution_runs.get(run_id)
                    if run is None:
                        queue.task_done()
                        continue
                    if str(run.get("status") or "").lower() in {
                        "reviewing", "promoted", "rejected", "completed",
                    }:
                        queue.task_done()
                        continue
                    try:
                        self._touch_background_task(batch)
                        self.refresh_evolution_batch(batch_id)
                        self._persist_background_tasks()
                        if progress_sink is not None:
                            progress_sink(self.evolution_queue_progress(batch, task_id=batch_id))
                        await self.run_queued_evolution(
                            run_id,
                            request,
                            cancel_check=cancel_check,
                            progress_sink=lambda progress: progress_sink(progress) if progress_sink is not None else None,
                        )
                    except Exception as exc:  # noqa: BLE001 - isolate one role
                        run["status"] = "failed"
                        run["error"] = str(exc)
                        run.setdefault("errors", []).append(str(exc))
                        _set_task_contract(run, failed=True, cancelled=False, interrupted=False)
                    finally:
                        queue.task_done()
                        self._touch_background_task(batch)
                        self.refresh_evolution_batch(batch_id)
                        self._persist_background_tasks()
                        if progress_sink is not None:
                            progress_sink(self.evolution_queue_progress(batch, task_id=batch_id))

            await asyncio.gather(*(run_worker() for _ in range(min(concurrency, len(run_ids)))))
            if batch.get("stop_requested") or batch.get("cancelled"):
                batch["status"] = "failed"
                batch["error"] = batch.get("error") or MANUAL_STOP_REASON
                _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
                self.mark_evolution_stopped(batch)
            elif batch.get("status") == "running":
                batch["status"] = "completed"
                _set_task_contract(batch, stop_requested=False, cancelled=False, interrupted=False, failed=False)
        except Exception as exc:  # pragma: no cover - defensive background failure path
            batch["status"] = "failed"
            batch["error"] = str(exc)
            self._append_background_diagnostic(
                batch,
                {
                    "kind": "evolution_batch_error",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                },
                stage="evolution.batch",
                timestamp=beijing_now_iso(),
            )
            _set_task_contract(batch, failed=True, cancelled=False, interrupted=False)
        finally:
            batch["finished_at"] = beijing_now_iso()
            self._touch_background_task(batch)
            self.refresh_evolution_batch(batch_id)
            self._persist_background_tasks()
            if progress_sink is not None:
                progress_sink(self.evolution_queue_progress(batch, task_id=batch_id))

    async def run_single_evolution(self, role: str, request: EvolutionStartRequest) -> dict[str, Any]:
        request = automatic_evolution_request(request)
        run = self.create_evolution_run(role, request)
        run_id = run["run_id"]
        result = await self.evolution_runner()(
            role=role,
            training_games=request.training_games,
            battle_games=request.battle_games,
            max_days=request.max_days,
            auto_promote=request.auto_promote,
            run_id=run_id,
            model=self.model_for_evolution_run(request),
            paths=self.paths,
            config=run.get("config") if isinstance(run.get("config"), dict) else None,
        )
        run.update(result)
        run["run_id"] = result.get("run_id") or run_id
        run["role"] = role
        if isinstance(run.get("config"), dict) and isinstance(run["config"].get("model_runtime"), dict):
            run["model_id"] = run["config"].get("model_id")
            run["model_config_hash"] = run["config"].get("model_config_hash")
            run["model_runtime"] = to_jsonable(dict(run["config"]["model_runtime"]))
        run["status"] = result.get("status", "reviewing")
        _set_task_contract(run, failed=run["status"] == "failed", cancelled=False, interrupted=False)
        run["started_at"] = run.get("started_at") or beijing_now_iso()
        run["finished_at"] = result.get("finished_at") or beijing_now_iso()
        self._touch_background_task(run)
        self._persist_background_tasks()
        return run


def _non_empty_mapping(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _first_mapping(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict) and value:
            return value
    return None


def _first_list(*values: Any) -> list[Any] | None:
    for value in values:
        if isinstance(value, list) and value:
            return value
    return None
