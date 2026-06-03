"""Role evolution manager — manages run state and SSE events.

Follows the same pattern as ``evolution_runner.py`` but wraps the
role-level evolution pipeline (``agent.learning.evolution.pipeline``).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, AsyncGenerator

from agent.common import beijing_now_iso, beijing_now_str
from ui.backend.sse_mixin import SSEMixin
from agent.common.errors import is_rate_limit_error as _is_rate_limit_error
from agent.common.paths import DEFAULT as DEFAULT_PATHS
from agent.learning.evolution.config import build_baseline_config
from agent.learning.evolution.models import (
    EvolutionRun,
)
from agent.learning.evolution.pipeline import (
    InvalidRunStateError,
    recover_interrupted_runs,
    reject as pipeline_reject,
    promote as pipeline_promote,
    run_evolution,
)
from agent.learning.evolution.state import load_run_state
from agent.learning.evolution.store import VersionStore
from agent.infrastructure.llm import AsyncRateLimiter

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
    artifact_run_id: str | None = None
    training_run_id: str | None = None
    training_output_dir: str | None = None
    training_completed: int = 0
    battle_completed: int = 0
    training_games: int = 0
    battle_games: int = 0
    game_concurrency: int = 1
    llm_concurrency: int = 5
    llm_rpm: int = 60
    retry_attempt: int = 0
    retry_total: int = 0

    def snapshot(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "kind": "role_evolution_run",
            "schema_version": 1,
            "run_id": self.run_id,
            "artifact_run_id": self.artifact_run_id,
            "training_run_id": self.training_run_id,
            "training_output_dir": self.training_output_dir,
            "role": self.role,
            "status": self.status,
            "stage": self.stage,
            "current_stage": self.stage,
            "started_at": self.started_at,
            "training_completed": self.training_completed,
            "battle_completed": self.battle_completed,
            "parent_hash": "",
            "candidate_hash": None,
            "training_games": self.training_games,
            "battle_games": self.battle_games,
            "game_concurrency": self.game_concurrency,
            "llm_concurrency": self.llm_concurrency,
            "llm_rpm": self.llm_rpm,
            "retry_attempt": self.retry_attempt,
            "retry_total": self.retry_total,
            "battle_result": None,
            "diff": None,
            "errors": [],
        }
        if self.run is not None:
            data["artifact_run_id"] = self.run.run_id
            data["training_run_id"] = self.run.training_run_id
            data["training_output_dir"] = self.run.training_output_dir
            data["parent_hash"] = self.run.parent_hash
            data["candidate_hash"] = self.run.candidate_hash
            data["training_games"] = self.run.training_games
            data["battle_games"] = self.run.battle_games
            data["battle_result"] = self.run.battle_result
            data["diff"] = [d.to_dict() for d in self.run.diff] if self.run.diff is not None else None
            if self.run.proposals is not None:
                data["proposal_count"] = len(self.run.proposals.proposals)
            if self.run.diff is not None:
                data["diff_count"] = len(self.run.diff)
            if self.run.errors:
                data["errors"] = list(self.run.errors)
        if self.error:
            data["error"] = self.error
            data["errors"] = [*data["errors"], self.error]
        return data


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class RoleEvolutionRunner(SSEMixin):
    """Manages role evolution runs, SSE queues, and recovery."""

    def __init__(self, store: VersionStore) -> None:
        super().__init__()
        self.store = store
        self._active_runs: dict[str, RoleEvolutionRun] = {}

    def restore_runs(self) -> None:
        """Load non-terminal runs from disk into memory."""
        from agent.learning.evolution.pipeline import scan_active_runs
        for state in scan_active_runs():
            run_id = state.get("run_id")
            if not run_id or run_id in self._active_runs:
                continue
            tracked = RoleEvolutionRun(
                run_id=run_id,
                role=state.get("role", ""),
                status=state.get("status", "unknown"),
                stage=state.get("status", "unknown"),
                started_at=state.get("updated_at", ""),
                training_games=state.get("training_games", 0),
                battle_games=state.get("battle_games", 0),
            )
            tracked.training_run_id = state.get("training_run_id")
            tracked.training_output_dir = state.get("training_output_dir")
            # Count completed games from disk
            training_output_dir = state.get("training_output_dir")
            if training_output_dir:
                games_dir = Path(training_output_dir) / "games"
                if games_dir.exists():
                    tracked.training_completed = sum(
                        1 for g in games_dir.iterdir()
                        if g.is_dir() and (g / "meta.json").exists()
                    )
            self._active_runs[run_id] = tracked
            _log.info("Restored evolution run %s (role=%s, status=%s, training=%d/%d)",
                      run_id, tracked.role, tracked.status, tracked.training_completed, tracked.training_games)

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    async def start_evolution(
        self,
        role: str,
        training_games: int = 20,
        battle_games: int = 10,
        game_concurrency: int = 1,
        llm_concurrency: int = 5,
        llm_rpm: int = 60,
        model_adapter: Any | None = None,
    ) -> RoleEvolutionRun:
        """Start a new evolution run.  Returns the tracked run."""
        # Check for existing active run on the same role
        for existing in self._active_runs.values():
            if existing.role == role and existing.status not in ("promoted", "rejected", "failed"):
                raise RuntimeError(f"角色 {role} 已有一个活跃的演化任务: {existing.run_id}")

        run_id = f"evo_{beijing_now_str('%Y%m%d_%H%M%S_%f')}"
        started_at = beijing_now_iso()

        tracked = RoleEvolutionRun(
            run_id=run_id,
            role=role,
            started_at=started_at,
            training_games=training_games,
            battle_games=battle_games,
            game_concurrency=game_concurrency,
            llm_concurrency=llm_concurrency,
            llm_rpm=llm_rpm,
        )
        self._active_runs[run_id] = tracked

        tracked.task = asyncio.create_task(
            self._execute(
                tracked, training_games, battle_games,
                game_concurrency, llm_concurrency, llm_rpm, model_adapter,
            ),
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

    def stop_run(self, run_id: str) -> RoleEvolutionRun | None:
        """Stop a running evolution task (can be resumed)."""
        run = self._active_runs.get(run_id)
        if run is None:
            return None
        if run.task and not run.task.done():
            run.task.cancel()
        run.status = "paused"
        run.stage = "paused"
        self._broadcast(run_id, "paused", run.snapshot())
        return run

    def terminate_run(self, run_id: str) -> RoleEvolutionRun | None:
        """Permanently stop an evolution run and delete its files."""
        run = self._active_runs.get(run_id)
        if run is None:
            return None
        if run.task and not run.task.done():
            run.task.cancel()
        run.status = "failed"
        run.stage = "failed"
        run.error = "用户终止"
        self._broadcast(run_id, "failed", run.snapshot())
        # Delete evolution run directory
        import shutil
        evo_dir = DEFAULT_PATHS.evolution_dir / run_id
        if evo_dir.exists():
            shutil.rmtree(evo_dir, ignore_errors=True)
        return run

    async def resume_run(
        self,
        run_id: str,
        model_adapter: Any | None = None,
    ) -> RoleEvolutionRun:
        """Resume a paused or failed evolution run from the failed stage."""
        tracked = self._active_runs.get(run_id)
        if tracked is None:
            raise KeyError(f"Run {run_id} not found")

        if tracked.status not in ("paused", "failed"):
            raise InvalidRunStateError(f"Run {run_id} is not paused or failed (status={tracked.status})")

        tracked.status = "running"
        tracked.stage = "running"
        tracked.error = None
        self._broadcast(run_id, "resuming", tracked.snapshot())

        tracked.task = asyncio.create_task(
            self._resume_execute(tracked, model_adapter),
            name=f"role-evolution-resume-{run_id}",
        )
        return tracked

    async def rerun_consolidation(
        self,
        run_id: str,
        model_adapter: Any | None = None,
    ) -> RoleEvolutionRun:
        """Re-run consolidation on existing training data with updated prompt."""
        tracked = self._active_runs.get(run_id)
        if tracked is None:
            raise KeyError(f"Run {run_id} not found")

        tracked.status = "consolidating"
        tracked.stage = "consolidating"
        tracked.error = None
        self._broadcast(run_id, "consolidating", tracked.snapshot())

        tracked.task = asyncio.create_task(
            self._rerun_consolidation_execute(tracked, model_adapter),
            name=f"role-evolution-rerun-{run_id}",
        )
        return tracked

    async def _rerun_consolidation_execute(
        self,
        tracked: RoleEvolutionRun,
        model_adapter: Any | None,
    ) -> None:
        """Background task that re-runs consolidation on existing training data."""

        def _on_progress(stage: str, data: dict) -> None:
            tracked.stage = stage
            if stage == "battle_game":
                tracked.status = "battling"
                idx = int(data.get("game_index", -1))
                tracked.battle_completed = int(data.get(
                    "completed",
                    max(tracked.battle_completed, idx + 1),
                ))
            else:
                tracked.status = stage
            self._broadcast(tracked.run_id, stage, tracked.snapshot())

        try:
            result = await run_evolution(
                self.store,
                run_id=tracked.run_id,
                start_from="consolidating",
                model_adapter=model_adapter,
                game_concurrency=tracked.game_concurrency,
                llm_semaphore=asyncio.Semaphore(tracked.llm_concurrency),
                llm_rate_limiter=AsyncRateLimiter(tracked.llm_rpm),
                on_progress=_on_progress,
            )
            tracked.run = result
            tracked.status = result.status
            tracked.stage = result.status
            self._broadcast(tracked.run_id, result.status, tracked.snapshot())
        except Exception as exc:
            _log.exception("Rerun consolidation failed for %s", tracked.run_id)
            tracked.status = "failed"
            tracked.stage = "failed"
            tracked.error = str(exc)
            self._broadcast(tracked.run_id, "failed", tracked.snapshot())

    async def _resume_execute(
        self,
        tracked: RoleEvolutionRun,
        model_adapter: Any | None,
    ) -> None:
        """Background task that drives the resumed evolution pipeline."""

        def _on_progress(stage: str, data: dict) -> None:
            tracked.stage = stage
            if data.get("run_id"):
                tracked.artifact_run_id = str(data["run_id"])
            if data.get("training_run_id"):
                tracked.training_run_id = str(data["training_run_id"])
            if data.get("training_output_dir"):
                tracked.training_output_dir = str(data["training_output_dir"])
            if stage == "training_game":
                tracked.status = "training"
                idx = int(data.get("game_index", -1))
                tracked.training_completed = int(data.get(
                    "completed",
                    max(tracked.training_completed, idx + 1),
                ))
            elif stage == "battle_game":
                tracked.status = "battling"
                idx = int(data.get("game_index", -1))
                tracked.battle_completed = int(data.get(
                    "completed",
                    max(tracked.battle_completed, idx + 1),
                ))
            else:
                tracked.status = stage
            self._broadcast(tracked.run_id, stage, tracked.snapshot())

        max_retries = 5
        for attempt in range(max_retries):
            try:
                result = await run_evolution(
                    self.store,
                    run_id=tracked.run_id,
                    model_adapter=model_adapter,
                    game_concurrency=tracked.game_concurrency,
                    llm_semaphore=asyncio.Semaphore(tracked.llm_concurrency),
                    llm_rate_limiter=AsyncRateLimiter(tracked.llm_rpm),
                    on_progress=_on_progress,
                )
                tracked.run = result
                tracked.artifact_run_id = result.run_id
                tracked.training_run_id = result.training_run_id
                tracked.training_output_dir = result.training_output_dir
                tracked.status = result.status
                tracked.stage = result.status
                self._broadcast(tracked.run_id, result.status, tracked.snapshot())
                return
            except Exception as exc:
                if _is_rate_limit_error(exc) and attempt < max_retries - 1:
                    wait = 30 * (attempt + 1)
                    _log.warning("Rate limited on resumed run %s, retrying in %ds (attempt %d/%d)", tracked.run_id, wait, attempt + 1, max_retries)
                    tracked.status = "rate_limited"
                    tracked.stage = "rate_limited"
                    self._broadcast(tracked.run_id, "rate_limited", tracked.snapshot())
                    await asyncio.sleep(wait)
                    continue
                _log.exception("Resumed evolution run %s failed", tracked.run_id)
                tracked.status = "failed"
                tracked.stage = "failed"
                tracked.error = str(exc)
                self._broadcast(tracked.run_id, "failed", tracked.snapshot())
                return

    # ------------------------------------------------------------------
    # Promote / reject
    # ------------------------------------------------------------------

    async def promote_run(self, run_id: str) -> RoleEvolutionRun:
        """Promote a run's candidate to baseline."""
        tracked = self._active_runs.get(run_id)
        if tracked is None:
            raise KeyError(f"Run {run_id} not found")
        # Load from disk if not in memory
        if tracked.run is None:
            state = load_run_state(DEFAULT_PATHS, run_id)
            if state is None:
                raise InvalidRunStateError(f"Run {run_id} has no pipeline data")
            from agent.learning.evolution.models import EvolutionRun, SkillVersionConfig
            baseline_data = state.get("baseline_config")
            baseline_config = SkillVersionConfig.from_dict(baseline_data) if baseline_data else build_baseline_config(self.store)
            tracked.run = EvolutionRun(
                run_id=run_id,
                role=state.get("role", ""),
                parent_hash=state.get("parent_hash", ""),
                candidate_hash=state.get("candidate_hash"),
                status=state.get("status", "reviewing"),
                training_games=state.get("training_games", 0),
                battle_games=state.get("battle_games", 0),
                baseline_config=baseline_config,
            )
            tracked.run.training_run_id = state.get("training_run_id")
            tracked.run.training_output_dir = state.get("training_output_dir")

        await pipeline_promote(tracked.run, self.store)
        tracked.status = tracked.run.status
        tracked.stage = tracked.run.status
        self._broadcast(run_id, "promoted", tracked.snapshot())
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
        self._broadcast(run_id, "rejected", tracked.snapshot())
        return tracked

    # ------------------------------------------------------------------
    # SSE
    # ------------------------------------------------------------------


    async def sse_events(self, run_id: str) -> AsyncGenerator[str, None]:
        """Yield SSE-formatted events for a run."""
        queue = self.subscribe(run_id)
        try:
            while True:
                item = await queue.get()
                event_name = item.get("event", "message")
                data = json.dumps(item.get("data", {}), ensure_ascii=False)
                yield f"data: {data}\n\n"
                if event_name in ("promoted", "rejected", "failed", "done"):
                    break
        finally:
            self.unsubscribe(run_id, queue)


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
        game_concurrency: int,
        llm_concurrency: int,
        llm_rpm: int,
        model_adapter: Any | None,
    ) -> None:
        """Background task that drives the evolution pipeline."""

        def _on_progress(stage: str, data: dict) -> None:
            tracked.stage = stage
            if data.get("run_id"):
                tracked.artifact_run_id = str(data["run_id"])
            if data.get("training_run_id"):
                tracked.training_run_id = str(data["training_run_id"])
            if data.get("training_output_dir"):
                tracked.training_output_dir = str(data["training_output_dir"])
            if stage == "training_game":
                tracked.status = "training"
                idx = int(data.get("game_index", -1))
                tracked.training_completed = int(data.get(
                    "completed",
                    max(tracked.training_completed, idx + 1),
                ))
            elif stage == "battle_game":
                tracked.status = "battling"
                idx = int(data.get("game_index", -1))
                tracked.battle_completed = int(data.get(
                    "completed",
                    max(tracked.battle_completed, idx + 1),
                ))
            else:
                tracked.status = stage
                if "completed" in data and stage == "training":
                    tracked.training_completed = data["completed"]
                if "completed" in data and stage == "battling":
                    tracked.battle_completed = data["completed"]
            self._broadcast(tracked.run_id, stage, tracked.snapshot())

        max_retries = 5
        tracked.retry_total = max_retries
        for attempt in range(max_retries):
            tracked.retry_attempt = attempt
            try:
                result = await run_evolution(
                    store=self.store,
                    role=tracked.role,
                    training_games=training_games,
                    battle_games=battle_games,
                    game_concurrency=game_concurrency,
                    llm_semaphore=asyncio.Semaphore(llm_concurrency),
                    llm_rate_limiter=AsyncRateLimiter(llm_rpm),
                    model_adapter=model_adapter,
                    on_progress=_on_progress,
                )
                tracked.run = result
                tracked.artifact_run_id = result.run_id
                tracked.training_run_id = result.training_run_id
                tracked.training_output_dir = result.training_output_dir
                tracked.status = result.status
                tracked.stage = result.status
                self._broadcast(tracked.run_id, result.status, tracked.snapshot())
                return
            except Exception as exc:
                if _is_rate_limit_error(exc) and attempt < max_retries - 1:
                    wait = 30 * (attempt + 1)
                    _log.warning("Rate limited on run %s, retrying in %ds (attempt %d/%d)", tracked.run_id, wait, attempt + 1, max_retries)
                    tracked.status = "rate_limited"
                    tracked.stage = "rate_limited"
                    self._broadcast(tracked.run_id, "rate_limited", tracked.snapshot())
                    await asyncio.sleep(wait)
                    continue
                _log.exception("Role evolution run %s failed", tracked.run_id)
                tracked.status = "failed"
                tracked.stage = "failed"
                tracked.error = str(exc)
                self._broadcast(tracked.run_id, "failed", tracked.snapshot())
                return
