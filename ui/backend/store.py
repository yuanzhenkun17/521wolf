"""Backend store and long-running task orchestration for the UI backend."""

from __future__ import annotations
import json
import logging
import os
import uuid
import asyncio
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.config import PathConfig, load_llm_config, load_tts_config
from app.lib.version import VersionRegistry
from app.run import run_evaluation, run_evolution
from app.services.llm import create_llm
from app.util.json import write_json
from app.util.time import beijing_now_iso
from ui.backend.background_store import BackgroundTaskStoreMixin
from ui.backend.constants import (
    MANUAL_STOP_REASON,
    ROLE_ORDER,
)
from ui.backend.game_store import GameStoreMixin
from ui.backend.schemas import (
    BenchmarkRequest,
    EvolutionStartRequest,
)
from ui.backend.live_game import BroadcastEventSink, LiveGameSession
from ui.backend.task_events import TaskEventLog
from ui.backend.task_state import (
    _set_task_contract,
)

_log = logging.getLogger(__name__)


class _FakeModel:
    async def ainvoke(self, messages: Any) -> Any:
        return type(
            "Result",
            (),
            {
                "content": (
                    '{"choice":null,"target":null,"public_text":"ok",'
                    '"private_reasoning":"ui backend fallback model",'
                    '"confidence":1,"alternatives":[],"rejected_reasons":[],'
                    '"selected_skills":[]}'
                )
            },
        )()


