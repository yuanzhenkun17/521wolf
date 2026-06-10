from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path
from typing import Any

from app.tools.manage_ui_tasks import run_with_service, verify_artifacts
from storage.artifacts import LocalArtifactStore
from storage.ui import TaskArtifactRepository


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ui_task_artifacts (
            artifact_id text PRIMARY KEY,
            task_id text NOT NULL,
            artifact_type text NOT NULL,
            name text NOT NULL,
            relative_path text NOT NULL,
            content_type text,
            size_bytes integer,
            sha256 text,
            created_at text NOT NULL,
            metadata text
        );
        """
    )
    return conn


class FakeTaskService:
    def __init__(self, db_path: Path, artifact_root: Path) -> None:
        self.db_path = db_path
        self.task_artifact_root = artifact_root
        self.list_statuses: list[str] | None = None

    def open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_task_queue_rows(self, *, statuses=None, limit: int = 100) -> list[dict[str, Any]]:
        self.list_statuses = list(statuses or [])
        return [
            {
                "task_id": "task-a",
                "kind": "benchmark_batch",
                "status": "queued",
                "priority": 100,
                "attempt": 0,
                "max_attempts": 1,
                "queued_at": "2026-06-10T10:00:00+08:00",
                "updated_at": "2026-06-10T10:00:00+08:00",
            }
        ][:limit]

    def cancel_task(self, task_id: str) -> dict[str, Any] | None:
        if task_id == "missing":
            return None
        return {"changed": True, "task": {"task_id": task_id, "kind": "benchmark_batch", "status": "cancelled"}}

    def retry_task(self, task_id: str) -> dict[str, Any] | None:
        return {"changed": task_id == "interrupted", "task": {"task_id": task_id, "kind": "benchmark_batch", "status": "queued"}}

    def list_task_artifacts(self, task_id: str) -> list[dict[str, Any]]:
        conn = self.open_connection()
        try:
            return TaskArtifactRepository(conn).list_for_task(task_id)
        finally:
            conn.close()


def _write_artifact(service: FakeTaskService, *, task_id: str = "task-a") -> dict[str, Any]:
    conn = _connect(service.db_path)
    try:
        artifact = LocalArtifactStore(root=service.task_artifact_root, repo=TaskArtifactRepository(conn)).put_json(
            task_id=task_id,
            name="result.json",
            payload={"ok": True},
            artifact_type="result",
            created_at="2026-06-10T10:00:00+08:00",
        )
        conn.commit()
        return artifact
    finally:
        conn.close()


def test_manage_ui_tasks_lists_and_operates_tasks(tmp_path: Path) -> None:
    service = FakeTaskService(tmp_path / "tasks.sqlite", tmp_path / "runs" / "tasks")
    _connect(service.db_path).close()

    listed = run_with_service(argparse.Namespace(command="list", status=["queued,running"], limit=10), service)
    cancelled = run_with_service(argparse.Namespace(command="cancel", task_id="task-a"), service)
    retry = run_with_service(argparse.Namespace(command="retry", task_id="interrupted"), service)
    missing = run_with_service(argparse.Namespace(command="cancel", task_id="missing"), service)

    assert listed["ok"] is True
    assert service.list_statuses == ["queued", "running"]
    assert listed["tasks"][0]["task_id"] == "task-a"
    assert cancelled["changed"] is True
    assert cancelled["task"]["status"] == "cancelled"
    assert retry["changed"] is True
    assert missing["ok"] is False
    assert missing["exit_code"] == 1


def test_manage_ui_tasks_verifies_artifact_hashes(tmp_path: Path) -> None:
    service = FakeTaskService(tmp_path / "tasks.sqlite", tmp_path / "runs" / "tasks")
    artifact = _write_artifact(service)

    ok_report = verify_artifacts(service, task_id="task-a")

    assert ok_report["ok"] is True
    assert ok_report["checked"] == 1
    assert ok_report["artifacts"][0]["artifact_id"] == artifact["artifact_id"]
    assert ok_report["artifacts"][0]["status"] == "ok"

    artifact_path = service.task_artifact_root / artifact["relative_path"]
    artifact_path.write_text("tampered", encoding="utf-8")
    failed_report = verify_artifacts(service, task_id="task-a")

    assert failed_report["ok"] is False
    assert failed_report["failed"] == 1
    assert failed_report["exit_code"] == 2
    assert "sha256_mismatch" in failed_report["artifacts"][0]["status"]
