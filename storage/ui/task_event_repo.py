"""Persistence for UI task SSE replay events."""

from __future__ import annotations

import json
from typing import Any

from storage.shared.database import StorageConnection, StorageRow


class TaskEventRepository:
    """Append/replay boundary for ``ui_task_events``.

    Schema creation is owned by Alembic migrations; this repository only reads
    and writes runtime data.
    """

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def list_recent(self, *, limit: int) -> list[StorageRow]:
        return self._conn.execute(
            "SELECT id, entity_id, entity_kind, event, status, payload, created_at "
            "FROM ui_task_events ORDER BY id DESC LIMIT ?",
            (int(limit),),
        ).fetchall()

    def append(self, item: dict[str, Any]) -> int:
        insert_returning_id = getattr(self._conn, "insert_returning_id", None)
        if callable(insert_returning_id):
            try:
                return int(insert_returning_id(
                    "INSERT INTO ui_task_events "
                    "(entity_id, entity_kind, event, status, payload, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        item.get("entity_id"),
                        item.get("entity_kind"),
                        item.get("event"),
                        item.get("status"),
                        json.dumps(item.get("payload", {}), ensure_ascii=False),
                        item.get("created_at"),
                    ),
                    id_column="id",
                ))
            except RuntimeError as exc:
                if "requires a PostgreSQL storage adapter" not in str(exc):
                    raise
        self._conn.execute(
            "INSERT INTO ui_task_events "
            "(id, entity_id, entity_kind, event, status, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(item["id"]),
                item.get("entity_id"),
                item.get("entity_kind"),
                item.get("event"),
                item.get("status"),
                json.dumps(item.get("payload", {}), ensure_ascii=False),
                item.get("created_at"),
            ),
        )
        return int(item["id"])

    def upsert(self, item: dict[str, Any]) -> None:
        self.append(item)

    def delete_before_id(self, cutoff: int) -> None:
        self._conn.execute("DELETE FROM ui_task_events WHERE id < ?", (int(cutoff),))
