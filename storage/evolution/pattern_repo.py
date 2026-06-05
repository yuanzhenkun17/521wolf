"""Pattern repo: CRUD and lifecycle queries for learned patterns (evolution database)."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from storage.shared.interfaces import storage_timestamp, TimestampProvider

_log = logging.getLogger(__name__)


class PatternStore:
    """Store and query tactical patterns discovered from game analysis."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_pattern(
        self,
        pattern_id: str,
        role: str,
        situation: str,
        recommendation: str,
        *,
        win_rate_with: float = 0.5,
        win_rate_without: float = 0.5,
        sample_size: int = 0,
        confidence: float = 0.1,
        alpha: float = 1.0,
        beta: float = 1.0,
        status: str = "candidate",
        source_games: list[str] | None = None,
        version_id: str | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> str:
        now = created_at or self._timestamp()
        upd = updated_at or now
        self._conn.execute(
            "INSERT OR REPLACE INTO patterns "
            "(pattern_id, role, situation, recommendation, win_rate_with, win_rate_without, "
            "sample_size, confidence, alpha, beta, status, source_games, version_id, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pattern_id,
                role,
                situation,
                recommendation,
                win_rate_with,
                win_rate_without,
                sample_size,
                confidence,
                alpha,
                beta,
                status,
                json.dumps(source_games or [], ensure_ascii=False),
                version_id,
                now,
                upd,
            ),
        )
        self._conn.commit()
        return pattern_id

    def update_pattern(
        self,
        pattern_id: str,
        **fields: Any,
    ) -> None:
        allowed = {
            "win_rate_with",
            "win_rate_without",
            "sample_size",
            "confidence",
            "alpha",
            "beta",
            "status",
            "source_games",
            "version_id",
            "recommendation",
            "situation",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return

        set_parts: list[str] = []
        params: list[Any] = []
        for key, value in updates.items():
            if key == "source_games" and value is not None:
                value = json.dumps(value, ensure_ascii=False)
            set_parts.append(f"{key} = ?")
            params.append(value)

        set_parts.append("updated_at = ?")
        params.append(self._timestamp())
        params.append(pattern_id)

        self._conn.execute(
            f"UPDATE patterns SET {', '.join(set_parts)} WHERE pattern_id = ?",
            params,
        )
        self._conn.commit()

    def get_pattern(self, pattern_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM patterns WHERE pattern_id = ?", (pattern_id,)
        ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def list_patterns(
        self,
        *,
        role: str | None = None,
        status: str | None = None,
        min_confidence: float | None = None,
        min_sample_size: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if role:
            conditions.append("role = ?")
            params.append(role)
        if status:
            conditions.append("status = ?")
            params.append(status)
        if min_confidence is not None:
            conditions.append("confidence >= ?")
            params.append(min_confidence)
        if min_sample_size is not None:
            conditions.append("sample_size >= ?")
            params.append(min_sample_size)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM patterns{where} ORDER BY confidence DESC, updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def get_for_role(self, role: str, *, status: str | None = None) -> list[dict[str, Any]]:
        """Return all patterns for a role, optionally filtered by status."""
        conditions: list[str] = ["role = ?"]
        params: list[Any] = [role]
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT * FROM patterns WHERE {where} ORDER BY confidence DESC",
            params,
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def promote_pattern(self, pattern_id: str, version_id: str | None = None) -> bool:
        """Promote a candidate pattern to 'active' status."""
        now = self._timestamp()
        params: list[Any] = ["active", now]
        if version_id:
            params.append(version_id)
        params.append(pattern_id)

        sql = "UPDATE patterns SET status = ?, updated_at = ?"
        if version_id:
            sql += ", version_id = ?"
        sql += " WHERE pattern_id = ?"

        cursor = self._conn.execute(sql, params)
        self._conn.commit()
        return cursor.rowcount > 0

    def retire_pattern(self, pattern_id: str) -> bool:
        """Retire a pattern by setting status to 'retired'."""
        now = self._timestamp()
        cursor = self._conn.execute(
            "UPDATE patterns SET status = ?, updated_at = ? WHERE pattern_id = ?",
            ("retired", now, pattern_id),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def count_by_role(self, role: str | None = None) -> dict[str, int]:
        if role:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM patterns WHERE role = ? GROUP BY status",
                (role,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS cnt FROM patterns GROUP BY status"
            ).fetchall()
        return {row["status"]: row["cnt"] for row in rows}

    def delete_pattern(self, pattern_id: str) -> int:
        cursor = self._conn.execute(
            "DELETE FROM patterns WHERE pattern_id = ?", (pattern_id,)
        )
        self._conn.commit()
        return cursor.rowcount


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["source_games"] = _load_json(data.get("source_games"), [])
    data.setdefault("alpha", 1.0)
    data.setdefault("beta", 1.0)
    return data


def _load_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
