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

    def get_many(self, task_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        values = list(dict.fromkeys(str(task_id) for task_id in task_ids if str(task_id)))
        if not values:
            return {}
        placeholders = ", ".join("?" for _ in values)
        rows = self._conn.execute(
            f"SELECT {_task_columns_sql()} FROM ui_task_queue "
            f"WHERE task_id IN ({placeholders})",
            tuple(values),
        ).fetchall()
        tasks = [_task_from_row(row) for row in rows]
        return {str(task["task_id"]): task for task in tasks}

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

    def status_counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS count FROM ui_task_queue GROUP BY status",
            (),
        ).fetchall()
        return {str(row["status"]): int(row["count"]) for row in rows}

    def stale_running_count(self, *, now: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM ui_task_queue "
            "WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?",
            (now,),
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    def fresh_running_count(self, *, now: str) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) AS count FROM ui_task_queue "
            "WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at > ?",
            (now,),
        ).fetchone()
        return int(row["count"]) if row is not None else 0

    def claim_next(
        self,
        *,
        worker_id: str,
        now: str,
        lease_expires_at: str,
        kinds: Iterable[str] | None = None,
        kind_concurrency_limits: dict[str, int] | None = None,
    ) -> dict[str, Any] | None:
        kind_values = [str(kind) for kind in kinds or [] if str(kind)]
        limits = {
            str(kind): max(1, int(limit))
            for kind, limit in (kind_concurrency_limits or {}).items()
            if str(kind) and int(limit) > 0
        }
        if callable(getattr(self._conn, "execute_for_update", None)):
            return self._claim_next_postgres(
                worker_id=worker_id,
                now=now,
                lease_expires_at=lease_expires_at,
                kind_values=kind_values,
                kind_concurrency_limits=limits,
            )
        return self._claim_next_portable(
            worker_id=worker_id,
            now=now,
            lease_expires_at=lease_expires_at,
            kind_values=kind_values,
            kind_concurrency_limits=limits,
        )

    def _claim_next_portable(
        self,
        *,
        worker_id: str,
        now: str,
        lease_expires_at: str,
        kind_values: list[str],
        kind_concurrency_limits: dict[str, int],
    ) -> dict[str, Any] | None:
        kind_filter = ""
        quota_filter, quota_parameters = _portable_kind_quota_sql(
            kind_concurrency_limits,
            candidate_alias="candidate_task",
            now=now,
        )
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
            "SELECT candidate_task.task_id FROM ui_task_queue AS candidate_task "
            "WHERE candidate_task.status = 'queued' AND candidate_task.cancel_requested = ? "
            f"{kind_filter}"
            f"{quota_filter}"
            "ORDER BY priority ASC, queued_at ASC, task_id ASC LIMIT 1"
            ") "
            "AND status = 'queued' AND cancel_requested = ? "
            f"RETURNING {_task_columns_sql()}",
            (*set_parameters, *where_parameters, *quota_parameters, False),
        ).fetchone()
        return _task_from_row(row) if row is not None else None

    def _claim_next_postgres(
        self,
        *,
        worker_id: str,
        now: str,
        lease_expires_at: str,
        kind_values: list[str],
        kind_concurrency_limits: dict[str, int],
    ) -> dict[str, Any] | None:
        kind_filter = ""
        candidate_parameters: list[Any] = [False]
        if kind_values:
            placeholders = ", ".join("?" for _ in kind_values)
            kind_filter = f"AND kind IN ({placeholders}) "
            candidate_parameters.extend(kind_values)
        quota_filter, quota_parameters = _postgres_kind_quota_sql(
            kind_concurrency_limits,
            candidate_alias="candidate_task",
            now=now,
        )
        row = self._conn.execute(
            "WITH candidate AS ("
            "SELECT candidate_task.task_id FROM ui_task_queue AS candidate_task "
            "WHERE candidate_task.status = 'queued' AND candidate_task.cancel_requested = ? "
            f"{kind_filter}"
            f"{quota_filter}"
            "ORDER BY priority ASC, queued_at ASC, task_id ASC "
            "FOR UPDATE SKIP LOCKED LIMIT 1"
            ") "
            "UPDATE ui_task_queue AS q SET "
            "status = 'running', "
            "lease_owner = ?, "
            "lease_expires_at = ?, "
            "started_at = COALESCE(started_at, ?), "
            "updated_at = ?, "
            "attempt = attempt + 1 "
            "FROM candidate "
            "WHERE q.task_id = candidate.task_id "
            "AND q.status = 'queued' AND q.cancel_requested = ? "
            f"RETURNING {_task_columns_sql('q')}",
            (
                *candidate_parameters,
                *quota_parameters,
                worker_id,
                lease_expires_at,
                now,
                now,
                False,
            ),
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
        worker_id: str | None = None,
    ) -> bool:
        owner_filter = ""
        parameters: list[Any] = [
            status,
            finished_at,
            finished_at,
            _json_dumps(result) if result is not None else None,
            _json_dumps(error) if error is not None else None,
            _json_dumps(progress) if progress is not None else None,
            task_id,
        ]
        if worker_id is not None:
            owner_filter = " AND lease_owner = ?"
            parameters.append(worker_id)
        cursor = self._conn.execute(
            "UPDATE ui_task_queue SET "
            "status = ?, finished_at = ?, updated_at = ?, result = ?, error = ?, progress = COALESCE(?, progress), "
            "lease_owner = NULL, lease_expires_at = NULL "
            f"WHERE task_id = ? AND status = 'running'{owner_filter}",
            tuple(parameters),
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


def _portable_kind_quota_sql(
    limits: dict[str, int],
    *,
    candidate_alias: str,
    now: str,
) -> tuple[str, list[Any]]:
    if not limits:
        return "", []
    clauses: list[str] = []
    parameters: list[Any] = []
    for kind, limit in sorted(limits.items()):
        clauses.append(
            f"({candidate_alias}.kind = ? AND "
            "(SELECT COUNT(*) FROM ui_task_queue AS active_task "
            "WHERE active_task.kind = ? AND active_task.status = 'running' "
            "AND active_task.lease_expires_at IS NOT NULL AND active_task.lease_expires_at > ?) < ?)"
        )
        parameters.extend((kind, kind, now, limit))
    placeholders = ", ".join("?" for _ in limits)
    return (
        f"AND ({candidate_alias}.kind NOT IN ({placeholders}) OR {' OR '.join(clauses)}) ",
        [*sorted(limits), *parameters],
    )


def _postgres_kind_quota_sql(
    limits: dict[str, int],
    *,
    candidate_alias: str,
    now: str,
) -> tuple[str, list[Any]]:
    quota_sql, parameters = _portable_kind_quota_sql(
        limits,
        candidate_alias=candidate_alias,
        now=now,
    )
    if not quota_sql:
        return "", []
    return (
        quota_sql
        + f"AND pg_try_advisory_xact_lock(hashtextextended('ui-task-kind:' || {candidate_alias}.kind, 0)) ",
        parameters,
    )


def _task_columns_sql(table_alias: str | None = None) -> str:
    if not table_alias:
        return ", ".join(_TASK_COLUMNS)
    return ", ".join(f"{table_alias}.{column}" for column in _TASK_COLUMNS)


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
