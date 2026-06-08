"""Report repo: CRUD for per-game summary reports (battle database)."""

from __future__ import annotations

import logging
from typing import Any

from storage.shared.database import StorageConnection
from storage.shared.interfaces import storage_timestamp, TimestampProvider

_log = logging.getLogger(__name__)


class ReportStore:
    """Store and query game summary reports."""

    def __init__(
        self,
        conn: StorageConnection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_report(
        self,
        report_id: str,
        game_id: str,
        summary: str,
        *,
        created_at: str | None = None,
    ) -> str:
        now = created_at or self._timestamp()
        self._conn.execute(
            "INSERT INTO reports (id, game_id, summary, created_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(game_id) DO UPDATE SET "
            "id = excluded.id, "
            "summary = excluded.summary, "
            "created_at = excluded.created_at",
            (report_id, game_id, summary, now),
        )
        self._conn.commit()
        return report_id

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_for_game(self, game_id: str) -> dict[str, Any] | None:
        """Return the report for a specific game (game_id is UNIQUE)."""
        row = self._conn.execute(
            "SELECT * FROM reports WHERE game_id = ?", (game_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def list_reports(
        self,
        *,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM reports ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_for_game(self, game_id: str) -> int:
        cursor = self._conn.execute(
            "DELETE FROM reports WHERE game_id = ?", (game_id,)
        )
        self._conn.commit()
        return cursor.rowcount

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM reports").fetchone()
        return row[0] if row else 0
