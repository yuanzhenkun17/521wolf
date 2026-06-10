from __future__ import annotations

import sqlite3

import pytest

from storage.artifacts import LocalArtifactStore
from storage.ui import TaskArtifactRepository, TaskQueueRepository


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE ui_task_queue (
            task_id text PRIMARY KEY,
            kind text NOT NULL,
            status text NOT NULL,
            priority integer NOT NULL DEFAULT 100,
            payload text NOT NULL,
            result text,
            error text,
            progress text,
            attempt integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL DEFAULT 1,
            lease_owner text,
            lease_expires_at text,
            queued_at text NOT NULL,
            started_at text,
            updated_at text NOT NULL,
            finished_at text,
            cancel_requested boolean NOT NULL DEFAULT 0,
            idempotency_key text,
            parent_task_id text,
            source text,
            metadata text
        );
        CREATE UNIQUE INDEX idx_ui_task_queue_idempotency
        ON ui_task_queue(idempotency_key)
        WHERE idempotency_key IS NOT NULL;
        CREATE TABLE ui_task_artifacts (
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


def test_task_queue_repository_claims_and_completes_task() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)

    repo.enqueue(
        task_id="task_a",
        kind="evolution_run",
        payload={"run_id": "evolve_a"},
        priority=50,
        queued_at="2026-06-10T10:00:00+08:00",
        metadata={"role": "seer"},
    )

    claimed = repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:01+08:00",
        lease_expires_at="2026-06-10T10:05:01+08:00",
    )

    assert claimed is not None
    assert claimed["task_id"] == "task_a"
    assert claimed["status"] == "running"
    assert claimed["attempt"] == 1
    assert claimed["payload"] == {"run_id": "evolve_a"}
    assert claimed["metadata"] == {"role": "seer"}
    assert repo.heartbeat(
        task_id="task_a",
        worker_id="worker-1",
        lease_expires_at="2026-06-10T10:06:00+08:00",
        updated_at="2026-06-10T10:01:00+08:00",
        progress={"stage": "training", "percent": 0.2},
    )

    assert repo.complete(
        task_id="task_a",
        status="succeeded",
        finished_at="2026-06-10T10:02:00+08:00",
        result={"ok": True},
    )
    completed = repo.get("task_a")
    assert completed is not None
    assert completed["status"] == "succeeded"
    assert completed["result"] == {"ok": True}
    assert completed["progress"] == {"stage": "training", "percent": 0.2}


def test_task_queue_repository_marks_expired_running_tasks_interrupted() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    repo.enqueue(
        task_id="task_a",
        kind="benchmark_batch",
        payload={},
        queued_at="2026-06-10T10:00:00+08:00",
    )
    assert repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:01+08:00",
        lease_expires_at="2026-06-10T10:01:00+08:00",
    )

    assert repo.mark_expired_running_interrupted(now="2026-06-10T10:02:00+08:00") == 1
    interrupted = repo.get("task_a")
    assert interrupted is not None
    assert interrupted["status"] == "interrupted"
    assert repo.retry_interrupted(task_id="task_a", updated_at="2026-06-10T10:03:00+08:00")
    assert repo.get("task_a")["status"] == "queued"  # type: ignore[index]


def test_task_queue_repository_reports_status_counts_and_stale_running() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    repo.enqueue(
        task_id="task_a",
        kind="benchmark_batch",
        payload={},
        queued_at="2026-06-10T10:00:00+08:00",
    )
    repo.enqueue(
        task_id="task_b",
        kind="benchmark_batch",
        payload={},
        queued_at="2026-06-10T10:00:01+08:00",
    )
    assert repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:02+08:00",
        lease_expires_at="2026-06-10T10:01:00+08:00",
    )

    assert repo.status_counts() == {"queued": 1, "running": 1}
    assert repo.stale_running_count(now="2026-06-10T10:00:30+08:00") == 0
    assert repo.stale_running_count(now="2026-06-10T10:02:00+08:00") == 1


def test_task_queue_repository_cancels_queued_tasks_without_worker_claim() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    repo.enqueue(
        task_id="task_cancel",
        kind="benchmark_batch",
        payload={},
        queued_at="2026-06-10T10:00:00+08:00",
    )

    assert repo.request_cancel(task_id="task_cancel", updated_at="2026-06-10T10:00:01+08:00")

    task = repo.get("task_cancel")
    assert task is not None
    assert task["status"] == "cancelled"
    assert task["finished_at"] == "2026-06-10T10:00:01+08:00"
    assert task["cancel_requested"] == 1
    assert task["error"] == {
        "kind": "cancelled",
        "message": "task cancellation requested",
    }
    assert repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:02+08:00",
        lease_expires_at="2026-06-10T10:05:02+08:00",
    ) is None


def test_task_queue_repository_cancels_interrupted_tasks_without_retry_loop() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    repo.enqueue(
        task_id="task_interrupted",
        kind="benchmark_batch",
        payload={},
        queued_at="2026-06-10T10:00:00+08:00",
    )
    assert repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:01+08:00",
        lease_expires_at="2026-06-10T10:01:00+08:00",
    )
    assert repo.mark_expired_running_interrupted(now="2026-06-10T10:02:00+08:00") == 1

    assert repo.request_cancel(task_id="task_interrupted", updated_at="2026-06-10T10:03:00+08:00")

    task = repo.get("task_interrupted")
    assert task is not None
    assert task["status"] == "cancelled"
    assert task["finished_at"] == "2026-06-10T10:03:00+08:00"
    assert task["cancel_requested"] == 1
    assert task["error"]["kind"] == "cancelled"
    assert repo.retry_interrupted(task_id="task_interrupted", updated_at="2026-06-10T10:04:00+08:00") is False


def test_local_artifact_store_writes_indexes_and_reads_json(tmp_path) -> None:
    conn = _connect()
    repo = TaskArtifactRepository(conn)
    store = LocalArtifactStore(root=tmp_path / "runs" / "tasks", repo=repo)

    artifact = store.put_json(
        task_id="task_a",
        name="reports/result.json",
        payload={"status": "ok"},
        artifact_type="result",
        created_at="2026-06-10T10:00:00+08:00",
        metadata={"format": "json"},
    )

    assert artifact["task_id"] == "task_a"
    assert artifact["name"] == "reports/result.json"
    assert artifact["relative_path"] == "task_a/reports/result.json"
    assert artifact["content_type"] == "application/json"
    assert artifact["size_bytes"] > 0
    assert artifact["metadata"] == {"format": "json"}
    assert store.list("task_a") == [artifact]
    assert b'"status": "ok"' in store.read_bytes(artifact["artifact_id"])


@pytest.mark.parametrize(
    ("task_id", "name"),
    [
        ("../task", "result.json"),
        ("task_a", "../result.json"),
        ("task_a", "/tmp/result.json"),
        ("task_a", "safe/../../result.json"),
    ],
)
def test_local_artifact_store_rejects_unsafe_paths(tmp_path, task_id: str, name: str) -> None:
    conn = _connect()
    store = LocalArtifactStore(
        root=tmp_path / "runs" / "tasks",
        repo=TaskArtifactRepository(conn),
    )

    with pytest.raises(ValueError):
        store.put_bytes(
            task_id=task_id,
            name=name,
            data=b"nope",
            artifact_type="diagnostic",
            created_at="2026-06-10T10:00:00+08:00",
        )
