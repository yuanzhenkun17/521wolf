from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ui.backend.routes.tasks import register_task_routes


class _FakeTaskQueueRepo:
    def __init__(self) -> None:
        self.list_recent_calls: list[dict[str, Any]] = []
        self.tasks = {
            "task_1": {
                "task_id": "task_1",
                "kind": "report_task",
                "status": "running",
                "priority": 20,
                "payload": {"run_id": "run_1"},
                "result": None,
                "error": None,
                "progress": {"step": 2, "total": 5},
                "attempt": 1,
                "max_attempts": 2,
                "queued_at": "2026-06-10T12:00:00+08:00",
                "started_at": "2026-06-10T12:01:00+08:00",
                "updated_at": "2026-06-10T12:02:00+08:00",
                "finished_at": None,
                "cancel_requested": False,
                "idempotency_key": "idem_1",
                "parent_task_id": None,
                "source": "ui",
                "metadata": {"owner": "tests"},
            },
            "task_2": {
                "task_id": "task_2",
                "kind": "artifact_export",
                "status": "queued",
                "priority": 50,
                "payload": {},
                "queued_at": "2026-06-10T12:03:00+08:00",
                "updated_at": "2026-06-10T12:03:00+08:00",
            },
        }

    def list_recent(self, *, statuses: list[str] | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.list_recent_calls.append({"statuses": statuses, "limit": limit})
        values = list(self.tasks.values())
        if statuses:
            values = [task for task in values if task["status"] in statuses]
        return values[:limit]

    def get(self, task_id: str) -> dict[str, Any] | None:
        return self.tasks.get(task_id)


class _FakeArtifactStore:
    def __init__(self) -> None:
        self.list_calls: list[str] = []
        self.artifacts = {
            "task_1": [
                {
                    "artifact_id": "artifact_1",
                    "task_id": "task_1",
                    "artifact_type": "report",
                    "name": "summary.json",
                    "relative_path": "task_1/summary.json",
                    "content_type": "application/json",
                    "size_bytes": 128,
                    "sha256": "abc123",
                    "created_at": "2026-06-10T12:04:00+08:00",
                    "metadata": {"section": "summary"},
                }
            ]
        }

    def list(self, task_id: str) -> list[dict[str, Any]]:
        self.list_calls.append(task_id)
        return self.artifacts.get(task_id, [])


class _FakeStore:
    def __init__(self) -> None:
        self.task_queue_repo = _FakeTaskQueueRepo()
        self.artifact_store = _FakeArtifactStore()


class _FakeTaskService:
    def __init__(self, *, artifact_path: Path | None = None) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.artifact_path = artifact_path
        self.tasks = {
            "task_1": {
                "task_id": "task_1",
                "kind": "service_task",
                "status": "succeeded",
                "priority": 30,
                "payload": {"source": "service"},
                "queued_at": "2026-06-10T12:00:00+08:00",
                "updated_at": "2026-06-10T12:01:00+08:00",
            }
        }
        self.events = [
            {
                "id": 7,
                "event": "progress",
                "entity_id": "task_1",
                "status": "running",
                "payload": {"task_id": "task_1", "status": "running"},
            }
        ]

    def list_task_queue_rows(
        self,
        *,
        statuses: list[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        self.calls.append(("list_task_queue_rows", statuses, limit))
        values = list(self.tasks.values())
        if statuses:
            values = [task for task in values if task["status"] in statuses]
        return values[:limit]

    def get_task_queue_row(self, task_id: str) -> dict[str, Any] | None:
        self.calls.append(("get_task_queue_row", task_id))
        return self.tasks.get(task_id)

    def list_task_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        self.calls.append(("list_task_artifacts", task_id))
        if task_id != "task_1":
            return []
        return [
            {
                "artifact_id": "artifact_service_1",
                "task_id": task_id,
                "artifact_type": "result",
                "name": "result.json",
                "relative_path": f"{task_id}/result.json",
                "content_type": "application/json",
                "size_bytes": 64,
                "sha256": "def456",
                "created_at": "2026-06-10T12:02:00+08:00",
            }
        ]

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        self.calls.append(("cancel_task", task_id))
        task = self.tasks.get(task_id)
        if task is None:
            return None
        task = dict(task)
        task["cancel_requested"] = True
        task["status"] = "cancelled"
        self.tasks[task_id] = task
        return {"changed": True, "task": task}

    def retry_task(self, task_id: str) -> dict[str, Any] | None:
        self.calls.append(("retry_task", task_id))
        task = self.tasks.get(task_id)
        if task is None:
            return None
        task = dict(task)
        changed = task.get("status") == "interrupted"
        if changed:
            task["status"] = "queued"
            self.tasks[task_id] = task
        return {"changed": changed, "task": task}

    def list_task_events(self, task_id: str, *, after_event_id: int = 0) -> list[dict[str, Any]]:
        self.calls.append(("list_task_events", task_id, after_event_id))
        return [
            event
            for event in self.events
            if event["entity_id"] == task_id and int(event["id"]) > after_event_id
        ]

    def task_artifact_file(self, task_id: str, artifact_id: str) -> tuple[dict[str, Any], Path] | None:
        self.calls.append(("task_artifact_file", task_id, artifact_id))
        artifacts = self.list_task_artifacts(task_id)
        artifact = next((item for item in artifacts if item["artifact_id"] == artifact_id), None)
        if artifact is None or self.artifact_path is None:
            return None
        return artifact, self.artifact_path


class _TaskServiceOnlyStore:
    def __init__(self, *, artifact_path: Path | None = None) -> None:
        self.task_service = _FakeTaskService(artifact_path=artifact_path)


def _client() -> tuple[TestClient, _FakeStore]:
    store = _FakeStore()
    api = FastAPI()
    register_task_routes(api, store)
    return TestClient(api), store


def test_list_tasks_returns_stable_shape_and_passes_filters() -> None:
    client, store = _client()

    response = client.get("/api/tasks?status=queued,running&limit=1")

    assert response.status_code == 200
    assert response.json() == {
        "kind": "task_list",
        "schema_version": 1,
        "tasks": [
            {
                "task_id": "task_1",
                "kind": "report_task",
                "status": "running",
                "priority": 20,
                "payload": {"run_id": "run_1"},
                "result": None,
                "error": None,
                "progress": {"step": 2, "total": 5},
                "attempt": 1,
                "max_attempts": 2,
                "queued_at": "2026-06-10T12:00:00+08:00",
                "started_at": "2026-06-10T12:01:00+08:00",
                "updated_at": "2026-06-10T12:02:00+08:00",
                "finished_at": None,
                "cancel_requested": False,
                "idempotency_key": "idem_1",
                "parent_task_id": None,
                "source": "ui",
                "metadata": {"owner": "tests"},
            }
        ],
    }
    assert store.task_queue_repo.list_recent_calls == [
        {"statuses": ["queued", "running"], "limit": 1}
    ]


def test_get_task_returns_detail_shape() -> None:
    client, _store = _client()

    response = client.get("/api/tasks/task_2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "task_detail"
    assert payload["schema_version"] == 1
    assert payload["task"]["task_id"] == "task_2"
    assert payload["task"]["status"] == "queued"
    assert payload["task"]["result"] is None
    assert payload["task"]["metadata"] == {}
    assert payload["task"]["cancel_requested"] is False


def test_get_task_returns_404_for_missing_task() -> None:
    client, _store = _client()

    response = client.get("/api/tasks/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == "task not found"


def test_list_task_artifacts_returns_metadata_shape() -> None:
    client, store = _client()

    response = client.get("/api/tasks/task_1/artifacts")

    assert response.status_code == 200
    assert response.json() == {
        "kind": "task_artifact_list",
        "schema_version": 1,
        "task_id": "task_1",
        "artifacts": [
            {
                "artifact_id": "artifact_1",
                "task_id": "task_1",
                "artifact_type": "report",
                "name": "summary.json",
                "relative_path": "task_1/summary.json",
                "content_type": "application/json",
                "size_bytes": 128,
                "sha256": "abc123",
                "created_at": "2026-06-10T12:04:00+08:00",
                "metadata": {"section": "summary"},
            }
        ],
    }
    assert store.artifact_store.list_calls == ["task_1"]


def test_list_task_artifacts_checks_task_exists_before_listing() -> None:
    client, store = _client()

    response = client.get("/api/tasks/missing/artifacts")

    assert response.status_code == 404
    assert response.json()["detail"] == "task not found"
    assert store.artifact_store.list_calls == []


def test_task_routes_can_read_through_task_service_facade() -> None:
    store = _TaskServiceOnlyStore()
    api = FastAPI()
    register_task_routes(api, store)
    client = TestClient(api)

    list_response = client.get("/api/tasks?status=succeeded&limit=5")
    detail_response = client.get("/api/tasks/task_1")
    artifact_response = client.get("/api/tasks/task_1/artifacts")

    assert list_response.status_code == 200
    assert list_response.json()["tasks"][0]["payload"] == {"source": "service"}
    assert detail_response.status_code == 200
    assert detail_response.json()["task"]["kind"] == "service_task"
    assert artifact_response.status_code == 200
    assert artifact_response.json()["artifacts"][0]["artifact_id"] == "artifact_service_1"
    assert store.task_service.calls == [
        ("list_task_queue_rows", ["succeeded"], 5),
        ("get_task_queue_row", "task_1"),
        ("get_task_queue_row", "task_1"),
        ("list_task_artifacts", "task_1"),
    ]


def test_task_routes_cancel_retry_and_events_through_task_service() -> None:
    store = _TaskServiceOnlyStore()
    api = FastAPI()
    register_task_routes(api, store)
    client = TestClient(api)

    cancel_response = client.post("/api/tasks/task_1/cancel")
    events_response = client.get("/api/tasks/task_1/events?after_event_id=6")
    retry_response = client.post("/api/tasks/task_1/retry")

    assert cancel_response.status_code == 200
    assert cancel_response.json()["action"] == "cancel"
    assert cancel_response.json()["changed"] is True
    assert cancel_response.json()["task"]["status"] == "cancelled"
    assert events_response.status_code == 200
    assert events_response.json()["events"][0]["id"] == 7
    assert retry_response.status_code == 200
    assert retry_response.json()["action"] == "retry"
    assert retry_response.json()["changed"] is False
    assert store.task_service.calls == [
        ("cancel_task", "task_1"),
        ("get_task_queue_row", "task_1"),
        ("list_task_events", "task_1", 6),
        ("retry_task", "task_1"),
    ]


def test_task_artifact_download_returns_file_response(tmp_path: Path) -> None:
    artifact_path = tmp_path / "result.json"
    artifact_path.write_text('{"ok": true}', encoding="utf-8")
    store = _TaskServiceOnlyStore(artifact_path=artifact_path)
    api = FastAPI()
    register_task_routes(api, store)
    client = TestClient(api)

    response = client.get("/api/tasks/task_1/artifacts/artifact_service_1")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.headers["content-disposition"].endswith('filename="result.json"')
    assert response.content == b'{"ok": true}'
