"""Background task compatibility facade for the UI backend store."""

from __future__ import annotations

from typing import Any

from ui.backend.services.task_service import TaskService
from ui.backend.task_events import TaskEventLog


class BackgroundTaskStoreMixin:
    @property
    def task_service(self) -> TaskService:
        return self._task_service()

    @property
    def task_event_log(self) -> TaskEventLog:
        return self.task_service.task_event_log

    def _touch_background_task(self, entity: dict[str, Any], *, timestamp: str | None = None) -> str:
        return self.task_service.touch_background_task(entity, timestamp=timestamp)

    @staticmethod
    def _task_progress_percent(entity: dict[str, Any], default: float = 0.0) -> float:
        return TaskService.task_progress_percent(entity, default)

    @staticmethod
    def _append_background_diagnostic(
        entity: dict[str, Any],
        diagnostic: dict[str, Any],
        *,
        stage: str,
        timestamp: str,
    ) -> None:
        TaskService.append_background_diagnostic(entity, diagnostic, stage=stage, timestamp=timestamp)

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
        self.task_service.mark_benchmark_stage(
            batch,
            stage,
            status=status,
            percent=percent,
            role=role,
            role_index=role_index,
            role_count=role_count,
            completed_roles=completed_roles,
            diagnostic=diagnostic,
        )

    def _persist_background_tasks(self) -> None:
        self.task_service.persist_background_tasks()

    def restore_background_tasks(self) -> int:
        return self.task_service.restore_background_tasks()
