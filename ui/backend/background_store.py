"""Background task persistence and recovery mixin for the UI backend store."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.util.json import read_json, to_jsonable
from app.util.time import beijing_now_iso
from ui.backend.constants import (
    BACKGROUND_ACTIVE_STATUSES,
    BACKGROUND_STABLE_STATUSES,
    BACKGROUND_STATE_FILE,
    TASK_EVENT_LOG_FILE,
)
from ui.backend.task_events import TaskEventLog
from ui.backend.task_state import _set_task_contract

_log = logging.getLogger(__name__)


class BackgroundTaskStoreMixin:
    @property
    def _background_state_path(self) -> Path:
        return self.paths.runs_dir / BACKGROUND_STATE_FILE

    @property
    def task_event_log(self) -> TaskEventLog:
        if self._task_event_log is None:
            self._task_event_log = TaskEventLog(self.paths.runs_dir / TASK_EVENT_LOG_FILE)
            self._task_event_log.load()
        return self._task_event_log

    def _touch_background_task(self, entity: dict[str, Any], *, timestamp: str | None = None) -> str:
        heartbeat = timestamp or beijing_now_iso()
        entity["last_heartbeat_at"] = heartbeat
        return heartbeat

    @staticmethod
    def _task_progress_percent(entity: dict[str, Any], default: float = 0.0) -> float:
        progress = entity.get("progress")
        if not isinstance(progress, dict):
            return default
        try:
            return float(progress.get("percent", default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _append_background_diagnostic(
        entity: dict[str, Any],
        diagnostic: dict[str, Any],
        *,
        stage: str,
        timestamp: str,
    ) -> None:
        diagnostics = entity.get("diagnostics")
        if not isinstance(diagnostics, list):
            diagnostics = []
            entity["diagnostics"] = diagnostics
        item = {key: value for key, value in diagnostic.items() if value is not None}
        item.setdefault("stage", stage)
        item.setdefault("at", timestamp)
        identity = (item.get("kind"), item.get("stage"), item.get("message"))
        for existing in diagnostics:
            if not isinstance(existing, dict):
                continue
            if (existing.get("kind"), existing.get("stage"), existing.get("message")) == identity:
                return
        diagnostics.append(item)

    def _mark_benchmark_stage(
        self,
        batch: dict[str, Any],
        stage: str,
        *,
        status: str | None = None,
        percent: float | None = None,
        role: str | None = None,
        role_index: int | None = None,
        role_count: int | None = None,
        completed_roles: int | None = None,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        if status is not None:
            batch["status"] = status
        heartbeat = self._touch_background_task(batch)
        batch["current_stage"] = stage
        progress = batch.get("progress")
        progress = dict(progress) if isinstance(progress, dict) else {}
        progress["stage"] = stage
        if percent is not None:
            progress["percent"] = max(0.0, min(1.0, float(percent)))
        if role is not None:
            progress["role"] = role
        if role_index is not None:
            progress["role_index"] = role_index
        if role_count is not None:
            progress["role_count"] = role_count
            progress["total_roles"] = role_count
        if completed_roles is not None:
            progress["completed_roles"] = completed_roles
        progress["updated_at"] = heartbeat
        batch["progress"] = progress
        if diagnostic is not None:
            self._append_background_diagnostic(batch, diagnostic, stage=stage, timestamp=heartbeat)

    def _background_tasks_payload(self) -> dict[str, Any]:
        payload = {
            "kind": "ui_backend_background_tasks",
            "schema_version": 1,
            "updated_at": beijing_now_iso(),
            "evolution_runs": list(self.evolution_runs.values()),
            "evolution_batches": list(self.evolution_batches.values()),
        }
        return to_jsonable(payload)

    @staticmethod
    def _background_tasks_fingerprint(payload: dict[str, Any]) -> str:
        comparable = dict(payload)
        comparable["updated_at"] = None
        return json.dumps(comparable, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def _persist_background_tasks(self) -> None:
        try:
            with self.background_state_lock:
                payload = self._background_tasks_payload()
                fingerprint = self._background_tasks_fingerprint(payload)
                if fingerprint == self._background_state_fingerprint:
                    return
                self._write_background_json(self._background_state_path, payload)
                self._background_state_fingerprint = fingerprint
                changed = self._changed_background_entities()
        except Exception:  # noqa: BLE001 - task index is best-effort UI recovery metadata
            _log.warning("failed to persist ui backend task index", exc_info=True)
            return
        for entity in changed:
            try:
                self.task_event_log.publish(entity)
            except Exception:  # noqa: BLE001 - task event replay is best-effort UI metadata
                _log.warning("failed to publish task event for %s", self._task_entity_key(entity), exc_info=True)

    def _changed_background_entities(self) -> list[dict[str, Any]]:
        changed: list[dict[str, Any]] = []
        for entity in [*self.evolution_runs.values(), *self.evolution_batches.values()]:
            key = self._task_entity_key(entity)
            if not key:
                continue
            fingerprint = self._task_entity_fingerprint(entity)
            if self._task_event_fingerprints.get(key) == fingerprint:
                continue
            self._task_event_fingerprints[key] = fingerprint
            changed.append(entity)
        return changed

    @staticmethod
    def _task_entity_key(entity: dict[str, Any]) -> str:
        return str(entity.get("run_id") or entity.get("batch_id") or "")

    @staticmethod
    def _task_entity_fingerprint(entity: dict[str, Any]) -> str:
        comparable = {
            key: entity.get(key)
            for key in (
                "kind",
                "status",
                "stop_requested",
                "cancelled",
                "interrupted",
                "failed",
                "finished_at",
                "last_heartbeat_at",
                "cancelled_at",
                "interrupted_at",
                "current_stage",
                "progress",
                "diagnostics",
                "recommendation",
                "error",
            )
            if key in entity
        }
        return json.dumps(to_jsonable(comparable), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def load_background_tasks(self) -> None:
        state_path = self._background_state_path
        if state_path.exists():
            try:
                payload = read_json(state_path)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                _log.warning("failed to load ui backend task index %s", state_path, exc_info=True)
            else:
                if isinstance(payload, dict):
                    for run in payload.get("evolution_runs", []) or []:
                        if not isinstance(run, dict):
                            continue
                        run_id = run.get("run_id")
                        if run_id:
                            self.evolution_runs.setdefault(str(run_id), dict(run))
                    for batch in payload.get("evolution_batches", []) or []:
                        if not isinstance(batch, dict):
                            continue
                        batch_id = batch.get("batch_id")
                        if batch_id:
                            self.evolution_batches.setdefault(str(batch_id), dict(batch))
        self._load_evolution_state_runs()

    def _load_evolution_state_runs(self) -> None:
        if not self.paths.evolution_dir.exists():
            return
        for state_path in sorted(self.paths.evolution_dir.glob("*/state.json")):
            try:
                payload = read_json(state_path)
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                _log.warning("failed to load evolution run state %s", state_path, exc_info=True)
                continue
            if not isinstance(payload, dict):
                continue
            run = self._evolution_state_to_ui_run(payload, state_path=state_path)
            if run is None:
                continue
            run_id = str(run["run_id"])
            existing = self.evolution_runs.get(run_id)
            if existing is None:
                self.evolution_runs[run_id] = run
            else:
                self._merge_evolution_state_run(existing, run)

    def _evolution_state_to_ui_run(
        self,
        payload: dict[str, Any],
        *,
        state_path: Path,
    ) -> dict[str, Any] | None:
        run_id = str(payload.get("run_id") or state_path.parent.name).strip()
        if not run_id:
            return None
        role = str(payload.get("role") or "").strip()
        training_games, training_count = self._restore_evolution_games(payload.get("training_games"))
        battle_games, battle_count = self._restore_evolution_games(payload.get("battle_games"))
        training_count = self._restore_count(payload.get("training_game_count"), training_count)
        battle_count = self._restore_count(payload.get("battle_game_count"), battle_count)
        proposals = self._restore_evolution_proposals(payload.get("proposals"))
        diff = [dict(item) for item in payload.get("diff", []) or [] if isinstance(item, dict)]
        config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        if not config:
            config = {
                "roles": [role] if role else [],
                "training_games": training_count,
                "battle_games": battle_count,
            }
        updated_at = payload.get("last_heartbeat_at") or payload.get("updated_at")
        run = {
            "kind": "role_evolution_run",
            "schema_version": self._restore_count(payload.get("schema_version"), 1) or 1,
            "run_id": run_id,
            "role": role,
            "status": str(payload.get("status") or ""),
            "started_at": payload.get("started_at"),
            "finished_at": payload.get("finished_at"),
            "last_heartbeat_at": updated_at,
            "parent_hash": payload.get("parent_hash"),
            "candidate_hash": payload.get("candidate_hash"),
            "candidate_skill_dir": payload.get("candidate_skill_dir"),
            "baseline_skill_dir": payload.get("baseline_skill_dir"),
            "training_run_id": payload.get("training_run_id"),
            "training_output_dir": payload.get("training_output_dir"),
            "training_games": training_games,
            "training_game_count": training_count,
            "training_completed": training_count,
            "battle_games": battle_games,
            "battle_game_count": battle_count,
            "battle_completed": battle_count,
            "battle_result": payload.get("battle_result") if isinstance(payload.get("battle_result"), dict) else {},
            "proposals": proposals,
            "diff": diff,
            "current_stage": payload.get("current_stage"),
            "progress": payload.get("progress") if isinstance(payload.get("progress"), dict) else {},
            "diagnostics": [dict(item) for item in payload.get("diagnostics", []) or [] if isinstance(item, dict)],
            "warnings": list(payload.get("warnings", []) or []),
            "errors": list(payload.get("errors", []) or []),
            "config": config,
            "source_state_path": str(state_path),
        }
        if payload.get("batch_id"):
            run["batch_id"] = payload.get("batch_id")
        if payload.get("interrupted_at"):
            run["interrupted_at"] = payload.get("interrupted_at")
        if payload.get("error"):
            run["error"] = payload.get("error")
        return {key: value for key, value in run.items() if value is not None}

    def _merge_evolution_state_run(self, existing: dict[str, Any], restored: dict[str, Any]) -> None:
        existing_status = str(existing.get("status") or "").lower()
        restored_status = str(restored.get("status") or "").lower()
        for key, value in restored.items():
            if self._missing_background_value(existing.get(key)) and not self._missing_background_value(value):
                existing[key] = value
        if existing_status in BACKGROUND_ACTIVE_STATUSES and restored_status in BACKGROUND_STABLE_STATUSES:
            for key in (
                "status",
                "finished_at",
                "parent_hash",
                "candidate_hash",
                "candidate_skill_dir",
                "baseline_skill_dir",
                "training_run_id",
                "training_output_dir",
                "training_games",
                "training_game_count",
                "training_completed",
                "battle_games",
                "battle_game_count",
                "battle_completed",
                "battle_result",
                "proposals",
                "diff",
                "current_stage",
                "progress",
                "diagnostics",
                "warnings",
                "errors",
            ):
                if key in restored and not self._missing_background_value(restored.get(key)):
                    existing[key] = restored[key]

    @staticmethod
    def _restore_evolution_games(raw: Any) -> tuple[list[dict[str, Any]], int]:
        if isinstance(raw, list):
            games = [dict(item) for item in raw if isinstance(item, dict)]
            return games, len(games)
        return [], BackgroundTaskStoreMixin._restore_count(raw, 0)

    @staticmethod
    def _restore_count(raw: Any, default: int) -> int:
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _restore_evolution_proposals(raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, dict):
            raw = raw.get("proposals", [])
        if not isinstance(raw, list):
            return []
        return [dict(item) for item in raw if isinstance(item, dict)]

    @staticmethod
    def _missing_background_value(value: Any) -> bool:
        return value is None or value == "" or value == [] or value == {}

    def recover_background_tasks(self) -> int:
        now = beijing_now_iso()
        recovered = 0
        for entity in [*self.evolution_runs.values(), *self.evolution_batches.values()]:
            status = str(entity.get("status") or "").lower()
            if status not in BACKGROUND_ACTIVE_STATUSES:
                continue
            previous_stage = entity.get("current_stage") or (
                entity.get("progress", {}).get("stage") if isinstance(entity.get("progress"), dict) else None
            ) or status
            entity["status"] = "interrupted"
            _set_task_contract(entity, stop_requested=False, cancelled=False, interrupted=True, failed=False)
            if not entity.get("last_heartbeat_at"):
                entity["last_heartbeat_at"] = now
            entity["interrupted_at"] = entity.get("interrupted_at") or now
            entity["finished_at"] = entity.get("finished_at") or now
            entity["error"] = entity.get("error") or "interrupted by backend restart"
            progress = entity.get("progress")
            progress = dict(progress) if isinstance(progress, dict) else {}
            progress["stage"] = "interrupted"
            progress.setdefault("percent", self._task_progress_percent(entity))
            progress["previous_stage"] = previous_stage
            progress["updated_at"] = entity.get("last_heartbeat_at") or now
            entity["current_stage"] = "interrupted"
            entity["progress"] = progress
            if entity.get("kind") == "benchmark_batch":
                progress.setdefault("completed_roles", 0)
                progress.setdefault("role_count", len(entity.get("roles", []) or []))
                progress.setdefault("total_roles", len(entity.get("roles", []) or []))
                self._append_background_diagnostic(
                    entity,
                    {
                        "kind": "benchmark_interrupted",
                        "message": entity["error"],
                    },
                    stage="interrupted",
                    timestamp=entity["interrupted_at"],
                )
            else:
                if entity.get("kind") == "role_evolution_batch":
                    progress.setdefault("completed_roles", 0)
                    progress.setdefault("role_count", len(entity.get("roles", []) or []))
                    progress.setdefault("total_roles", len(entity.get("roles", []) or []))
                    diagnostic_kind = "evolution_batch_interrupted"
                else:
                    progress.setdefault("completed_games", progress.get("completed_games", 0))
                    diagnostic_kind = "evolution_interrupted"
                self._append_background_diagnostic(
                    entity,
                    {
                        "kind": diagnostic_kind,
                        "message": entity["error"],
                        "previous_stage": previous_stage,
                    },
                    stage="interrupted",
                    timestamp=entity["interrupted_at"],
                )
            recovered += 1
        if recovered:
            self._persist_background_tasks()
        return recovered

    def restore_background_tasks(self) -> int:
        self.load_background_tasks()
        return self.recover_background_tasks()


