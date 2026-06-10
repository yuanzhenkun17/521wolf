"""Repository for persisted benchmark saved views."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from storage.postgres.unit_of_work import from_connection_factory
from storage.shared.database import StorageConnection, StorageRow


class BenchmarkSavedViewRepository:
    """Persist and query reusable benchmark leaderboard view configs.

    Schema creation is owned by Alembic migrations; this repository only reads
    and writes runtime data.
    """

    def __init__(self, conn: StorageConnection, *, autocommit: bool = False) -> None:
        self._conn = conn
        self._autocommit = autocommit

    def save(self, view: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO benchmark_saved_views "
            "(view_key, name, scope, benchmark_id, evaluation_set_id, target_role, "
            "view_config, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(view_key) DO UPDATE SET "
            "name = excluded.name, "
            "scope = excluded.scope, "
            "benchmark_id = excluded.benchmark_id, "
            "evaluation_set_id = excluded.evaluation_set_id, "
            "target_role = excluded.target_role, "
            "view_config = excluded.view_config, "
            "updated_at = excluded.updated_at",
            (
                view.get("view_key"),
                view.get("name"),
                view.get("scope"),
                view.get("benchmark_id"),
                view.get("evaluation_set_id"),
                view.get("target_role"),
                json.dumps(view.get("view_config") or {}, ensure_ascii=False),
                view.get("created_at"),
                view.get("updated_at"),
            ),
        )
        if self._autocommit:
            self._conn.commit()

    def list(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        where = "WHERE 1 = 1 "
        params: list[Any] = []
        if view_key:
            where += "AND view_key = ? "
            params.append(view_key)
        if scope:
            where += "AND scope = ? "
            params.append(scope)
        if evaluation_set_id:
            where += "AND evaluation_set_id = ? "
            params.append(evaluation_set_id)
        if benchmark_id:
            where += "AND benchmark_id = ? "
            params.append(benchmark_id)
        if target_role:
            where += "AND target_role = ? "
            params.append(target_role)
        params.append(_bounded_limit(limit))
        rows = self._conn.execute(
            "SELECT view_key, name, scope, benchmark_id, evaluation_set_id, target_role, "
            "view_config, created_at, updated_at "
            "FROM benchmark_saved_views "
            f"{where}"
            "ORDER BY updated_at DESC, view_key ASC LIMIT ?",
            tuple(params),
        ).fetchall()
        return [_view_from_row(row) for row in rows]

    def get(self, view_key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT view_key, name, scope, benchmark_id, evaluation_set_id, target_role, "
            "view_config, created_at, updated_at "
            "FROM benchmark_saved_views WHERE view_key = ?",
            (view_key,),
        ).fetchone()
        return _view_from_row(row) if row is not None else None

    def delete(self, view_key: str) -> bool:
        cursor = self._conn.execute(
            "DELETE FROM benchmark_saved_views WHERE view_key = ?",
            (view_key,),
        )
        if self._autocommit:
            self._conn.commit()
        return int(getattr(cursor, "rowcount", 0) or 0) > 0


def persist_benchmark_saved_view(
    connection_factory: Callable[[], StorageConnection],
    view: dict[str, Any],
) -> None:
    """Persist a saved view in a storage-owned write transaction."""
    with from_connection_factory(connection_factory) as tx:
        BenchmarkSavedViewRepository(tx.connection, autocommit=False).save(view)
        tx.commit()


def delete_benchmark_saved_view(
    connection_factory: Callable[[], StorageConnection],
    view_key: str,
) -> bool:
    """Delete a saved view in a storage-owned write transaction."""
    with from_connection_factory(connection_factory) as tx:
        deleted = BenchmarkSavedViewRepository(tx.connection, autocommit=False).delete(view_key)
        tx.commit()
        return deleted


def _view_from_row(row: StorageRow) -> dict[str, Any]:
    payload = _row_to_dict(row)
    return {
        "view_key": payload.get("view_key"),
        "name": payload.get("name"),
        "scope": payload.get("scope"),
        "benchmark_id": payload.get("benchmark_id"),
        "evaluation_set_id": payload.get("evaluation_set_id"),
        "target_role": payload.get("target_role"),
        "view_config": _decode_json_field(payload.get("view_config"), fallback={}),
        "created_at": payload.get("created_at"),
        "updated_at": payload.get("updated_at"),
    }


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    try:
        return dict(row)
    except Exception:
        pass
    keys = getattr(row, "keys", None)
    if callable(keys):
        return {key: row[key] for key in keys()}
    return {}


def _decode_json_field(value: Any, *, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _bounded_limit(limit: int) -> int:
    return max(1, min(int(limit or 50), 500))


__all__ = [
    "BenchmarkSavedViewRepository",
    "delete_benchmark_saved_view",
    "persist_benchmark_saved_view",
]
