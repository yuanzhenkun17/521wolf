"""Persistence for UI background task recovery state."""

from __future__ import annotations

import json
from typing import Any

from storage.shared.database import StorageConnection, StorageRow


class BackgroundTaskRepository:
    """CRUD boundary for ``ui_background_tasks``.

    Schema creation is owned by Alembic migrations; this repository only reads
    and writes runtime data.
    """

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        entity_id: str,
        entity_kind: str | None,
        status: str | None,
        payload: dict[str, Any],
        updated_at: str,
    ) -> None:
        self._conn.execute(
            "INSERT INTO ui_background_tasks "
            "(entity_id, entity_kind, status, payload, updated_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(entity_id) DO UPDATE SET "
            "entity_kind = excluded.entity_kind, "
            "status = excluded.status, "
            "payload = excluded.payload, "
            "updated_at = excluded.updated_at",
            (
                entity_id,
                entity_kind,
                status,
                json.dumps(payload, ensure_ascii=False),
                updated_at,
            ),
        )

    def list_all(self) -> list[StorageRow]:
        return self._conn.execute(
            "SELECT entity_id, entity_kind, status, payload, updated_at "
            "FROM ui_background_tasks ORDER BY updated_at, entity_id"
        ).fetchall()

    def list_all_summary(self) -> list[StorageRow]:
        """List all tasks without the large payload column for fast startup."""
        return self._conn.execute(
            "SELECT entity_id, entity_kind, status, updated_at "
            "FROM ui_background_tasks ORDER BY updated_at, entity_id"
        ).fetchall()

    def get_payload(self, entity_id: str) -> dict[str, Any] | None:
        """Fetch only the payload for a single task."""
        row = self._conn.execute(
            "SELECT payload FROM ui_background_tasks WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if row is None:
            return None
        try:
            import json
            return json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        except (TypeError, json.JSONDecodeError):
            return None
