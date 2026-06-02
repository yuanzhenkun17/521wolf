from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from agent.common import beijing_now_iso, beijing_now_str
from agent.learning.evolution.batch import (
    BatchEvolutionResult,
    promote_batch_result,
    run_batch_evolution,
)
from agent.learning.evolution.store import VersionStore

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class RoleBatchEvolutionRun:
    batch_id: str
    roles: list[str]
    status: str = "queued"
    stage: str = "queued"
    started_at: str = ""
    training_games: int = 0
    battle_games: int = 0
    role_concurrency: int = 1
    game_concurrency: int = 1
    llm_concurrency: int = 5
    llm_rpm: int = 60
    role_statuses: dict[str, str] = field(default_factory=dict)
    role_run_ids: dict[str, str] = field(default_factory=dict)
    role_candidates: dict[str, str | None] = field(default_factory=dict)
    result: BatchEvolutionResult | None = None
    error: str | None = None
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": "role_batch_evolution_run",
            "schema_version": 1,
            "batch_id": self.batch_id,
            "roles": list(self.roles),
            "status": self.status,
            "stage": self.stage,
            "current_stage": self.stage,
            "started_at": self.started_at,
            "training_games": self.training_games,
            "battle_games": self.battle_games,
            "role_concurrency": self.role_concurrency,
            "game_concurrency": self.game_concurrency,
            "llm_concurrency": self.llm_concurrency,
            "llm_rpm": self.llm_rpm,
            "role_statuses": dict(self.role_statuses),
            "role_run_ids": dict(self.role_run_ids),
            "role_candidates": dict(self.role_candidates),
            "accepted_roles": [],
            "rejected_roles": [],
            "combined_passed": False,
            "promoted_roles": [],
            "errors": [],
            "combined_battle_result": None,
        }
        if self.result is not None:
            data.update({
                "baseline_config": self.result.baseline_config.to_dict(),
                "accepted_roles": list(self.result.accepted_roles),
                "rejected_roles": list(self.result.rejected_roles),
                "combined_config": self.result.combined_config.to_dict()
                if self.result.combined_config is not None else None,
                "combined_passed": self.result.combined_passed,
                "promoted_roles": list(self.result.promoted_roles),
                "errors": list(self.result.errors),
                "combined_battle_result": self.result.combined_battle_result,
                "runs": [r.to_dict() for r in self.result.runs],
            })
        if self.error:
            data["error"] = self.error
            data["errors"] = [*data["errors"], self.error]
        return data


