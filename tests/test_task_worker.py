from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from storage.ui import TaskQueueRepository, TaskWorkerRepository
from ui.backend.services.task_persistence_service import TaskPersistenceService
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
        CREATE TABLE IF NOT EXISTS ui_background_tasks (
            entity_id text PRIMARY KEY,
            entity_kind text,
            status text,
            payload text NOT NULL,
            updated_at text NOT NULL
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


def test_task_context_heartbeat_refreshes_worker_record() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    worker_repo = TaskWorkerRepository(conn)
    _enqueue(repo)
    clock = _TickingClock()

    def _execute(_task: dict[str, Any], context) -> dict[str, Any]:
        assert context.heartbeat(progress={"stage": "executing"})
        worker = worker_repo.get("worker-live")
        assert worker is not None
        assert worker["status"] == "running"
        assert worker["current_task_id"] == "task_a"
        return {"ok": True}

    worker = TaskWorker(
        repository=repo,
        executors={"demo": _execute},
        worker_id="worker-live",
        clock=clock,
        after_repository_update=conn.commit,
        worker_heartbeat=lambda task_id: worker_repo.upsert_heartbeat(
            worker_id="worker-live",
            status="running",
            last_heartbeat_at=clock().isoformat(),
            lease_seconds=300,
            current_task_id=task_id,
        ),
    )

    result = worker.run_once()

    assert result.status == "succeeded"


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
    assert published == [("task_a", "progress"), ("task_a", "succeeded")]


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


def test_task_worker_respects_explicit_kind_concurrency_limit() -> None:
    conn = _connect()
    repo = TaskQueueRepository(conn)
    _enqueue(repo, task_id="task_a", kind="evolution_run")
    _enqueue(repo, task_id="task_b", kind="evolution_run")
    assert repo.claim_next(
        worker_id="other-worker",
        now="2026-06-10T10:00:00+08:00",
        lease_expires_at="2026-06-10T10:05:00+08:00",
    )
    calls: list[str] = []
    worker = TaskWorker(
        repository=repo,
        executors={"evolution_run": lambda task, _context: calls.append(task["task_id"]) or {}},
        worker_id="worker-2",
        clock=_TickingClock(),
        kind_concurrency_limits={"evolution_run": 1},
    )

    result = worker.run_once()

    assert result.status == "idle"
    assert calls == []


def test_task_worker_loop_reads_kind_limits_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "UI_TASK_KIND_CONCURRENCY_LIMITS",
        '{"benchmark_batch":2,"evolution_run":3,"invalid":0}',
    )

    loop = TaskWorkerLoop(
        connection_factory=_connect,
        executors={},
        worker_id="worker-config",
    )

    assert loop._kind_concurrency_limits == {  # noqa: SLF001 - configuration contract
        "benchmark_batch": 2,
        "evolution_run": 3,
    }


class _BackgroundStore:
    def __init__(self) -> None:
        self.evolution_runs: dict[str, dict[str, Any]] = {}
        self.evolution_batches: dict[str, dict[str, Any]] = {}
        self.background_state_lock = threading.Lock()
        self._background_state_fingerprint: str | None = None
        self._task_event_fingerprints: dict[str, str] = {}


class _EventLog:
    def __init__(self) -> None:
        self.published: list[str] = []

    def publish(self, entity: dict[str, Any]) -> None:
        self.published.append(str(entity.get("run_id") or entity.get("batch_id")))


def test_background_persistence_coalesces_active_updates_but_never_terminal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "background.sqlite3"
    conn = _connect(db_path)
    conn.close()

    def _factory() -> sqlite3.Connection:
        return _connect(db_path)

    store = _BackgroundStore()
    events = _EventLog()
    service = TaskPersistenceService(
        store,
        open_connection=_factory,
        task_event_log=lambda: events,  # type: ignore[arg-type]
    )
    monkeypatch.setenv("UI_BACKGROUND_PERSIST_INTERVAL_SECONDS", "3600")
    run = {
        "run_id": "run-1",
        "kind": "role_evolution_run",
        "status": "running",
        "progress": {"percent": 1},
    }
    store.evolution_runs["run-1"] = run

    service.persist_background_tasks()
    run["progress"] = {"percent": 2}
    service.persist_background_tasks()
    run["status"] = "failed"
    run["progress"] = {"percent": 3}
    service.persist_background_tasks()

    verify = _connect(db_path)
    try:
        row = verify.execute(
            "SELECT status, payload FROM ui_background_tasks WHERE entity_id = ?",
            ("run-1",),
        ).fetchone()
    finally:
        verify.close()
    assert row is not None
    assert row["status"] == "failed"
    assert json.loads(row["payload"])["progress"]["percent"] == 3
    assert events.published == ["run-1", "run-1"]
