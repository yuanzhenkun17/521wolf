"""Persistence boundary for task artifact metadata."""

from __future__ import annotations

import json
from typing import Any

from storage.shared.database import StorageConnection, StorageRow

_ARTIFACT_COLUMNS = (
    "artifact_id",
    "task_id",
    "artifact_type",
    "name",
    "relative_path",
    "content_type",
    "size_bytes",
    "sha256",
    "created_at",
    "metadata",
)


class TaskArtifactRepository:
    """CRUD boundary for ``ui_task_artifacts`` metadata."""

    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def upsert(
        self,
        *,
        artifact_id: str,
        task_id: str,
        artifact_type: str,
        name: str,
        relative_path: str,
        created_at: str,
        content_type: str | None = None,
        size_bytes: int | None = None,
        sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO ui_task_artifacts "
            "(artifact_id, task_id, artifact_type, name, relative_path, content_type, size_bytes, sha256, created_at, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(artifact_id) DO UPDATE SET "
            "task_id = excluded.task_id, "
            "artifact_type = excluded.artifact_type, "
            "name = excluded.name, "
            "relative_path = excluded.relative_path, "
            "content_type = excluded.content_type, "
            "size_bytes = excluded.size_bytes, "
            "sha256 = excluded.sha256, "
            "created_at = excluded.created_at, "
            "metadata = excluded.metadata",
            (
                artifact_id,
                task_id,
                artifact_type,
                name,
                relative_path,
                content_type,
                size_bytes,
                sha256,
                created_at,
                json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True, default=str),
            ),
        )

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            f"SELECT {_artifact_columns_sql()} FROM ui_task_artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        return _artifact_from_row(row) if row is not None else None

    def list_for_task(self, task_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT {_artifact_columns_sql()} FROM ui_task_artifacts "
            "WHERE task_id = ? ORDER BY created_at, artifact_id",
            (task_id,),
        ).fetchall()
        return [_artifact_from_row(row) for row in rows]

    def delete_for_task(self, task_id: str) -> int:
        cursor = self._conn.execute("DELETE FROM ui_task_artifacts WHERE task_id = ?", (task_id,))
        return int(cursor.rowcount)


def _artifact_columns_sql() -> str:
    return ", ".join(_ARTIFACT_COLUMNS)


def _artifact_from_row(row: StorageRow) -> dict[str, Any]:
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
