"""Task lifecycle service for UI backend background jobs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from app.util.time import beijing_now_iso
from storage.artifacts import LocalArtifactStore
from storage.postgres.unit_of_work import from_connection_factory
from storage.ui import TaskArtifactRepository, TaskQueueRepository, TaskWorkerRepository
from ui.backend.services.task_persistence_service import TaskPersistenceService
from ui.backend.task_events import TaskEventLog


class BackgroundTaskServiceProtocol(Protocol):
    """Task operations exposed to backend services and routes."""

    def open_connection(self) -> Any:
        ...

    def list_task_queue_rows(
        self,
        *,
        statuses: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        ...

    def get_task_queue_row(self, task_id: str) -> dict[str, Any] | None:
        ...

    def enqueue_task(
        self,
        *,
        task_id: str,
        kind: str,
        payload: dict[str, Any],
        priority: int = 100,
        idempotency_key: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def list_task_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        ...

    def put_task_json_artifact(
        self,
        *,
        task_id: str,
        name: str,
        payload: Any,
        artifact_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def put_task_bytes_artifact(
        self,
        *,
        task_id: str,
        name: str,
        data: bytes,
        artifact_type: str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        ...

    def retry_task(self, task_id: str) -> dict[str, Any] | None:
        ...

    def list_task_events(self, task_id: str, *, after_event_id: int = 0) -> list[dict[str, Any]]:
        ...

    def task_artifact_file(self, task_id: str, artifact_id: str) -> tuple[dict[str, Any], Path] | None:
        ...

    def task_control_health(self) -> dict[str, Any]:
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

    def load_background_tasks(self) -> None:
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

    def list_task_queue_rows(
        self,
        *,
        statuses: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conn = self.open_connection()
        try:
            return TaskQueueRepository(conn).list_recent(statuses=statuses, limit=limit)
        finally:
            conn.close()

    def get_task_queue_row(self, task_id: str) -> dict[str, Any] | None:
        conn = self.open_connection()
        try:
            return TaskQueueRepository(conn).get(task_id)
        finally:
            conn.close()

    def enqueue_task(
        self,
        *,
        task_id: str,
        kind: str,
        payload: dict[str, Any],
        priority: int = 100,
        idempotency_key: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = beijing_now_iso()
        with from_connection_factory(self.open_connection) as tx:
            repo = TaskQueueRepository(tx.connection)
            existing = repo.get(task_id)
            if existing is not None:
                tx.commit()
                return existing
            repo.enqueue(
                task_id=task_id,
                kind=kind,
                payload=payload,
                queued_at=now,
                updated_at=now,
                priority=priority,
                idempotency_key=idempotency_key,
                source=source,
                metadata=metadata,
            )
            task = repo.get(task_id)
            if task is None:  # pragma: no cover - repository contract guard
                raise RuntimeError(f"task was not persisted: {task_id}")
            tx.commit()
        self.publish_task_queue_event(task, event="queued")
        return task

    def list_task_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        conn = self.open_connection()
        try:
            return TaskArtifactRepository(conn).list_for_task(task_id)
        finally:
            conn.close()

    def put_task_json_artifact(
        self,
        *,
        task_id: str,
        name: str,
        payload: Any,
        artifact_type: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._put_task_artifact(
            task_id=task_id,
            name=name,
            payload=payload,
            data=None,
            artifact_type=artifact_type,
            content_type="application/json",
            metadata=metadata,
        )

    def put_task_bytes_artifact(
        self,
        *,
        task_id: str,
        name: str,
        data: bytes,
        artifact_type: str,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._put_task_artifact(
            task_id=task_id,
            name=name,
            payload=None,
            data=data,
            artifact_type=artifact_type,
            content_type=content_type,
            metadata=metadata,
        )

    def _put_task_artifact(
        self,
        *,
        task_id: str,
        name: str,
        payload: Any,
        data: bytes | None,
        artifact_type: str,
        content_type: str | None,
        metadata: dict[str, Any] | None,
    ) -> dict[str, Any]:
        created_at = beijing_now_iso()
        with from_connection_factory(self.open_connection) as tx:
            store = LocalArtifactStore(root=self.task_artifact_root, repo=TaskArtifactRepository(tx.connection))
            if data is None:
                artifact = store.put_json(
                    task_id=task_id,
                    name=name,
                    payload=payload,
                    artifact_type=artifact_type,
                    created_at=created_at,
                    metadata=metadata,
                )
            else:
                artifact = store.put_bytes(
                    task_id=task_id,
                    name=name,
                    data=data,
                    artifact_type=artifact_type,
                    created_at=created_at,
                    content_type=content_type,
                    metadata=metadata,
                )
            tx.commit()
            return artifact

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        now = beijing_now_iso()
        with from_connection_factory(self.open_connection) as tx:
            repo = TaskQueueRepository(tx.connection)
            task = repo.get(task_id)
            if task is None:
                return None
            changed = repo.request_cancel(task_id=task_id, updated_at=now)
            updated = repo.get(task_id) or task
            tx.commit()
        if changed:
            self.publish_task_queue_event(updated, event="cancelled" if updated.get("status") == "cancelled" else "cancel_requested")
        return {"changed": changed, "task": updated}

    def retry_task(self, task_id: str) -> dict[str, Any] | None:
        now = beijing_now_iso()
        with from_connection_factory(self.open_connection) as tx:
            repo = TaskQueueRepository(tx.connection)
            task = repo.get(task_id)
            if task is None:
                return None
            changed = repo.retry_interrupted(task_id=task_id, updated_at=now)
            updated = repo.get(task_id) or task
            tx.commit()
        if changed:
            self.publish_task_queue_event(updated, event="retry")
        return {"changed": changed, "task": updated}

    def list_task_events(self, task_id: str, *, after_event_id: int = 0) -> list[dict[str, Any]]:
        return self.task_event_log.replay(task_id, after_event_id=after_event_id)

    def publish_task_queue_event(self, task: dict[str, Any], event: str | None = None) -> dict[str, Any]:
        payload = dict(task)
        payload.setdefault("kind", str(task.get("kind") or "task"))
        payload.setdefault("task_id", str(task.get("task_id") or ""))
        return self.task_event_log.publish(payload, event=event)

    def task_artifact_file(self, task_id: str, artifact_id: str) -> tuple[dict[str, Any], Path] | None:
        conn = self.open_connection()
        try:
            repo = TaskArtifactRepository(conn)
            artifact = repo.get(artifact_id)
            if artifact is None or str(artifact.get("task_id") or "") != str(task_id):
                return None
            path = LocalArtifactStore(root=self.task_artifact_root, repo=repo).get_path(artifact_id)
        finally:
            conn.close()
        if not path.is_file():
            raise FileNotFoundError(str(path))
        return artifact, path

    def task_control_health(self) -> dict[str, Any]:
        now = beijing_now_iso()
        artifact_root = self._artifact_root_health()
        try:
            conn = self.open_connection()
            try:
                queue_repo = TaskQueueRepository(conn)
                worker_repo = TaskWorkerRepository(conn)
                queue_status_counts = queue_repo.status_counts()
                stale_running_count = queue_repo.stale_running_count(now=now)
                workers = worker_repo.list_recent(limit=5)
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - health diagnostics should not crash /api/health
            return {
                "status": "error",
                "message": "Task control storage is unavailable.",
                "queue_status_counts": {},
                "stale_running_count": 0,
                "worker_fresh": False,
                "workers": [],
                "artifact_root": artifact_root,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }

        worker_fresh = any(_worker_is_fresh(worker, now=now) for worker in workers)
        if artifact_root["status"] == "error":
            status = "error"
            message = "Task artifact root is not writable."
        elif stale_running_count > 0 or not worker_fresh:
            status = "degraded"
            message = "Task control is available but worker freshness needs attention."
        else:
            status = "ok"
            message = "Task control is healthy."
        return {
            "status": status,
            "message": message,
            "queue_status_counts": queue_status_counts,
            "stale_running_count": stale_running_count,
            "worker_fresh": worker_fresh,
            "workers": workers,
            "artifact_root": artifact_root,
        }

    @property
    def task_artifact_root(self) -> Path:
        paths = getattr(self._store, "paths", None)
        runs_dir = getattr(paths, "runs_dir", None)
        return Path(runs_dir) / "tasks" if runs_dir is not None else Path("runs") / "tasks"

    def _artifact_root_health(self) -> dict[str, Any]:
        root = self.task_artifact_root
        probe = root / ".healthcheck.tmp"
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return {
                "status": "ok",
                "path": str(root),
                "writable": True,
            }
        except Exception as exc:  # noqa: BLE001 - health diagnostics should not crash /api/health
            return {
                "status": "error",
                "path": str(root),
                "writable": False,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }

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


def _worker_is_fresh(worker: dict[str, Any], *, now: str) -> bool:
    heartbeat = str(worker.get("last_heartbeat_at") or "")
    elapsed = _seconds_between(now, heartbeat)
    if elapsed is None:
        return False
    lease_seconds = _positive_int(worker.get("lease_seconds"), default=300)
    return elapsed <= max(lease_seconds * 2, 60)


def _seconds_between(later: str, earlier: str) -> float | None:
    later_dt = _parse_iso(later)
    earlier_dt = _parse_iso(earlier)
    if later_dt is None or earlier_dt is None:
        return None
    try:
        return max(0.0, (later_dt - earlier_dt).total_seconds())
    except TypeError:
        return None


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


__all__ = ["BackgroundTaskServiceProtocol", "TaskService"]
