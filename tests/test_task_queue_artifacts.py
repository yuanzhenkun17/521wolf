from __future__ import annotations

import sqlite3
from typing import Any

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


class _Cursor:
    rowcount = 1

    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def fetchone(self) -> dict[str, Any] | None:
        return self._row

    def fetchall(self) -> list[dict[str, Any]]:
        return [] if self._row is None else [self._row]


class _FakePostgresClaimConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute_for_update(self, sql: str, parameters: Any = ()) -> _Cursor:
        raise AssertionError("claim_next should issue its CTE update through execute()")

    def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
        self.calls.append((sql, tuple(parameters)))
        return _Cursor(
            {
                "task_id": "task_pg",
                "kind": "evolution_run",
                "status": "running",
                "priority": 40,
                "payload": {"run_id": "evolve_pg"},
                "result": None,
                "error": None,
                "progress": None,
                "attempt": 1,
                "max_attempts": 1,
                "lease_owner": "worker-1",
                "lease_expires_at": "2026-06-10T10:05:01+08:00",
                "queued_at": "2026-06-10T10:00:00+08:00",
                "started_at": "2026-06-10T10:00:01+08:00",
                "updated_at": "2026-06-10T10:00:01+08:00",
                "finished_at": None,
                "cancel_requested": False,
                "idempotency_key": None,
                "parent_task_id": None,
                "source": "test",
                "metadata": {"role": "seer"},
            }
        )


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


def test_task_queue_repository_enforces_kind_concurrency_limit() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    for task_id in ("task_a", "task_b"):
        repo.enqueue(
            task_id=task_id,
            kind="evolution_run",
            payload={"run_id": task_id},
            queued_at="2026-06-10T10:00:00+08:00",
        )

    first = repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:01+08:00",
        lease_expires_at="2026-06-10T10:05:01+08:00",
        kind_concurrency_limits={"evolution_run": 1},
    )
    second = repo.claim_next(
        worker_id="worker-2",
        now="2026-06-10T10:00:02+08:00",
        lease_expires_at="2026-06-10T10:05:02+08:00",
        kind_concurrency_limits={"evolution_run": 1},
    )

    assert first is not None
    assert second is None
    assert repo.get("task_b")["status"] == "queued"  # type: ignore[index]


def test_task_queue_repository_ignores_expired_lease_for_kind_limit() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    for task_id in ("task_a", "task_b"):
        repo.enqueue(
            task_id=task_id,
            kind="benchmark_batch",
            payload={"batch_id": task_id},
            queued_at="2026-06-10T10:00:00+08:00",
        )
    assert repo.claim_next(
        worker_id="stale-worker",
        now="2026-06-10T10:00:01+08:00",
        lease_expires_at="2026-06-10T10:01:00+08:00",
    )

    claimed = repo.claim_next(
        worker_id="worker-2",
        now="2026-06-10T10:02:00+08:00",
        lease_expires_at="2026-06-10T10:07:00+08:00",
        kind_concurrency_limits={"benchmark_batch": 1},
    )

    assert claimed is not None
    assert claimed["task_id"] == "task_b"


def test_task_queue_repository_gets_many_tasks_in_one_query() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    for task_id in ("task_a", "task_b", "task_c"):
        repo.enqueue(
            task_id=task_id,
            kind="benchmark_batch",
            payload={"task_id": task_id},
            queued_at="2026-06-10T10:00:00+08:00",
        )

    tasks = repo.get_many(["task_c", "task_a", "task_a", "missing"])

    assert set(tasks) == {"task_a", "task_c"}
    assert tasks["task_a"]["payload"] == {"task_id": "task_a"}
    assert tasks["task_c"]["payload"] == {"task_id": "task_c"}