class RoleBatchEvolutionRunner:
    def __init__(self, store: VersionStore) -> None:
        self.store = store
        self._active_batches: dict[str, RoleBatchEvolutionRun] = {}
        self._sse_queues: dict[str, list[asyncio.Queue]] = {}

    async def start_batch(
        self,
        *,
        roles: list[str],
        training_games: int = 20,
        battle_games: int = 10,
        role_concurrency: int = 2,
        game_concurrency: int = 1,
        llm_concurrency: int = 5,
        llm_rpm: int = 60,
        model_adapter: Any | None = None,
    ) -> RoleBatchEvolutionRun:
        if not roles:
            raise ValueError("roles cannot be empty")
        active_roles = {
            role
            for batch in self._active_batches.values()
            if batch.status not in ("reviewing", "promoted", "rejected", "failed")
            for role in batch.roles
        }
        conflict = sorted(set(roles) & active_roles)
        if conflict:
            raise RuntimeError(f"角色已有活跃批量演化任务: {', '.join(conflict)}")

        batch_id = f"batch_{beijing_now_str('%Y%m%d_%H%M%S_%f')}"
        tracked = RoleBatchEvolutionRun(
            batch_id=batch_id,
            roles=list(roles),
            started_at=beijing_now_iso(),
            training_games=training_games,
            battle_games=battle_games,
            role_concurrency=role_concurrency,
            game_concurrency=game_concurrency,
            llm_concurrency=llm_concurrency,
            llm_rpm=llm_rpm,
            role_statuses={role: "queued" for role in roles},
        )
        self._active_batches[batch_id] = tracked
        tracked.task = asyncio.create_task(
            self._execute(
                tracked,
                training_games,
                battle_games,
                role_concurrency,
                game_concurrency,
                llm_concurrency,
                llm_rpm,
                model_adapter,
            ),
            name=f"role-batch-evolution-{batch_id}",
        )
        return tracked

    def get_batch(self, batch_id: str) -> RoleBatchEvolutionRun | None:
        return self._active_batches.get(batch_id)

    def list_batches(self) -> list[dict[str, Any]]:
        return [batch.snapshot() for batch in self._active_batches.values()]

    async def promote_batch(self, batch_id: str) -> RoleBatchEvolutionRun:
        tracked = self._active_batches.get(batch_id)
        if tracked is None:
            raise KeyError(batch_id)
        if tracked.result is None:
            raise RuntimeError("batch has no review result")
        if tracked.status == "promoted":
            return tracked
        if tracked.status not in ("reviewing", "promoted"):
            raise RuntimeError(f"cannot promote batch in status {tracked.status}")
        tracked.result = await promote_batch_result(store=self.store, result=tracked.result)
        tracked.status = "promoted" if tracked.result.promoted_roles else "reviewing"
        tracked.stage = tracked.status
        self._broadcast(batch_id, tracked.status, tracked.snapshot())
        return tracked

    async def reject_batch(self, batch_id: str) -> RoleBatchEvolutionRun:
        tracked = self._active_batches.get(batch_id)
        if tracked is None:
            raise KeyError(batch_id)
        if tracked.status != "reviewing":
            raise RuntimeError(f"cannot reject batch in status {tracked.status}")
        tracked.status = "rejected"
        tracked.stage = "rejected"
        self._broadcast(batch_id, "rejected", tracked.snapshot())
        return tracked

    def stop_batch(self, batch_id: str) -> RoleBatchEvolutionRun | None:
        """Stop a running batch (can be resumed)."""
        tracked = self._active_batches.get(batch_id)
        if tracked is None:
            return None
        if tracked.task and not tracked.task.done():
            tracked.task.cancel()
        tracked.status = "paused"
        tracked.stage = "paused"
        self._broadcast(batch_id, "paused", tracked.snapshot())
        return tracked

    def terminate_batch(self, batch_id: str) -> RoleBatchEvolutionRun | None:
        """Permanently stop a batch run."""
        tracked = self._active_batches.get(batch_id)
        if tracked is None:
            return None
        if tracked.task and not tracked.task.done():
            tracked.task.cancel()
        tracked.status = "failed"
        tracked.stage = "failed"
        tracked.error = "用户终止"
        self._broadcast(batch_id, "failed", tracked.snapshot())
        return tracked

    def subscribe(self, batch_id: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        self._sse_queues.setdefault(batch_id, []).append(queue)
        return queue

    def unsubscribe(self, batch_id: str, queue: asyncio.Queue) -> None:
        queues = self._sse_queues.get(batch_id, [])
        try:
            queues.remove(queue)
        except ValueError:
            pass

    async def sse_events(self, batch_id: str) -> AsyncGenerator[str, None]:
        queue = self.subscribe(batch_id)
        try:
            while True:
                item = await queue.get()
                data = json.dumps(item.get("data", {}), ensure_ascii=False)
                yield f"data: {data}\n\n"
                if item.get("event") in ("reviewing", "promoted", "rejected", "failed"):
                    break
        finally:
            self.unsubscribe(batch_id, queue)

    def _broadcast(self, batch_id: str, event: str, data: dict[str, Any]) -> None:
        for queue in self._sse_queues.get(batch_id, []):
            queue.put_nowait({"event": event, "data": data})

    async def _execute(
        self,
        tracked: RoleBatchEvolutionRun,
        training_games: int,
        battle_games: int,
        role_concurrency: int,
        game_concurrency: int,
        llm_concurrency: int,
        llm_rpm: int,
        model_adapter: Any | None,
    ) -> None:
        def _on_progress(stage: str, data: dict) -> None:
            tracked.stage = stage
            if stage.startswith("role_"):
                role = data.get("role")
                if role:
                    tracked.role_statuses[str(role)] = _status_from_stage(stage)
                run_id = data.get("run_id")
                if role and run_id:
                    tracked.role_run_ids[str(role)] = str(run_id)
                candidate_hash = data.get("candidate_hash")
                if role and candidate_hash is not None:
                    tracked.role_candidates[str(role)] = str(candidate_hash)
            elif stage == "combined_battle_started":
                tracked.status = "combined_battling"
            elif stage == "batch_reviewing":
                tracked.status = "reviewing"
            elif stage == "batch_started":
                tracked.status = "training"
            else:
                tracked.status = tracked.status if tracked.status != "queued" else "training"
            self._broadcast(tracked.batch_id, stage, tracked.snapshot())

        try:
            tracked.result = await run_batch_evolution(
                store=self.store,
                roles=tracked.roles,
                training_games=training_games,
                battle_games=battle_games,
                role_concurrency=role_concurrency,
                game_concurrency=game_concurrency,
                llm_concurrency=llm_concurrency,
                llm_rpm=llm_rpm,
                model_adapter=model_adapter,
                auto_promote=False,
                on_progress=_on_progress,
            )
            tracked.status = "reviewing"
            tracked.stage = "reviewing"
            self._broadcast(tracked.batch_id, "reviewing", tracked.snapshot())
        except Exception as exc:
            _log.exception("Batch evolution %s failed", tracked.batch_id)
            tracked.status = "failed"
            tracked.stage = "failed"
            tracked.error = str(exc)
            self._broadcast(tracked.batch_id, "failed", tracked.snapshot())


def _status_from_stage(stage: str) -> str:
    if stage.startswith("role_training"):
        return "training"
    if stage.startswith("role_consolidating"):
        return "consolidating"
    if stage.startswith("role_applying"):
        return "applying"
    if stage.startswith("role_battling"):
        return "battling"
    if stage.startswith("role_reviewing") or stage == "role_finished":
        return "reviewing"
    return stage.removeprefix("role_")
