"""Low-coupling worker skeleton for PostgreSQL-backed UI task queue rows."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.util.time import beijing_now
from storage.ui.task_queue_repo import TaskQueueRepository


class TaskCancelled(RuntimeError):
    """Raised by executors when a cooperative cancel checkpoint is reached."""


TaskExecutor = Callable[[dict[str, Any], "TaskExecutionContext"], dict[str, Any] | None]


class TaskExecutorRegistry:
    """Map task kinds to executor callables."""

    def __init__(self, executors: Mapping[str, TaskExecutor] | None = None) -> None:
        self._executors: dict[str, TaskExecutor] = {}
        for kind, executor in (executors or {}).items():
            self.register(kind, executor)

    def register(
        self,
        kind: str,
        executor: TaskExecutor | None = None,
    ) -> TaskExecutor | Callable[[TaskExecutor], TaskExecutor]:
        normalized_kind = str(kind)
        if not normalized_kind:
            raise ValueError("task kind must not be empty")

        def _decorator(fn: TaskExecutor) -> TaskExecutor:
            self._executors[normalized_kind] = fn
            return fn

        if executor is None:
            return _decorator
        return _decorator(executor)

    def get(self, kind: str) -> TaskExecutor | None:
        return self._executors.get(str(kind))

    def kinds(self) -> tuple[str, ...]:
        return tuple(sorted(self._executors))


@dataclass(frozen=True, slots=True)
class TaskWorkerRunResult:
    """Outcome for a single worker polling step."""

    task_id: str | None
    kind: str | None
    status: str
    executed: bool = False
    error: dict[str, Any] | None = None


class TaskExecutionContext:
    """Executor-facing helpers for heartbeat and cooperative cancellation."""

    def __init__(
        self,
        *,
        repository: TaskQueueRepository,
        task: dict[str, Any],
        worker_id: str,
        lease_seconds: int,
        clock: Callable[[], datetime],
        after_repository_update: Callable[[], None] | None = None,
    ) -> None:
        self._repository = repository
        self._task = dict(task)
        self._worker_id = worker_id
        self._lease_seconds = int(lease_seconds)
        self._clock = clock
        self._after_repository_update = after_repository_update

    @property
    def task(self) -> dict[str, Any]:
        return dict(self._task)

    @property
    def task_id(self) -> str:
        return str(self._task["task_id"])

    @property
    def kind(self) -> str:
        return str(self._task["kind"])

    @property
    def payload(self) -> dict[str, Any]:
        payload = self._task.get("payload")
        return dict(payload) if isinstance(payload, dict) else {}

    def heartbeat(self, progress: dict[str, Any] | None = None) -> bool:
        now = self._clock()
        ok = self._repository.heartbeat(
            task_id=self.task_id,
            worker_id=self._worker_id,
            lease_expires_at=(now + timedelta(seconds=self._lease_seconds)).isoformat(),
            updated_at=now.isoformat(),
            progress=progress,
        )
        if ok and self._after_repository_update is not None:
            self._after_repository_update()
        return ok

    def cancel_requested(self) -> bool:
        latest = self._repository.get(self.task_id)
        if latest is not None:
            self._task = dict(latest)
        return _truthy(self._task.get("cancel_requested"))

    def raise_if_cancel_requested(self) -> None:
        if self.cancel_requested():
            raise TaskCancelled("task cancellation requested")


class TaskWorker:
    """Claim one queued task at a time and dispatch it by ``task.kind``."""

    def __init__(
        self,
        *,
        repository: TaskQueueRepository,
        executors: TaskExecutorRegistry | Mapping[str, TaskExecutor] | None = None,
        worker_id: str,
        lease_seconds: int = 300,
        clock: Callable[[], datetime] = beijing_now,
        after_repository_update: Callable[[], None] | None = None,
    ) -> None:
        self._repository = repository
        self.registry = executors if isinstance(executors, TaskExecutorRegistry) else TaskExecutorRegistry(executors)
        self._worker_id = str(worker_id)
        self._lease_seconds = int(lease_seconds)
        self._clock = clock
        self._after_repository_update = after_repository_update

    def run_once(self) -> TaskWorkerRunResult:
        kinds = self.registry.kinds()
        if not kinds:
            return TaskWorkerRunResult(task_id=None, kind=None, status="idle")

        now = self._clock()
        task = self._repository.claim_next(
            worker_id=self._worker_id,
            now=now.isoformat(),
            lease_expires_at=(now + timedelta(seconds=self._lease_seconds)).isoformat(),
            kinds=kinds,
        )
        if task is None:
            return TaskWorkerRunResult(task_id=None, kind=None, status="idle")
        self._commit_if_requested()

        context = TaskExecutionContext(
            repository=self._repository,
            task=task,
            worker_id=self._worker_id,
            lease_seconds=self._lease_seconds,
            clock=self._clock,
            after_repository_update=self._after_repository_update,
        )
        task_id = str(task["task_id"])
        kind = str(task["kind"])
        if context.cancel_requested():
            return self._finish_cancelled(task_id=task_id, kind=kind, executed=False)

        executor = self.registry.get(kind)
        if executor is None:
            return self._finish_failed(
                task_id=task_id,
                kind=kind,
                executed=False,
                error={
                    "kind": "missing_executor",
                    "message": f"no executor registered for task kind {kind!r}",
                },
            )

        context.heartbeat(progress={"stage": "running"})
        try:
            result = executor(dict(task), context)
            if context.cancel_requested():
                raise TaskCancelled("task cancellation requested")
        except TaskCancelled as exc:
            return self._finish_cancelled(task_id=task_id, kind=kind, executed=True, message=str(exc))
        except Exception as exc:  # noqa: BLE001 - task failures are persisted as task errors
            return self._finish_failed(
                task_id=task_id,
                kind=kind,
                executed=True,
                error=_error_from_exception(exc),
            )

        finished_at = self._clock().isoformat()
        self._repository.complete(
            task_id=task_id,
            status="succeeded",
            finished_at=finished_at,
            result=result,
        )
        self._commit_if_requested()
        return TaskWorkerRunResult(task_id=task_id, kind=kind, status="succeeded", executed=True)

    def run_available(self, *, max_tasks: int | None = None) -> list[TaskWorkerRunResult]:
        results: list[TaskWorkerRunResult] = []
        while max_tasks is None or len(results) < max_tasks:
            result = self.run_once()
            if result.status == "idle":
                break
            results.append(result)
        return results

    def _finish_cancelled(
        self,
        *,
        task_id: str,
        kind: str,
        executed: bool,
        message: str = "task cancellation requested",
    ) -> TaskWorkerRunResult:
        error = {"kind": "cancelled", "message": message or "task cancellation requested"}
        self._repository.complete(
            task_id=task_id,
            status="cancelled",
            finished_at=self._clock().isoformat(),
            error=error,
        )
        self._commit_if_requested()
        return TaskWorkerRunResult(task_id=task_id, kind=kind, status="cancelled", executed=executed, error=error)

    def _finish_failed(
        self,
        *,
        task_id: str,
        kind: str,
        executed: bool,
        error: dict[str, Any],
    ) -> TaskWorkerRunResult:
        self._repository.complete(
            task_id=task_id,
            status="failed",
            finished_at=self._clock().isoformat(),
            error=error,
        )
        self._commit_if_requested()
        return TaskWorkerRunResult(task_id=task_id, kind=kind, status="failed", executed=executed, error=error)

    def _commit_if_requested(self) -> None:
        if self._after_repository_update is not None:
            self._after_repository_update()


def _error_from_exception(exc: BaseException) -> dict[str, Any]:
    return {
        "kind": "executor_error",
        "exception_type": type(exc).__name__,
        "message": str(exc),
    }


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return bool(value)


__all__ = [
    "TaskCancelled",
    "TaskExecutionContext",
    "TaskExecutor",
    "TaskExecutorRegistry",
    "TaskWorker",
    "TaskWorkerRunResult",
]
