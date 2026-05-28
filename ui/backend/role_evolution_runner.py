"""Role evolution manager — manages run state and SSE events.

Follows the same pattern as ``evolution_runner.py`` but wraps the
role-level evolution pipeline (``agent.role_evolution.pipeline``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from agent.role_evolution.models import (
    EvolutionRun,
    EvolutionStatus,
    SkillConsolidation,
    SkillDiff,
)
from agent.role_evolution.pipeline import (
    BaselineChangedError,
    InvalidRunStateError,
    recover_interrupted_runs,
    reject as pipeline_reject,
    promote as pipeline_promote,
    run_evolution,
    _load_state,
    _run_dir,
)
from agent.role_evolution.store import VersionStore

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tracked run wrapper (mirrors RunningEvolution in evolution_runner.py)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RoleEvolutionRun:
    """Mutable wrapper around an :class:`EvolutionRun` with task handle."""

    run_id: str
    role: str
    status: str = "queued"
    stage: str = "queued"
    run: EvolutionRun | None = None
    error: str | None = None
    started_at: str = ""
    task: asyncio.Task[None] | None = None

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": self.run_id,
            "role": self.role,
            "status": self.status,
            "stage": self.stage,
            "started_at": self.started_at,
        }
        if self.run is not None:
            data["parent_hash"] = self.run.parent_hash
            data["candidate_hash"] = self.run.candidate_hash
            data["training_games"] = self.run.training_games
            data["battle_games"] = self.run.battle_games
            data["battle_result"] = self.run.battle_result
            if self.run.proposals is not None:
                data["proposal_count"] = len(self.run.proposals.proposals)
            if self.run.diff is not None:
                data["diff_count"] = len(self.run.diff)
            if self.run.errors:
                data["errors"] = list(self.run.errors)
        if self.error:
            data["error"] = self.error
        return data


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class RoleEvolutionRunner:
    """Manages role evolution runs, SSE queues, and recovery."""

    def __init__(self, store: VersionStore) -> None:
        self.store = store
        self._active_runs: dict[str, RoleEvolutionRun] = {}
        self._sse_queues: dict[str, list[asyncio.Queue]] = {}

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    async def start_evolution(
        self,
        role: str,
        training_games: int = 20,
        battle_games: int = 10,
        model_adapter: Any | None = None,
    ) -> RoleEvolutionRun:
        """Start a new evolution run.  Returns the tracked run."""
        run_id = f"evo_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}"
        started_at = datetime.now(timezone.utc).isoformat()

        tracked = RoleEvolutionRun(
            run_id=run_id,
            role=role,
            started_at=started_at,
        )
        self._active_runs[run_id] = tracked

        tracked.task = asyncio.create_task(
            self._execute(tracked, training_games, battle_games, model_adapter),
            name=f"role-evolution-{run_id}",
        )
        return tracked

    def get_run(self, run_id: str) -> RoleEvolutionRun | None:
        """Get tracked run by ID."""
        return self._active_runs.get(run_id)

    def get_runs_for_role(self, role: str) -> list[RoleEvolutionRun]:
        """Get all tracked runs for a role."""
        return [r for r in self._active_runs.values() if r.role == role]

    def list_runs(self) -> list[dict[str, Any]]:
        """Snapshot of all tracked runs."""
        return [r.snapshot() for r in self._active_runs.values()]

    # ------------------------------------------------------------------
    # Promote / reject
    # ------------------------------------------------------------------

    async def promote_run(self, run_id: str) -> RoleEvolutionRun:
        """Promote a run's candidate to baseline."""
        tracked = self._active_runs.get(run_id)
        if tracked is None:
            raise KeyError(f"Run {run_id} not found")
        if tracked.run is None:
            raise InvalidRunStateError(f"Run {run_id} has no pipeline data")

        await pipeline_promote(tracked.run, self.store)
        tracked.status = tracked.run.status
        tracked.stage = tracked.run.status
        self._broadcast(run_id, "promoted", {"run_id": run_id})
        return tracked

    async def reject_run(self, run_id: str) -> RoleEvolutionRun:
        """Reject a run."""
        tracked = self._active_runs.get(run_id)
        if tracked is None:
            raise KeyError(f"Run {run_id} not found")
        if tracked.run is None:
            raise InvalidRunStateError(f"Run {run_id} has no pipeline data")

        await pipeline_reject(tracked.run, self.store)
        tracked.status = tracked.run.status
        tracked.stage = tracked.run.status
        self._broadcast(run_id, "rejected", {"run_id": run_id})
        return tracked

    # ------------------------------------------------------------------
    # SSE
    # ------------------------------------------------------------------

    def subscribe(self, run_id: str) -> asyncio.Queue:
        """Subscribe to SSE events for a run.  Returns a queue."""
        q: asyncio.Queue = asyncio.Queue()
        self._sse_queues.setdefault(run_id, []).append(q)
        return q

    def unsubscribe(self, run_id: str, queue: asyncio.Queue) -> None:
        """Remove a queue from the subscriber list."""
        queues = self._sse_queues.get(run_id, [])
        try:
            queues.remove(queue)
        except ValueError:
            pass

    async def sse_events(self, run_id: str) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted events for a run."""
        queue = self.subscribe(run_id)
        try:
            while True:
                item = await queue.get()
                event_name = item.get("event", "message")
                data = json.dumps(item.get("data", {}), ensure_ascii=False)
                yield f"event: {event_name}\ndata: {data}\n\n"
                if event_name in ("promoted", "rejected", "failed", "done"):
                    break
        finally:
            self.unsubscribe(run_id, queue)

    def _broadcast(self, run_id: str, event: str, data: dict) -> None:
        """Push an event to all SSE queues for a run."""
        for q in self._sse_queues.get(run_id, []):
            q.put_nowait({"event": event, "data": data})

    # ------------------------------------------------------------------
    # Recovery
    # ------------------------------------------------------------------

    def recover_on_startup(self) -> list[dict]:
        """Scan state.json files and mark interrupted runs as failed.

        Returns the list of recovered (now-failed) run states.
        """
        return recover_interrupted_runs(self.store)

    # ------------------------------------------------------------------
    # Pipeline execution
    # ------------------------------------------------------------------

    async def _execute(
        self,
        tracked: RoleEvolutionRun,
        training_games: int,
        battle_games: int,
        model_adapter: Any | None,
    ) -> None:
        """Background task that drives the evolution pipeline."""

        def _on_progress(stage: str, data: dict) -> None:
            tracked.stage = stage
            tracked.status = stage
            self._broadcast(tracked.run_id, stage, {"run_id": tracked.run_id, **data})

        try:
            result = await run_evolution(
                store=self.store,
                role=tracked.role,
                training_games=training_games,
                battle_games=battle_games,
                model_adapter=model_adapter,
                on_progress=_on_progress,
            )
            tracked.run = result
            tracked.status = result.status
            tracked.stage = result.status
            self._broadcast(tracked.run_id, result.status, {"run_id": tracked.run_id})
        except Exception as exc:
            _log.exception("Role evolution run %s failed", tracked.run_id)
            tracked.status = "failed"
            tracked.stage = "failed"
            tracked.error = str(exc)
            self._broadcast(tracked.run_id, "failed", {
                "run_id": tracked.run_id,
                "error": str(exc),
            })
