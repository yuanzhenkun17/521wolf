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

    def upsert(self, item: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO ui_task_events "
            "(id, entity_id, entity_kind, event, status, payload, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "entity_id = excluded.entity_id, "
            "entity_kind = excluded.entity_kind, "
            "event = excluded.event, "
            "status = excluded.status, "
            "payload = excluded.payload, "
            "created_at = excluded.created_at",
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

    def delete_before_id(self, cutoff: int) -> None:
        self._conn.execute("DELETE FROM ui_task_events WHERE id < ?", (int(cutoff),))
