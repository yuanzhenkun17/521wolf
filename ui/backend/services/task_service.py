"""Task lifecycle service for UI backend background jobs."""

from __future__ import annotations

from typing import Any, Protocol

from ui.backend.services.task_persistence_service import TaskPersistenceService
from ui.backend.task_events import TaskEventLog


class BackgroundTaskServiceProtocol(Protocol):
    """Task operations exposed to backend services and routes."""

    def open_connection(self) -> Any:
        ...

    @property
    def task_event_log(self) -> TaskEventLog:
        ...

    def touch_background_task(self, entity: dict[str, Any], *, timestamp: str | None = None) -> str:
        ...

    def task_progress_percent(self, entity: dict[str, Any], default: float = 0.0) -> float:
        ...

    def mark_benchmark_stage(
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
        ...

    def persist_background_tasks(self) -> None:
        ...

    def restore_background_tasks(self) -> int:
        ...


class TaskService:
    """Own background task persistence, recovery, and event publishing."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._persistence = TaskPersistenceService(
            store,
            open_connection=self.open_connection,
            task_event_log=lambda: self.task_event_log,
        )

    def open_connection(self) -> Any:
        from storage.provider import open_wolf_connection

        return open_wolf_connection(paths=getattr(self._store, "paths", None))

    @property
    def task_event_log(self) -> TaskEventLog:
        if self._store._task_event_log is None:
            self._store._task_event_log = TaskEventLog(connection_factory=self.open_connection)
            self._store._task_event_log.load()
        return self._store._task_event_log

    def touch_background_task(self, entity: dict[str, Any], *, timestamp: str | None = None) -> str:
        return TaskPersistenceService.touch_background_task(entity, timestamp=timestamp)

    @staticmethod
    def task_progress_percent(entity: dict[str, Any], default: float = 0.0) -> float:
        return TaskPersistenceService.task_progress_percent(entity, default)

    @staticmethod
    def append_background_diagnostic(
        entity: dict[str, Any],
        diagnostic: dict[str, Any],
        *,
        stage: str,
        timestamp: str,
    ) -> None:
        TaskPersistenceService.append_background_diagnostic(
            entity,
            diagnostic,
            stage=stage,
            timestamp=timestamp,
        )

    def mark_benchmark_stage(
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
        heartbeat = self.touch_background_task(batch)
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
            self.append_background_diagnostic(batch, diagnostic, stage=stage, timestamp=heartbeat)

    def background_tasks_payload(self) -> dict[str, Any]:
        return self._persistence.background_tasks_payload()

    @staticmethod
    def background_tasks_fingerprint(payload: dict[str, Any]) -> str:
        return TaskPersistenceService.background_tasks_fingerprint(payload)

    def persist_background_tasks(self) -> None:
        self._persistence.persist_background_tasks()

    def persist_background_entities(self, payload: dict[str, Any]) -> None:
        self._persistence.persist_background_entities(payload)

    def changed_background_entities(self) -> list[dict[str, Any]]:
        return self._persistence.changed_background_entities()

    @staticmethod
    def task_entity_key(entity: dict[str, Any]) -> str:
        return TaskPersistenceService.task_entity_key(entity)

    @staticmethod
    def task_entity_fingerprint(entity: dict[str, Any]) -> str:
        return TaskPersistenceService.task_entity_fingerprint(entity)

    def load_background_tasks(self) -> None:
        self._persistence.load_background_tasks()

    def recover_background_tasks(self) -> int:
        return self._persistence.recover_background_tasks()

    def restore_background_tasks(self) -> int:
        return self._persistence.restore_background_tasks()


__all__ = ["BackgroundTaskServiceProtocol", "TaskService"]
