"""Background task persistence and recovery mixin for the UI backend store."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.util.json import to_jsonable
from app.util.time import beijing_now_iso
from ui.backend.constants import (
    BACKGROUND_ACTIVE_STATUSES,
)
from ui.backend.task_events import TaskEventLog
from ui.backend.task_state import _set_task_contract

_log = logging.getLogger(__name__)


class BackgroundTaskStoreMixin:
    @property
    def task_event_log(self) -> TaskEventLog:
        if self._task_event_log is None:
            self._task_event_log = TaskEventLog(connection_factory=self._open_ui_task_connection)
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
        changed: list[dict[str, Any]]
        payload: dict[str, Any]
        fingerprint: str
        previous_fingerprint: str | None = None
        try:
            with self.background_state_lock:
                payload = self._background_tasks_payload()
                fingerprint = self._background_tasks_fingerprint(payload)
                if fingerprint == self._background_state_fingerprint:
                    return
                previous_fingerprint = self._background_state_fingerprint
                changed = self._changed_background_entities()
                self._background_state_fingerprint = fingerprint
            self._persist_background_entities(payload)
        except Exception:  # noqa: BLE001 - task index is best-effort UI recovery metadata
            with self.background_state_lock:
                if "fingerprint" in locals() and self._background_state_fingerprint == fingerprint:
                    self._background_state_fingerprint = previous_fingerprint
            _log.warning("failed to persist ui backend task index to PostgreSQL", exc_info=True)
            changed = changed if "changed" in locals() else []
        for entity in changed:
            try:
                self.task_event_log.publish(entity)
            except Exception:  # noqa: BLE001 - task event replay is best-effort UI metadata
                _log.warning("failed to publish task event for %s", self._task_entity_key(entity), exc_info=True)

    def _persist_background_entities(self, payload: dict[str, Any]) -> None:
        conn = self._open_ui_task_connection()
        try:
            _ensure_background_task_tables(conn)
            for entity in [*payload.get("evolution_runs", []), *payload.get("evolution_batches", [])]:
                if not isinstance(entity, dict):
                    continue
                entity_id = self._task_entity_key(entity)
                if not entity_id:
                    continue
                conn.execute(
                    "INSERT INTO ui_background_tasks "
                    "(entity_id, entity_kind, status, payload, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(entity_id) DO UPDATE SET "
                    "entity_kind = excluded.entity_kind, "
                    "status = excluded.status, "
                    "payload = excluded.payload, "
                    "updated_at = excluded.updated_at",
                    (
                        entity_id,
                        entity.get("kind"),
                        entity.get("status"),
                        json.dumps(to_jsonable(entity), ensure_ascii=False),
                        payload.get("updated_at") or beijing_now_iso(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

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
        conn = None
        try:
            conn = self._open_ui_task_connection()
            _ensure_background_task_tables(conn)
            rows = conn.execute(
                "SELECT entity_id, entity_kind, status, payload, updated_at "
                "FROM ui_background_tasks ORDER BY updated_at, entity_id"
            ).fetchall()
        except Exception:  # noqa: BLE001 - task index is best-effort UI recovery metadata
            _log.warning("failed to load ui backend task index from PostgreSQL", exc_info=True)
            return
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001 - cleanup is best-effort
                    pass
        for row in rows:
            payload = _background_payload_from_row(row)
            if payload is None:
                continue
            entity_id = str(payload.get("run_id") or payload.get("batch_id") or row["entity_id"])
            if not entity_id:
                continue
            if payload.get("run_id") or payload.get("kind") == "role_evolution_run":
                payload.setdefault("run_id", entity_id)
                self.evolution_runs.setdefault(entity_id, payload)
            elif payload.get("batch_id") or payload.get("kind") in {"role_evolution_batch", "benchmark_batch"}:
                payload.setdefault("batch_id", entity_id)
                self.evolution_batches.setdefault(entity_id, payload)
        self._background_state_fingerprint = self._background_tasks_fingerprint(self._background_tasks_payload())
        for entity in [*self.evolution_runs.values(), *self.evolution_batches.values()]:
            key = self._task_entity_key(entity)
            if key:
                self._task_event_fingerprints[key] = self._task_entity_fingerprint(entity)

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


def _ensure_background_task_tables(conn: Any) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ui_background_tasks (
            entity_id text PRIMARY KEY,
            entity_kind text NOT NULL,
            status text,
            payload jsonb NOT NULL,
            updated_at timestamptz NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ui_background_tasks_kind "
        "ON ui_background_tasks(entity_kind)"
    )
    conn.commit()


def _background_payload_from_row(row: Any) -> dict[str, Any] | None:
    payload = row["payload"]
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            _log.warning("skipping invalid PostgreSQL ui background task payload for %s", row["entity_id"])
            return None
    if not isinstance(payload, dict):
        return None
    return dict(payload)