@dataclass
class BackendStore(BackgroundTaskStoreMixin, GameStoreMixin):
    paths: PathConfig
    model: Any | None = None
    games: dict[str, dict[str, Any]] = field(default_factory=dict)
    live_sessions: dict[str, LiveGameSession] = field(default_factory=dict)
    evolution_runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    evolution_batches: dict[str, dict[str, Any]] = field(default_factory=dict)
    background_state_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _background_state_fingerprint: str | None = field(default=None, init=False, repr=False)
    _task_event_fingerprints: dict[str, str] = field(default_factory=dict, init=False, repr=False)
    _task_event_log: TaskEventLog | None = field(default=None, init=False, repr=False)

    @property
    def registry(self) -> VersionRegistry:
        return VersionRegistry(self.paths.registry_dir)

    def _write_background_json(self, path: Path, payload: dict[str, Any]) -> None:
        write_json(path, payload)

    def leaderboard_scores_for_role(self, role: str) -> dict[str, dict[str, Any]]:
        """Load persisted benchmark scores for a role, keyed by version id.

        Reads the benchmark_leaderboard table populated by the eval pipeline.
        Returns {} on any failure so the leaderboard endpoint still renders.
        """
        from app.lib.score import open_eval_connection

        scores: dict[str, dict[str, Any]] = {}
        conn = None
        try:
            conn = open_eval_connection(self.paths)
            rows = conn.execute(
                "SELECT target_version_id, avg_role_score, target_side_win_rate, "
                "fallback_rate, rankable, games_played FROM benchmark_leaderboard "
                "WHERE scope = 'role_version' AND target_role = ? "
                "ORDER BY updated_at DESC",
                (role,),
            ).fetchall()
            for row in rows:
                vid = row["target_version_id"]
                if vid and vid not in scores:  # newest row per version wins
                    scores[vid] = dict(row)
        except Exception:  # noqa: BLE001 — leaderboard read is best-effort
            _log.warning("leaderboard_scores_for_role failed for %s", role, exc_info=True)
        finally:
            if conn is not None:
                conn.close()
        return scores

    def model_for_run(self) -> Any | None:
        if self.model is not None:
            return self.model
        use_fake = os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}
        if use_fake:
            return _FakeModel()
        try:
            return create_llm()
        except RuntimeError:
            _log.warning("LLM config missing; UI backend is using fallback model", exc_info=True)
            return _FakeModel()

    def llm_status(self) -> str:
        if self.model is not None:
            return "configured"
        use_fake = os.environ.get("UI_BACKEND_USE_FAKE_LLM", "").lower() in {"1", "true", "yes"}
        if use_fake:
            return "fallback"
        try:
            load_llm_config()
        except RuntimeError:
            return "fallback"
        return "configured"

    def tts_status(self) -> str:
        try:
            load_tts_config()
        except RuntimeError:
            return "fallback"
        return "configured"

    def queue_evolution(self, request: EvolutionStartRequest) -> dict[str, Any]:
        roles = request.roles or ["villager"]
        if len(roles) == 1:
            return self._create_evolution_run(roles[0], request)

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
            "config": request.model_dump(),
        }
        self.evolution_batches[batch_id] = batch
        for role in roles:
            run = self._create_evolution_run(role, request, batch_id=batch_id, status="queued")
            batch["runs"].append(run["run_id"])
        self._persist_background_tasks()
        return batch

    def _create_evolution_run(
        self,
        role: str,
        request: EvolutionStartRequest,
        *,
        batch_id: str | None = None,
        status: str = "running",
    ) -> dict[str, Any]:
        run_id = f"evolve_{role}_{uuid.uuid4().hex[:8]}"
        now = beijing_now_iso()
        stage = "queued"
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
            "config": request.model_dump(),
        }
        self.evolution_runs[run_id] = run
        self._persist_background_tasks()
        return run

    @staticmethod
    def _count_evolution_games(value: Any) -> int:
        if isinstance(value, list):
            return len([item for item in value if isinstance(item, dict)])
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def _evolution_overall_progress(self, run: dict[str, Any]) -> dict[str, Any]:
        progress = run.get("progress") if isinstance(run.get("progress"), dict) else {}
        config = run.get("config") if isinstance(run.get("config"), dict) else {}
        training_total = self._count_evolution_games(run.get("training_game_count") or config.get("training_games"))
        battle_per_side = self._count_evolution_games(run.get("battle_game_count") or config.get("battle_games"))
        training_completed = self._count_evolution_games(run.get("training_completed") or run.get("training_games"))
        battle_completed = self._count_evolution_games(run.get("battle_completed") or run.get("battle_games"))
        total = training_total + battle_per_side * 2
        completed = training_completed + battle_completed
        terminal = str(run.get("status") or "").lower() in {"reviewing", "promoted", "rejected", "completed"}
        percent = (completed / total) if total > 0 else self._task_progress_percent(run)
        if terminal:
            percent = max(percent, 1.0)
        return {
            "stage": str(run.get("current_stage") or progress.get("stage") or run.get("status") or ""),
            "percent": max(0.0, min(1.0, float(percent))),
            "training_completed": training_completed,
            "training_total": training_total,
            "battle_completed": battle_completed,
            "battle_total": battle_per_side * 2,
            "battle_requested_per_side": battle_per_side,
            "updated_at": run.get("last_heartbeat_at") or progress.get("updated_at") or beijing_now_iso(),
        }

    def _sync_evolution_progress(self, run_id: str, snapshot: dict[str, Any]) -> None:
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
        run["training_game_count"] = self._count_evolution_games(
            snapshot.get("training_game_count") or run.get("training_game_count")
        )
        run["battle_game_count"] = self._count_evolution_games(
            snapshot.get("battle_game_count") or run.get("battle_game_count")
        )
        run["training_completed"] = self._count_evolution_games(run.get("training_games"))
        run["battle_completed"] = self._count_evolution_games(run.get("battle_games"))
        heartbeat = self._touch_background_task(run, timestamp=snapshot.get("last_heartbeat_at"))
        run["overall_progress"] = self._evolution_overall_progress(run)
        run["overall_progress"]["updated_at"] = heartbeat
        self._refresh_evolution_batch(run.get("batch_id"))
        self._persist_background_tasks()

    def _evolution_cancel_check(self, run_id: str) -> bool:
        run = self.evolution_runs.get(run_id)
        if run is None:
            return True
        if run.get("stop_requested") or run.get("cancelled"):
            return True
        batch_id = run.get("batch_id")
        batch = self.evolution_batches.get(str(batch_id)) if batch_id else None
        return bool(batch and (batch.get("stop_requested") or batch.get("cancelled")))

    def _run_summary_for_batch(self, run: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": run.get("run_id"),
            "role": run.get("role"),
            "status": run.get("status"),
            "current_stage": run.get("current_stage"),
            "progress": run.get("progress") if isinstance(run.get("progress"), dict) else {},
            "overall_progress": run.get("overall_progress") if isinstance(run.get("overall_progress"), dict) else self._evolution_overall_progress(run),
            "training_completed": self._count_evolution_games(run.get("training_completed") or run.get("training_games")),
            "training_game_count": self._count_evolution_games(run.get("training_game_count")),
            "battle_completed": self._count_evolution_games(run.get("battle_completed") or run.get("battle_games")),
            "battle_game_count": self._count_evolution_games(run.get("battle_game_count")),
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

    def _refresh_evolution_batch(self, batch_id: Any) -> None:
        if not batch_id:
            return
        batch = self.evolution_batches.get(str(batch_id))
        if batch is None or batch.get("kind") != "role_evolution_batch":
            return
        run_ids = [str(item) for item in batch.get("runs", []) or []]
        summaries = [
            self._run_summary_for_batch(self.evolution_runs[run_id])
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
            "percent": (completed / total) if total else 0.0,
            "completed_roles": completed,
            "role_count": total,
            "total_roles": total,
            "updated_at": heartbeat,
        }
        batch["overall_progress"] = dict(batch["progress"])

    def _mark_evolution_stopped(self, entity: dict[str, Any]) -> None:
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
            entity["overall_progress"] = self._evolution_overall_progress(entity)
        elif entity.get("kind") == "role_evolution_batch":
            self._refresh_evolution_batch(entity.get("batch_id"))

    async def run_queued_evolution(self, run_id: str, request: EvolutionStartRequest) -> None:
        run = self.evolution_runs.get(run_id)
        if run is None:
            return
        if self._evolution_cancel_check(run_id):
            self._mark_evolution_stopped(run)
            self._persist_background_tasks()
            return
        role = str(run.get("role") or "villager")
        run["status"] = "training"
        run["current_stage"] = "training"
        run.setdefault("started_at", beijing_now_iso())
        self._touch_background_task(run)
        run["overall_progress"] = self._evolution_overall_progress(run)
        self._persist_background_tasks()
        try:
            result = await run_evolution(
                role=role,
                training_games=request.training_games,
                battle_games=request.battle_games,
                max_days=request.max_days,
                auto_promote=request.auto_promote,
                run_id=run_id,
                model=self.model_for_run(),
                paths=self.paths,
                progress_sink=lambda snapshot: self._sync_evolution_progress(run_id, snapshot),
                cancel_check=lambda: self._evolution_cancel_check(run_id),
            )
        except Exception as exc:  # pragma: no cover - defensive background failure path
            if self._evolution_cancel_check(run_id) or str(exc) == MANUAL_STOP_REASON:
                self._mark_evolution_stopped(run)
                self._refresh_evolution_batch(run.get("batch_id"))
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

        if self._evolution_cancel_check(run_id):
            self._mark_evolution_stopped(run)
            self._refresh_evolution_batch(run.get("batch_id"))
            self._persist_background_tasks()
            return
        run.update(result)
        run["run_id"] = result.get("run_id") or run_id
        run["role"] = role
        run["status"] = result.get("status", "reviewing")
        _set_task_contract(run, failed=run["status"] == "failed", cancelled=False, interrupted=False)
        run["started_at"] = run.get("started_at") or beijing_now_iso()
        run["finished_at"] = result.get("finished_at") or beijing_now_iso()
        self._touch_background_task(run)
        run["training_completed"] = self._count_evolution_games(run.get("training_games"))
        run["battle_completed"] = self._count_evolution_games(run.get("battle_games"))
        run["overall_progress"] = self._evolution_overall_progress(run)
        self._refresh_evolution_batch(run.get("batch_id"))
        self._persist_background_tasks()

    async def run_queued_evolution_batch(self, batch_id: str, request: EvolutionStartRequest) -> None:
        batch = self.evolution_batches.get(batch_id)
        if batch is None:
            return
        batch["status"] = "running"
        _set_task_contract(batch, failed=False, cancelled=False, interrupted=False)
        self._refresh_evolution_batch(batch_id)
        self._touch_background_task(batch)
        self._persist_background_tasks()
        try:
            for run_id in list(batch.get("runs", [])):
                if batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "rejected"}:
                    break
                self._touch_background_task(batch)
                self._refresh_evolution_batch(batch_id)
                self._persist_background_tasks()
                await self.run_queued_evolution(str(run_id), request)
                self._touch_background_task(batch)
                self._refresh_evolution_batch(batch_id)
                self._persist_background_tasks()
            if batch.get("stop_requested") or batch.get("cancelled"):
                batch["status"] = "failed"
                batch["error"] = batch.get("error") or MANUAL_STOP_REASON
                _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
                self._mark_evolution_stopped(batch)
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
            self._refresh_evolution_batch(batch_id)
            self._persist_background_tasks()

    async def _run_single_evolution(self, role: str, request: EvolutionStartRequest) -> dict[str, Any]:
        run = self._create_evolution_run(role, request)
        run_id = run["run_id"]
        result = await run_evolution(
            role=role,
            training_games=request.training_games,
            battle_games=request.battle_games,
            max_days=request.max_days,
            auto_promote=request.auto_promote,
            run_id=run_id,
            model=self.model_for_run(),
            paths=self.paths,
        )
        run.update(result)
        run["run_id"] = result.get("run_id") or run_id
        run["role"] = role
        run["status"] = result.get("status", "reviewing")
        _set_task_contract(run, failed=run["status"] == "failed", cancelled=False, interrupted=False)
        run["started_at"] = run.get("started_at") or beijing_now_iso()
        run["finished_at"] = result.get("finished_at") or beijing_now_iso()
        self._touch_background_task(run)
        self._persist_background_tasks()
        return run

    def queue_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        batch_id = f"bench_{uuid.uuid4().hex[:10]}"
        now = beijing_now_iso()
        batch = {
            "kind": "benchmark_batch",
            "schema_version": 1,
            "batch_id": batch_id,
            "roles": list(request.roles),
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
                "role_count": len(request.roles or []),
                "total_roles": len(request.roles or []),
                "updated_at": now,
            },
            "diagnostics": [],
            "config": request.model_dump(),
            "result": None,
            "error": None,
        }
        self.evolution_batches[batch_id] = batch
        self._persist_background_tasks()
        return batch

    async def run_queued_benchmark(self, batch_id: str, request: BenchmarkRequest) -> None:
        batch = self.evolution_batches.get(batch_id)
        if batch is None:
            return
        if batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "cancelled"}:
            batch["finished_at"] = batch.get("finished_at") or beijing_now_iso()
            batch["error"] = batch.get("error") or MANUAL_STOP_REASON
            _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
            self._mark_benchmark_stage(
                batch,
                "stopped",
                status="failed",
                percent=self._task_progress_percent(batch),
                diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
            )
            self._persist_background_tasks()
            return

        # One evaluation batch per requested role, each pinned to that role's
        # current baseline version, grouped so the leaderboard is attributable.
        roles = [r for r in (request.roles or []) if r] or [None]
        role_count = len(roles)
        results: list[dict[str, Any]] = []
        self._mark_benchmark_stage(
            batch,
            "preparing",
            status="running",
            percent=0.0,
            role_count=role_count,
            completed_roles=0,
        )
        self._persist_background_tasks()
        try:
            for index, role in enumerate(roles):
                if batch.get("stop_requested") or batch.get("cancelled"):
                    break
                role_label = role or "all"
                self._mark_benchmark_stage(
                    batch,
                    "evaluating",
                    status="running",
                    percent=index / role_count if role_count else 0.0,
                    role=role_label,
                    role_index=index + 1,
                    role_count=role_count,
                    completed_roles=index,
                )
                self._persist_background_tasks()
                results.append(
                    await run_evaluation(
                        batch_config=self._benchmark_batch_config(batch_id, role, request, index),
                        model=self.model_for_run(),
                        paths=self.paths,
                    )
                )
                self._mark_benchmark_stage(
                    batch,
                    "evaluating",
                    status="running",
                    percent=(index + 1) / role_count if role_count else 1.0,
                    role=role_label,
                    role_index=index + 1,
                    role_count=role_count,
                    completed_roles=index + 1,
                )
                self._persist_background_tasks()
        except Exception as exc:  # pragma: no cover - defensive background failure path
            batch["finished_at"] = beijing_now_iso()
            batch["error"] = str(exc)
            _set_task_contract(batch, failed=True, cancelled=False, interrupted=False)
            self._mark_benchmark_stage(
                batch,
                "failed",
                status="failed",
                percent=self._task_progress_percent(batch),
                diagnostic={
                    "kind": "benchmark_error",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                },
            )
            self._persist_background_tasks()
            return

        if batch.get("stop_requested") or batch.get("cancelled") or batch.get("status") in {"failed", "cancelled"}:
            batch["finished_at"] = batch.get("finished_at") or beijing_now_iso()
            batch["error"] = batch.get("error") or MANUAL_STOP_REASON
            _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
            self._mark_benchmark_stage(
                batch,
                "stopped",
                status="failed",
                percent=self._task_progress_percent(batch),
                completed_roles=len(results),
                role_count=role_count,
                diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
            )
            self._persist_background_tasks()
            return

        batch["status"] = "completed"
        _set_task_contract(batch, stop_requested=False, cancelled=False, interrupted=False, failed=False)
        batch["started_at"] = (results[0].get("started_at") if results else None) or batch.get("started_at") or beijing_now_iso()
        batch["finished_at"] = beijing_now_iso()
        # Keep the first result as the headline; expose all per-role results too.
        batch["result"] = results[0] if results else None
        batch["results"] = results
        self._mark_benchmark_stage(
            batch,
            "completed",
            status="completed",
            percent=1.0,
            role_count=role_count,
            completed_roles=len(results),
        )
        self._persist_background_tasks()

    def _benchmark_batch_config(
        self, batch_id: str, role: str | None, request: BenchmarkRequest, index: int
    ) -> dict[str, Any]:
        """Build a role-version eval batch config pinned to the role's baseline."""
        cfg: dict[str, Any] = {
            "batch_id": f"{batch_id}_{role}" if role else batch_id,
            "comparison_group_id": batch_id,
            "game_count": request.battle_games,
            "max_days": request.max_days,
            "model_id": getattr(self, "model_id", None),
        }
        if role:
            baseline = self.registry.get_baseline(role)
            if baseline:
                cfg["comparison_type"] = "role_version"
                cfg["target_role"] = role
                cfg["target_version_id"] = baseline
        return cfg