def test_task_queue_repository_postgres_claim_uses_skip_locked_cte() -> None:
    conn = _FakePostgresClaimConnection()
    repo = TaskQueueRepository(conn)  # type: ignore[arg-type]

    claimed = repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:01+08:00",
        lease_expires_at="2026-06-10T10:05:01+08:00",
        kinds=["evolution_run", "benchmark_batch"],
    )

    assert claimed is not None
    assert claimed["task_id"] == "task_pg"
    assert claimed["payload"] == {"run_id": "evolve_pg"}
    assert len(conn.calls) == 1
    sql, parameters = conn.calls[0]
    assert "WITH candidate AS (" in sql
    assert "FOR UPDATE SKIP LOCKED LIMIT 1" in sql
    assert "UPDATE ui_task_queue AS q SET" in sql
    assert "AND kind IN (?, ?) " in sql
    assert "RETURNING q.task_id" in sql
    assert parameters == (
        False,
        "evolution_run",
        "benchmark_batch",
        "worker-1",
        "2026-06-10T10:05:01+08:00",
        "2026-06-10T10:00:01+08:00",
        "2026-06-10T10:00:01+08:00",
        False,
    )


def test_task_queue_repository_postgres_kind_limit_uses_advisory_lock() -> None:
    conn = _FakePostgresClaimConnection()
    repo = TaskQueueRepository(conn)  # type: ignore[arg-type]

    claimed = repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:01+08:00",
        lease_expires_at="2026-06-10T10:05:01+08:00",
        kinds=["evolution_run"],
        kind_concurrency_limits={"evolution_run": 1},
    )

    assert claimed is not None
    sql, parameters = conn.calls[0]
    assert "pg_try_advisory_xact_lock" in sql
    assert "active_task.lease_expires_at > ?" in sql
    assert parameters[:2] == (False, "evolution_run")
    assert parameters[2:7] == (
        "evolution_run",
        "evolution_run",
        "evolution_run",
        "2026-06-10T10:00:01+08:00",
        1,
    )


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
    assert repo.fresh_running_count(now="2026-06-10T10:00:30+08:00") == 1
    assert repo.stale_running_count(now="2026-06-10T10:00:30+08:00") == 0
    assert repo.fresh_running_count(now="2026-06-10T10:02:00+08:00") == 0
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
    assert artifact["relative_path"].startswith("task_a/")
    assert artifact["relative_path"].endswith("/reports/result.json")
    assert artifact["content_type"] == "application/json"
    assert artifact["size_bytes"] > 0
    assert artifact["metadata"] == {"format": "json"}
    assert store.list("task_a") == [artifact]
    assert b'"status": "ok"' in store.read_bytes(artifact["artifact_id"])


def test_task_queue_repository_complete_requires_running_owner() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    repo.enqueue(
        task_id="task_a",
        kind="evolution_run",
        payload={},
        queued_at="2026-06-10T10:00:00+08:00",
    )
    assert repo.claim_next(
        worker_id="worker-1",
        now="2026-06-10T10:00:01+08:00",
        lease_expires_at="2026-06-10T10:01:00+08:00",
    )

    assert repo.complete(
        task_id="task_a",
        status="succeeded",
        finished_at="2026-06-10T10:00:02+08:00",
        result={"ok": True},
        worker_id="worker-2",
    ) is False
    assert repo.get("task_a")["status"] == "running"  # type: ignore[index]

    assert repo.mark_expired_running_interrupted(now="2026-06-10T10:02:00+08:00") == 1
    assert repo.complete(
        task_id="task_a",
        status="succeeded",
        finished_at="2026-06-10T10:03:00+08:00",
        result={"late": True},
        worker_id="worker-1",
    ) is False
    task = repo.get("task_a")
    assert task is not None
    assert task["status"] == "interrupted"
    assert task["result"] is None


def test_local_artifact_store_rewrite_keeps_old_metadata_readable(tmp_path) -> None:
    conn = _connect()
    repo = TaskArtifactRepository(conn)
    store = LocalArtifactStore(root=tmp_path / "runs" / "tasks", repo=repo)

    first = store.put_json(
        task_id="task_a",
        name="result.json",
        payload={"version": 1},
        artifact_type="result",
        created_at="2026-06-10T10:00:00+08:00",
    )
    second = store.put_json(
        task_id="task_a",
        name="result.json",
        payload={"version": 2},
        artifact_type="result",
        created_at="2026-06-10T10:01:00+08:00",
    )

    assert first["artifact_id"] != second["artifact_id"]
    assert first["relative_path"] != second["relative_path"]
    assert b'"version": 1' in store.read_bytes(first["artifact_id"])
    assert b'"version": 2' in store.read_bytes(second["artifact_id"])


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
