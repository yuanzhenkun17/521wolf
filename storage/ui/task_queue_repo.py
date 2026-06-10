"""Persistence boundary for PostgreSQL-backed UI task queue rows."""

from __future__ import annotations

import json
from typing import Any, Iterable

from storage.shared.database import StorageConnection, StorageRow

_TASK_COLUMNS = (
    "task_id",
    "kind",
    "status",
    "priority",
    "payload",
    "result",
    "error",
    "progress",
    "attempt",
    "max_attempts",
    "lease_owner",
    "lease_expires_at",
    "queued_at",
    "started_at",
    "updated_at",
    "finished_at",
    "cancel_requested",
    "idempotency_key",
    "parent_task_id",
    "source",
    "metadata",
)

_JSON_FIELDS = {"payload", "result", "error", "progress", "metadata"}


class TaskQueueRepository:
    """CRUD and claim boundary for ``ui_task_queue``.

    Schema creation is owned by Alembic migrations. This repository intentionally
    stays storage-focused; worker policy and executor dispatch live above it.
    """

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def enqueue(
        self,
        *,
        task_id: str,
        kind: str,
        payload: dict[str, Any],
        queued_at: str,
        updated_at: str | None = None,
        priority: int = 100,
        max_attempts: int = 1,
        idempotency_key: str | None = None,
        parent_task_id: str | None = None,
        source: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO ui_task_queue "
            "(task_id, kind, status, priority, payload, attempt, max_attempts, "
            "queued_at, updated_at, cancel_requested, idempotency_key, parent_task_id, source, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                kind,
                "queued",
                int(priority),
                _json_dumps(payload),
                0,
                int(max_attempts),
                queued_at,
                updated_at or queued_at,
                False,
                idempotency_key,
                parent_task_id,
                source,
                _json_dumps(metadata or {}),
            ),
        )

    def get(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_task_columns_sql()} FROM ui_task_queue WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return _task_from_row(row) if row is not None else None

    def get_by_idempotency_key(self, idempotency_key: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_task_columns_sql()} FROM ui_task_queue WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        return _task_from_row(row) if row is not None else None

    def list_recent(
        self,
        *,
        statuses: Iterable[str] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        status_values = [str(status) for status in statuses or [] if str(status)]
        if status_values:
            placeholders = ", ".join("?" for _ in status_values)
            rows = self._conn.execute(
                f"SELECT {_task_columns_sql()} FROM ui_task_queue "
                f"WHERE status IN ({placeholders}) "
                "ORDER BY updated_at DESC, task_id LIMIT ?",
                (*status_values, int(limit)),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {_task_columns_sql()} FROM ui_task_queue "
                "ORDER BY updated_at DESC, task_id LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [_task_from_row(row) for row in rows]

    def claim_next(
        self,
        *,
        worker_id: str,
        now: str,
        lease_expires_at: str,
        kinds: Iterable[str] | None = None,
    ) -> dict[str, Any] | None:
        kind_values = [str(kind) for kind in kinds or [] if str(kind)]
        kind_filter = ""
        set_parameters: list[Any] = [
            worker_id,
            lease_expires_at,
            now,
            now,
        ]
        where_parameters: list[Any] = [False]
        if kind_values:
            placeholders = ", ".join("?" for _ in kind_values)
            kind_filter = f"AND kind IN ({placeholders}) "
            where_parameters.extend(kind_values)
        row = self._conn.execute(
            "UPDATE ui_task_queue SET "
            "status = 'running', "
            "lease_owner = ?, "
            "lease_expires_at = ?, "
            "started_at = COALESCE(started_at, ?), "
            "updated_at = ?, "
            "attempt = attempt + 1 "
            "WHERE task_id = ("
            "SELECT task_id FROM ui_task_queue "
            "WHERE status = 'queued' AND cancel_requested = ? "
            f"{kind_filter}"
            "ORDER BY priority ASC, queued_at ASC, task_id ASC LIMIT 1"
            ") "
            f"RETURNING {_task_columns_sql()}",
            (*set_parameters, *where_parameters),
        ).fetchone()
        return _task_from_row(row) if row is not None else None

    def heartbeat(
        self,
        *,
        task_id: str,
        worker_id: str,
        lease_expires_at: str,
        updated_at: str,
        progress: dict[str, Any] | None = None,
    ) -> bool:
        cursor = self._conn.execute(
            "UPDATE ui_task_queue SET "
            "lease_expires_at = ?, updated_at = ?, progress = COALESCE(?, progress) "
            "WHERE task_id = ? AND status = 'running' AND lease_owner = ?",
            (
                lease_expires_at,
                updated_at,
                _json_dumps(progress) if progress is not None else None,
                task_id,
                worker_id,
            ),
        )
        return cursor.rowcount > 0

    def complete(
        self,
        *,
        task_id: str,
        status: str,
        finished_at: str,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        progress: dict[str, Any] | None = None,
    ) -> bool:
        cursor = self._conn.execute(
            "UPDATE ui_task_queue SET "
            "status = ?, finished_at = ?, updated_at = ?, result = ?, error = ?, progress = COALESCE(?, progress), "
            "lease_owner = NULL, lease_expires_at = NULL "
            "WHERE task_id = ?",
            (
                status,
                finished_at,
                finished_at,
                _json_dumps(result) if result is not None else None,
                _json_dumps(error) if error is not None else None,
                _json_dumps(progress) if progress is not None else None,
                task_id,
            ),
        )
        return cursor.rowcount > 0

    def request_cancel(self, *, task_id: str, updated_at: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE ui_task_queue SET "
            "cancel_requested = ?, "
            "status = CASE WHEN status IN ('queued', 'interrupted') THEN 'cancelled' ELSE status END, "
            "finished_at = CASE WHEN status IN ('queued', 'interrupted') THEN ? ELSE finished_at END, "
            "error = CASE WHEN status IN ('queued', 'interrupted') THEN ? ELSE error END, "
            "updated_at = ? "
            "WHERE task_id = ? AND status NOT IN ('succeeded', 'failed', 'cancelled')",
            (
                True,
                updated_at,
                _json_dumps({"kind": "cancelled", "message": "task cancellation requested"}),
                updated_at,
                task_id,
            ),
        )
        return cursor.rowcount > 0

    def retry_interrupted(self, *, task_id: str, updated_at: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE ui_task_queue SET "
            "status = 'queued', lease_owner = NULL, lease_expires_at = NULL, "
            "finished_at = NULL, error = NULL, updated_at = ? "
            "WHERE task_id = ? AND status = 'interrupted'",
            (updated_at, task_id),
        )
        return cursor.rowcount > 0

    def mark_expired_running_interrupted(self, *, now: str) -> int:
        cursor = self._conn.execute(
            "UPDATE ui_task_queue SET "
            "status = 'interrupted', updated_at = ?, lease_owner = NULL, lease_expires_at = NULL "
            "WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
            (now, now),
        )
        return int(cursor.rowcount)


def _task_columns_sql() -> str:
    return ", ".join(_TASK_COLUMNS)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _task_from_row(row: StorageRow) -> dict[str, Any]:
    item = {key: row[key] for key in row.keys()}
    for field in _JSON_FIELDS:
        item[field] = _json_loads(item.get(field))
    return item
