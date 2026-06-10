from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from storage.ui import TaskQueueRepository, TaskWorkerRepository
from ui.backend.services.task_worker import (
    TaskExecutorRegistry,
    TaskWorker,
    TaskWorkerLoop,
)


def _connect(path: Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path) if path is not None else ":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS ui_task_queue (
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
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ui_task_queue_idempotency
        ON ui_task_queue(idempotency_key)
        WHERE idempotency_key IS NOT NULL;
        CREATE TABLE IF NOT EXISTS ui_task_workers (
            worker_id text PRIMARY KEY,
            status text NOT NULL,
            last_heartbeat_at text NOT NULL,
            lease_seconds integer NOT NULL,
            current_task_id text,
            metadata text
        );
        """
    )
    return conn


class _TickingClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 6, 10, 10, 0, tzinfo=timezone(timedelta(hours=8)))

    def __call__(self) -> datetime:
        value = self._current
        self._current = value + timedelta(seconds=1)
        return value


def _enqueue(repo: TaskQueueRepository, *, task_id: str = "task_a", kind: str = "demo") -> None:
    repo.enqueue(
        task_id=task_id,
        kind=kind,
        payload={"value": 42},
        queued_at="2026-06-10T10:00:00+08:00",
    )


def test_task_worker_claims_executes_and_marks_succeeded() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    _enqueue(repo)
    registry = TaskExecutorRegistry()
    calls: list[dict[str, Any]] = []

    @registry.register("demo")
    def _execute(task: dict[str, Any], context) -> dict[str, Any]:
        calls.append(task)
        assert context.cancel_requested() is False
        assert context.heartbeat(progress={"stage": "executing", "percent": 0.5})
        return {"echo": context.payload["value"]}

    worker = TaskWorker(
        repository=repo,
        executors=registry,
        worker_id="worker-1",
        clock=_TickingClock(),
        lease_seconds=300,
    )

    result = worker.run_once()

    assert result.status == "succeeded"
    assert result.executed is True
    assert [call["task_id"] for call in calls] == ["task_a"]
    task = repo.get("task_a")
    assert task is not None
    assert task["status"] == "succeeded"
    assert task["attempt"] == 1
    assert task["lease_owner"] is None
    assert task["lease_expires_at"] is None
    assert task["result"] == {"echo": 42}
    assert task["error"] is None
    assert task["progress"] == {"stage": "executing", "percent": 0.5}


def test_task_worker_marks_executor_exception_failed() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    _enqueue(repo)

    def _execute(_task: dict[str, Any], _context) -> dict[str, Any]:
        raise RuntimeError("boom")

    worker = TaskWorker(
        repository=repo,
        executors={"demo": _execute},
        worker_id="worker-1",
        clock=_TickingClock(),
    )

    result = worker.run_once()

    assert result.status == "failed"
    assert result.executed is True
    task = repo.get("task_a")
    assert task is not None
    assert task["status"] == "failed"
    assert task["result"] is None
    assert task["error"] == {
        "kind": "executor_error",
        "exception_type": "RuntimeError",
        "message": "boom",
    }
    assert task["lease_owner"] is None


def test_task_worker_skips_pre_cancelled_queued_task() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    _enqueue(repo)
    assert repo.request_cancel(task_id="task_a", updated_at="2026-06-10T10:00:01+08:00")
    calls: list[str] = []

    def _execute(task: dict[str, Any], _context) -> dict[str, Any]:
        calls.append(task["task_id"])
        return {"ok": True}

    worker = TaskWorker(
        repository=repo,
        executors={"demo": _execute},
        worker_id="worker-1",
        clock=_TickingClock(),
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert calls == []
    task = repo.get("task_a")
    assert task is not None
    assert task["status"] == "cancelled"
    assert task["cancel_requested"] == 1
    assert task["error"] == {
        "kind": "cancelled",
        "message": "task cancellation requested",
    }


def test_task_worker_marks_cooperative_cancel_requested_cancelled() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    _enqueue(repo)

    def _execute(task: dict[str, Any], context) -> dict[str, Any]:
        assert repo.request_cancel(task_id=task["task_id"], updated_at="2026-06-10T10:00:05+08:00")
        context.raise_if_cancel_requested()
        return {"should": "not complete"}

    worker = TaskWorker(
        repository=repo,
        executors={"demo": _execute},
        worker_id="worker-1",
        clock=_TickingClock(),
    )

    result = worker.run_once()

    assert result.status == "cancelled"
    assert result.executed is True
    task = repo.get("task_a")
    assert task is not None
    assert task["status"] == "cancelled"
    assert task["result"] is None
    assert task["error"] == {
        "kind": "cancelled",
        "message": "task cancellation requested",
    }
    assert task["cancel_requested"] == 1


def test_task_worker_loop_records_heartbeat_and_runs_available_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "task_worker.sqlite3"
    conn = _connect(db_path)
    repo = TaskQueueRepository(conn)
    _enqueue(repo)
    conn.commit()
    conn.close()

    def _factory() -> sqlite3.Connection:
        return _connect(db_path)

    published: list[tuple[str, str]] = []
    loop = TaskWorkerLoop(
        connection_factory=_factory,
        executors={"demo": lambda _task, context: {"echo": context.payload["value"]}},
        worker_id="worker-loop",
        clock=_TickingClock(),
        poll_interval_seconds=0,
        event_publisher=lambda task, event: published.append((task["task_id"], str(event))),
    )

    result = loop.run_once()

    assert result.status == "succeeded"
    verify_conn = _connect(db_path)
    try:
        task = TaskQueueRepository(verify_conn).get("task_a")
        worker = TaskWorkerRepository(verify_conn).get("worker-loop")
    finally:
        verify_conn.close()
    assert task is not None
    assert task["status"] == "succeeded"
    assert task["result"] == {"echo": 42}
    assert worker is not None
    assert worker["status"] == "succeeded"
    assert worker["lease_seconds"] == 300
    assert worker["metadata"]["registered_kinds"] == ["demo"]
    assert published == [("task_a", "succeeded")]


def test_task_worker_loop_marks_expired_running_tasks_interrupted(tmp_path: Path) -> None:
    db_path = tmp_path / "task_worker.sqlite3"
    conn = _connect(db_path)
    repo = TaskQueueRepository(conn)
    _enqueue(repo)
    assert repo.claim_next(
        worker_id="stale-worker",
        now="2026-06-10T09:00:00+08:00",
        lease_expires_at="2026-06-10T09:01:00+08:00",
    )
    conn.commit()
    conn.close()

    def _factory() -> sqlite3.Connection:
        return _connect(db_path)

    loop = TaskWorkerLoop(
        connection_factory=_factory,
        executors={"demo": lambda _task, _context: {"ok": True}},
        worker_id="worker-loop",
        clock=_TickingClock(),
        poll_interval_seconds=0,
    )

    count = loop.mark_expired_running_interrupted()

    assert count == 1
    verify_conn = _connect(db_path)
    try:
        task = TaskQueueRepository(verify_conn).get("task_a")
        worker = TaskWorkerRepository(verify_conn).get("worker-loop")
    finally:
        verify_conn.close()
    assert task is not None
    assert task["status"] == "interrupted"
    assert worker is not None
    assert worker["status"] == "maintenance"
    assert worker["metadata"] == {"interrupted_count": 1}
