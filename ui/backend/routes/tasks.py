"""Task queue and task artifact routes for the UI backend.

This module intentionally only defines a route registration helper. The main
FastAPI app owns deciding when to register these routes and which concrete
PostgreSQL-backed repositories or ArtifactStore instance to pass through
``store``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse


class _TaskQueueReader(Protocol):
    def list_recent(self, *, statuses: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        ...

    def get(self, task_id: str) -> dict[str, Any] | None:
        ...


class _ArtifactPathProvider(Protocol):
    def get_path(self, artifact_id: str) -> Path:
        ...


class _ResolvedArtifactPathProvider:
    def __init__(self, path: Path) -> None:
        self._path = path

    def get_path(self, artifact_id: str) -> Path:
        del artifact_id
        return self._path


class _TaskServiceTaskReader:
    def __init__(self, task_service: Any) -> None:
        self._task_service = task_service

    def list_recent(self, *, statuses: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        return self._task_service.list_task_queue_rows(statuses=statuses, limit=limit)

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self._task_service.get_task_queue_row(task_id)


def register_task_routes(api: FastAPI, store: Any) -> None:
    """Register task queue metadata routes.

    Expected low-coupling store attributes:
    - ``task_queue_repo`` or ``task_queue`` with ``list_recent`` and ``get``.
    - ``artifact_store``/``task_artifact_store`` with ``list`` or
      ``task_artifact_repo``/``artifact_repo`` with ``list_for_task``.
    - or a ``task_service`` facade with ``list_task_queue_rows``,
      ``get_task_queue_row``, and ``list_task_artifacts``.
    """

    @api.get("/api/tasks")
    def list_tasks(
        status: list[str] | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        task_repo = _task_queue_reader(store)
        statuses = _filter_statuses(status)
        tasks = task_repo.list_recent(statuses=statuses or None, limit=limit)
        return {
            "kind": "task_list",
            "schema_version": 1,
            "tasks": [_task_payload(task) for task in tasks],
        }

    @api.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, Any]:
        task = _task_or_404(_task_queue_reader(store), task_id)
        return {
            "kind": "task_detail",
            "schema_version": 1,
            "task": _task_payload(task),
        }

    @api.post("/api/tasks/{task_id}/cancel")
    def cancel_task(task_id: str) -> dict[str, Any]:
        result = _task_action_or_503(store, "cancel_task", task_id)
        return _task_action_payload(task_id=task_id, action="cancel", result=result)

    @api.post("/api/tasks/{task_id}/retry")
    def retry_task(task_id: str) -> dict[str, Any]:
        result = _task_action_or_503(store, "retry_task", task_id)
        return _task_action_payload(task_id=task_id, action="retry", result=result)

    @api.get("/api/tasks/{task_id}/events")
    def list_task_events(
        task_id: str,
        after_event_id: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        _task_or_404(_task_queue_reader(store), task_id)
        task_service = _task_service_or_503(store)
        if not callable(getattr(task_service, "list_task_events", None)):
            raise HTTPException(status_code=503, detail="task event replay is not configured")
        events = task_service.list_task_events(task_id, after_event_id=after_event_id)
        return {
            "kind": "task_events",
            "schema_version": 1,
            "task_id": task_id,
            "after_event_id": after_event_id,
            "events": jsonable_encoder(events),
        }

    @api.get("/api/tasks/{task_id}/artifacts")
    def list_task_artifacts(task_id: str) -> dict[str, Any]:
        _task_or_404(_task_queue_reader(store), task_id)
        artifact_lister = _task_artifact_lister(store)
        try:
            artifacts = artifact_lister(task_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "kind": "task_artifact_list",
            "schema_version": 1,
            "task_id": task_id,
            "artifacts": [_artifact_payload(artifact) for artifact in artifacts],
        }

    @api.get("/api/tasks/{task_id}/artifacts/{artifact_id}")
    def download_task_artifact(task_id: str, artifact_id: str) -> FileResponse:
        _task_or_404(_task_queue_reader(store), task_id)
        task_service = _task_service_or_503(store)
        if not callable(getattr(task_service, "task_artifact_file", None)):
            raise HTTPException(status_code=503, detail="task artifact downloads are not configured")
        try:
            resolved = task_service.task_artifact_file(task_id, artifact_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="artifact file not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if resolved is None:
            raise HTTPException(status_code=404, detail="artifact not found")
        artifact, path = resolved
        return task_artifact_file_response(_ResolvedArtifactPathProvider(path), artifact)


def task_artifact_file_response(
    path_provider: _ArtifactPathProvider,
    artifact: dict[str, Any],
) -> FileResponse:
    """Build a download response from a validated artifact path provider.

    Download routes should call a path provider such as
    ``LocalArtifactStore.get_path(artifact_id)``. That method resolves and
    validates the final path against the artifact root; callers should not
    construct filesystem paths from request parameters directly.
    """

    artifact_id = str(artifact.get("artifact_id") or "")
    if not artifact_id:
        raise HTTPException(status_code=404, detail="artifact not found")
    try:
        path = path_provider.get_path(artifact_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="artifact not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return FileResponse(
        path,
        media_type=artifact.get("content_type") or None,
        filename=str(artifact.get("name") or path.name),
    )


def _task_queue_reader(store: Any) -> _TaskQueueReader:
    for attribute in ("task_queue_repo", "task_queue"):
        repo = getattr(store, attribute, None)
        if repo is not None:
            return repo
    task_service = getattr(store, "task_service", None)
    if (
        task_service is not None
        and callable(getattr(task_service, "list_task_queue_rows", None))
        and callable(getattr(task_service, "get_task_queue_row", None))
    ):
        return _TaskServiceTaskReader(task_service)
    raise HTTPException(status_code=503, detail="task queue repository is not configured")


def _task_service_or_503(store: Any) -> Any:
    task_service = getattr(store, "task_service", None)
    if task_service is None:
        raise HTTPException(status_code=503, detail="task service is not configured")
    return task_service


def _task_action_or_503(store: Any, method_name: str, task_id: str) -> dict[str, Any]:
    task_service = _task_service_or_503(store)
    method = getattr(task_service, method_name, None)
    if not callable(method):
        raise HTTPException(status_code=503, detail="task control actions are not configured")
    result = method(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="task not found")
    return result


def _task_artifact_lister(store: Any) -> Callable[[str], list[dict[str, Any]]]:
    for attribute in ("artifact_store", "task_artifact_store"):
        artifact_store = getattr(store, attribute, None)
        if artifact_store is not None and callable(getattr(artifact_store, "list", None)):
            return artifact_store.list
    for attribute in ("task_artifact_repo", "artifact_repo"):
        repo = getattr(store, attribute, None)
        if repo is not None and callable(getattr(repo, "list_for_task", None)):
            return repo.list_for_task
    task_service = getattr(store, "task_service", None)
    if task_service is not None and callable(getattr(task_service, "list_task_artifacts", None)):
        return task_service.list_task_artifacts
    raise HTTPException(status_code=503, detail="task artifact repository is not configured")


def _task_or_404(task_repo: _TaskQueueReader, task_id: str) -> dict[str, Any]:
    try:
        task = task_repo.get(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return task


def _filter_statuses(values: list[str] | None) -> list[str]:
    statuses: list[str] = []
    for value in values or []:
        for item in str(value).split(","):
            item = item.strip()
            if item:
                statuses.append(item)
    return statuses


def _task_payload(task: dict[str, Any]) -> dict[str, Any]:
    payload = dict(task)
    payload.setdefault("payload", {})
    payload.setdefault("result", None)
    payload.setdefault("error", None)
    payload.setdefault("progress", None)
    payload.setdefault("metadata", {})
    payload.setdefault("cancel_requested", False)
    return jsonable_encoder(payload)


def _artifact_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    payload = dict(artifact)
    payload.setdefault("metadata", {})
    return jsonable_encoder(payload)


def _task_action_payload(*, task_id: str, action: str, result: dict[str, Any]) -> dict[str, Any]:
    task = result.get("task")
    if not isinstance(task, dict):
        raise HTTPException(status_code=500, detail="task action returned an invalid task payload")
    return {
        "kind": "task_action",
        "schema_version": 1,
        "action": action,
        "task_id": task_id,
        "changed": bool(result.get("changed")),
        "task": _task_payload(task),
    }
