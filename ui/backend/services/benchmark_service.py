"""Benchmark service facade for the UI backend.

The facade keeps the R2 service boundary importable without moving benchmark
business logic yet. BackendStore injects the current private implementations so
missing methods fail fast instead of falling back into public wrapper recursion.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Mapping
from inspect import isawaitable
from typing import Any, Protocol, cast

from fastapi import HTTPException

from app.util.time import beijing_now_iso
from storage.benchmark.leaderboard_repo import BenchmarkLeaderboardRepository
from storage.benchmark.saved_view_repo import (
    BenchmarkSavedViewRepository,
    delete_benchmark_saved_view,
    persist_benchmark_saved_view,
)
from storage.benchmark.snapshot_repo import (
    BenchmarkSnapshotRepository,
    persist_benchmark_snapshot,
)
from ui.backend.schemas import (
    BenchmarkLifecycleRequest,
    BenchmarkRequest,
    BenchmarkSnapshotRequest,
    BenchmarkViewRequest,
)
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.evolution_serializers import _evolution_batch_summary
from ui.backend.services.task_service import BackgroundTaskServiceProtocol
from ui.backend.sse import _sse, stream_task_event_log_sse, task_event_log_matches_entity
from ui.backend.task_state import _set_task_contract

BenchmarkCallable = Callable[..., Any]
_TERMINAL_BENCHMARK_SSE_STATUSES = {"completed", "failed", "cancelled", "interrupted"}

BENCHMARK_PUBLIC_METHODS: tuple[str, ...] = (
    "leaderboard_scores_for_role",
    "leaderboard_entries",
    "model_leaderboard_entries",
    "leaderboard_unrankable_evidence",
    "leaderboard_compare",
    "leaderboard_scores_for_roles",
    "list_benchmark_specs",
    "get_benchmark_spec_summary",
    "update_benchmark_lifecycle",
    "list_benchmark_seed_sets",
    "get_benchmark_seed_set",
    "plan_benchmark",
    "queue_benchmark",
    "run_queued_benchmark",
    "benchmark_model_runtime",
    "benchmark_batch_detail",
    "benchmark_batch_games",
    "benchmark_batch_diagnostics",
    "benchmark_batch_report",
    "benchmark_reports",
    "benchmark_diagnostics",
    "create_benchmark_snapshot",
    "list_benchmark_snapshots",
    "get_benchmark_snapshot",
    "benchmark_snapshot_export",
    "benchmark_snapshot_compare",
    "save_benchmark_view",
    "list_benchmark_views",
    "get_benchmark_view",
    "delete_benchmark_view",
)


class BenchmarkServiceContextProtocol(Protocol):
    """Context capabilities required by ``BenchmarkService``."""

    paths: object
    evolution_batches: dict[str, dict[str, Any]]

    @property
    def task_service(self) -> BackgroundTaskServiceProtocol:
        ...


class BenchmarkService:
    """Compatibility facade for benchmark-facing ``BackendStore`` methods."""

    def __init__(
        self,
        context: BenchmarkServiceContextProtocol,
        callables: Mapping[str, BenchmarkCallable] | None = None,
        *,
        allow_context_fallback: bool = False,
    ) -> None:
        self._context = context
        self._callables = dict(callables or {})
        self._allow_context_fallback = allow_context_fallback

    @property
    def context(self) -> BenchmarkServiceContextProtocol:
        return self._context

    @property
    def _tasks(self) -> BackgroundTaskServiceProtocol:
        return self._context.task_service

    def _open_connection(self) -> Any:
        from app.lib.score import open_eval_connection

        return open_eval_connection(getattr(self._context, "paths", None))

    def load_role_leaderboard_rows(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkLeaderboardRepository(conn).list_role_rows(
                role,
                evaluation_set_id=evaluation_set_id,
            )
        finally:
            if conn is not None:
                conn.close()

    def load_leaderboard_rows(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[Any]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkLeaderboardRepository(conn).list(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role,
                limit=limit,
            )
        finally:
            if conn is not None:
                conn.close()

    def load_role_leaderboard_rows_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkLeaderboardRepository(conn).list_role_rows_for_roles(
                roles,
                evaluation_set_id=evaluation_set_id,
            )
        finally:
            if conn is not None:
                conn.close()

    def persist_benchmark_snapshot(self, snapshot: dict[str, Any]) -> None:
        persist_benchmark_snapshot(self._open_connection, snapshot)

    def load_benchmark_snapshot_summaries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkSnapshotRepository(conn).list(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                limit=limit,
            )
        finally:
            if conn is not None:
                conn.close()

    def load_benchmark_snapshot_detail(self, snapshot_id: str) -> dict[str, Any] | None:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkSnapshotRepository(conn).get(snapshot_id)
        finally:
            if conn is not None:
                conn.close()

    def persist_benchmark_saved_view(self, view: dict[str, Any]) -> None:
        persist_benchmark_saved_view(self._open_connection, view)

    def load_benchmark_saved_views(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkSavedViewRepository(conn).list(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                view_key=view_key,
                limit=limit,
            )
        finally:
            if conn is not None:
                conn.close()

    def delete_benchmark_saved_view(self, view_key: str) -> bool:
        return delete_benchmark_saved_view(self._open_connection, view_key)

    def _resolve(self, method_name: str) -> BenchmarkCallable:
        if method_name in self._callables:
            target = self._callables[method_name]
            if callable(target):
                return target
            raise TypeError(f"BenchmarkService callable is not callable: {method_name}")

        if self._allow_context_fallback:
            target = getattr(self._context, method_name, None)
            if callable(target):
                return target
        raise AttributeError(f"BenchmarkService cannot resolve benchmark method: {method_name}")

    def _call(self, method_name: str, /, *args: Any, **kwargs: Any) -> Any:
        return self._resolve(method_name)(*args, **kwargs)

    async def _acall(self, method_name: str, /, *args: Any, **kwargs: Any) -> Any:
        result = self._resolve(method_name)(*args, **kwargs)
        if isawaitable(result):
            return await result
        return result

    @staticmethod
    def sse_event(status: Any) -> str:
        status_text = str(status or "").lower()
        if status_text in _TERMINAL_BENCHMARK_SSE_STATUSES:
            return status_text
        return "progress"

    @classmethod
    def task_event_name(cls, item: dict[str, Any]) -> str:
        event_name = str(item.get("event") or cls.sse_event(item.get("status")))
        if event_name == "progress":
            return cls.sse_event(item.get("status"))
        return event_name

    def _batch(self, batch_id: str) -> dict[str, Any]:
        batch = self._context.evolution_batches.get(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return batch

    def benchmark_specs_payload(self) -> dict[str, Any]:
        return {"kind": "benchmark_specs", "schema_version": 1, "items": self.list_benchmark_specs()}

    def stop_benchmark(self, batch_id: str) -> dict[str, Any]:
        batch = self._batch(batch_id)
        batch["status"] = "failed"
        batch["stop_requested"] = True
        _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
        batch["finished_at"] = beijing_now_iso()
        batch["error"] = batch.get("error") or MANUAL_STOP_REASON
        self._tasks.mark_benchmark_stage(
            batch,
            "stopped",
            status="failed",
            percent=self._tasks.task_progress_percent(batch),
            completed_roles=int(batch.get("progress", {}).get("completed_roles", 0)) if isinstance(batch.get("progress"), dict) else 0,
            role_count=len(batch.get("roles", []) or []),
            diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
        )
        self._tasks.persist_background_tasks()
        return batch

    def stream_benchmark_events(self, batch_id: str, last_event_id: int) -> AsyncIterator[str]:
        batch = self._batch(batch_id)
        task_event_log = self._tasks.task_event_log

        async def stream() -> AsyncIterator[str]:
            if task_event_log_matches_entity(
                task_event_log,
                batch_id,
                batch,
                terminal_statuses=_TERMINAL_BENCHMARK_SSE_STATUSES,
            ):
                async for frame in stream_task_event_log_sse(
                    task_event_log,
                    batch_id,
                    after_event_id=last_event_id,
                    ping_payload=lambda: {"batch_id": batch_id, "status": batch.get("status")},
                    event_name=self.task_event_name,
                    terminal_statuses=_TERMINAL_BENCHMARK_SSE_STATUSES,
                ):
                    yield frame
                return
            if last_event_id < 1:
                yield _sse(self.sse_event(batch.get("status")), _evolution_batch_summary(batch), event_id=1)

        return stream()

    def leaderboard_scores_for_role(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        return cast(
            dict[str, dict[str, Any]],
            self._call("leaderboard_scores_for_role", role, evaluation_set_id=evaluation_set_id),
        )

    def leaderboard_entries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            self._call(
                "leaderboard_entries",
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role,
                limit=limit,
            ),
        )

    def model_leaderboard_entries(
        self,
        *,
        evaluation_set_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            self._call("model_leaderboard_entries", evaluation_set_id=evaluation_set_id, limit=limit),
        )

    def leaderboard_unrankable_evidence(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return cast(
            list[dict[str, Any]],
            self._call(
                "leaderboard_unrankable_evidence",
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role,
                limit=limit,
                rows=rows,
            ),
        )

    def leaderboard_compare(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        baseline_subject_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "leaderboard_compare",
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role,
                baseline_subject_id=baseline_subject_id,
                limit=limit,
            ),
        )

    def leaderboard_scores_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        return cast(
            dict[str, dict[str, dict[str, Any]]],
            self._call("leaderboard_scores_for_roles", roles, evaluation_set_id=evaluation_set_id),
        )

    def list_benchmark_specs(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], self._call("list_benchmark_specs"))

    def get_benchmark_spec_summary(self, benchmark_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_benchmark_spec_summary", benchmark_id))

    def update_benchmark_lifecycle(
        self,
        benchmark_id: str,
        request: BenchmarkLifecycleRequest,
    ) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("update_benchmark_lifecycle", benchmark_id, request))

    def list_benchmark_seed_sets(self) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("list_benchmark_seed_sets"))

    def get_benchmark_seed_set(self, seed_set_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_benchmark_seed_set", seed_set_id))

    def plan_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("plan_benchmark", request))

    def queue_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("queue_benchmark", request))

    async def run_queued_benchmark(self, batch_id: str, request: BenchmarkRequest) -> None:
        await self._acall("run_queued_benchmark", batch_id, request)

    def benchmark_model_runtime(self, request: BenchmarkRequest | None = None) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("benchmark_model_runtime", request))

    def benchmark_batch_detail(self, batch_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("benchmark_batch_detail", batch_id))

    def benchmark_batch_games(
        self,
        batch_id: str,
        *,
        result_batch_id: str | None = None,
        target_role: str | None = None,
        status: str | None = None,
        seed: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "benchmark_batch_games",
                batch_id,
                result_batch_id=result_batch_id,
                target_role=target_role,
                status=status,
                seed=seed,
                limit=limit,
                offset=offset,
            ),
        )

    def benchmark_batch_diagnostics(
        self,
        batch_id: str,
        *,
        target_role: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "benchmark_batch_diagnostics",
                batch_id,
                target_role=target_role,
                kind=kind,
                level=level,
                status=status,
                stage=stage,
                seed=seed,
            ),
        )

    def benchmark_batch_report(self, batch_id: str, *, format: str = "json") -> dict[str, Any]:
        return cast(dict[str, Any], self._call("benchmark_batch_report", batch_id, format=format))

    def benchmark_reports(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "benchmark_reports",
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                model_id=model_id,
                model_config_hash=model_config_hash,
                status=status,
                limit=limit,
                offset=offset,
            ),
        )

    def benchmark_diagnostics(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "benchmark_diagnostics",
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                model_id=model_id,
                model_config_hash=model_config_hash,
                kind=kind,
                level=level,
                status=status,
                stage=stage,
                seed=seed,
                limit=limit,
                offset=offset,
            ),
        )

    def create_benchmark_snapshot(self, request: BenchmarkSnapshotRequest) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("create_benchmark_snapshot", request))

    def list_benchmark_snapshots(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "list_benchmark_snapshots",
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                limit=limit,
            ),
        )

    def get_benchmark_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_benchmark_snapshot", snapshot_id))

    def benchmark_snapshot_export(self, snapshot_id: str, *, format: str = "json") -> dict[str, Any]:
        return cast(dict[str, Any], self._call("benchmark_snapshot_export", snapshot_id, format=format))

    def benchmark_snapshot_compare(
        self,
        snapshot_id: str,
        *,
        against_snapshot_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "benchmark_snapshot_compare",
                snapshot_id,
                against_snapshot_id=against_snapshot_id,
                limit=limit,
            ),
        )

    def save_benchmark_view(self, request: BenchmarkViewRequest) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("save_benchmark_view", request))

    def list_benchmark_views(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return cast(
            dict[str, Any],
            self._call(
                "list_benchmark_views",
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                view_key=view_key,
                limit=limit,
            ),
        )

    def get_benchmark_view(self, view_key: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("get_benchmark_view", view_key))

    def delete_benchmark_view(self, view_key: str) -> dict[str, Any]:
        return cast(dict[str, Any], self._call("delete_benchmark_view", view_key))
