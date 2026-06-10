"""Persistence boundary for UI task worker heartbeat rows."""

from __future__ import annotations

import json
from typing import Any

from storage.shared.database import StorageConnection, StorageRow

_WORKER_COLUMNS = (
    "worker_id",
    "status",
    "last_heartbeat_at",
    "lease_seconds",
    "current_task_id",
    "metadata",
)


class TaskWorkerRepository:
    """CRUD boundary for ``ui_task_workers``."""

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def upsert_heartbeat(
        self,
        *,
        worker_id: str,
        status: str,
        last_heartbeat_at: str,
        lease_seconds: int,
        current_task_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO ui_task_workers "
            "(worker_id, status, last_heartbeat_at, lease_seconds, current_task_id, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(worker_id) DO UPDATE SET "
            "status = excluded.status, "
            "last_heartbeat_at = excluded.last_heartbeat_at, "
            "lease_seconds = excluded.lease_seconds, "
            "current_task_id = excluded.current_task_id, "
            "metadata = excluded.metadata",
            (
                worker_id,
                status,
                last_heartbeat_at,
                int(lease_seconds),
                current_task_id,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, default=str),
            ),
        )

    def get(self, worker_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_worker_columns_sql()} FROM ui_task_workers WHERE worker_id = ?",
            (worker_id,),
        ).fetchone()
        return _worker_from_row(row) if row is not None else None

    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {_worker_columns_sql()} FROM ui_task_workers "
            "ORDER BY last_heartbeat_at DESC, worker_id LIMIT ?",
            (int(limit),),
        ).fetchall()
        return [_worker_from_row(row) for row in rows]


def _worker_columns_sql() -> str:
    return ", ".join(_WORKER_COLUMNS)


def _worker_from_row(row: StorageRow) -> dict[str, Any]:
    item = {key: row[key] for key in row.keys()}
    metadata = item.get("metadata")
    if isinstance(metadata, str):
        try:
            item["metadata"] = json.loads(metadata)
        except json.JSONDecodeError:
            item["metadata"] = {}
    elif metadata is None:
        item["metadata"] = {}
    return item
