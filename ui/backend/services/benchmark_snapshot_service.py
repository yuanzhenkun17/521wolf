"""Benchmark snapshot, saved-view, and export service helpers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol, cast

from storage.benchmark.saved_view_repo import (
    BenchmarkSavedViewRepository,
    delete_benchmark_saved_view,
    persist_benchmark_saved_view,
)
from storage.benchmark.snapshot_repo import (
    BenchmarkSnapshotRepository,
    persist_benchmark_snapshot,
)
from ui.backend.schemas import BenchmarkSnapshotRequest, BenchmarkViewRequest

BenchmarkCallable = Callable[..., Any]


class BenchmarkSnapshotServiceContextProtocol(Protocol):
    """Context capabilities required by ``BenchmarkSnapshotService``."""

    paths: object


class BenchmarkSnapshotService:
    """Facade and persistence helper for benchmark release artifacts."""

    def __init__(
        self,
        context: BenchmarkSnapshotServiceContextProtocol,
        callables: Mapping[str, BenchmarkCallable] | None = None,
        *,
        resolver: Callable[[str], BenchmarkCallable] | None = None,
    ) -> None:
        self._context = context
        self._callables = dict(callables or {})
        self._resolver = resolver

    def _open_connection(self) -> Any:
        from app.lib.score import open_eval_connection

        return open_eval_connection(getattr(self._context, "paths", None))

    def _resolve(self, method_name: str) -> BenchmarkCallable:
        if self._resolver is not None:
            return self._resolver(method_name)
        if method_name in self._callables:
            target = self._callables[method_name]
            if callable(target):
                return target
            raise TypeError(f"BenchmarkSnapshotService callable is not callable: {method_name}")
        raise AttributeError(f"BenchmarkSnapshotService cannot resolve benchmark method: {method_name}")

    def _call(self, method_name: str, /, *args: Any, **kwargs: Any) -> Any:
        return self._resolve(method_name)(*args, **kwargs)

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
