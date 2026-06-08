"""Leaderboard repo: CRUD for the battle leaderboard (battle database)."""

from __future__ import annotations

import logging
from typing import Any

from storage.shared.database import StorageConnection
from storage.shared.interfaces import storage_timestamp, TimestampProvider

_log = logging.getLogger(__name__)


class BattleLeaderboardStore:
    """Store and query the per-role, per-version leaderboard."""

    def __init__(
        self,
        conn: StorageConnection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def upsert_entry(
        self,
        role: str,
        version_id: str,
        *,
        games_played: int = 0,
        wins: int = 0,
        win_rate: float = 0.0,
        avg_speech_score: float = 0.0,
        avg_vote_score: float = 0.0,
        avg_skill_score: float = 0.0,
        avg_information_score: float = 0.0,
        avg_cooperation_score: float = 0.0,
        updated_at: str | None = None,
    ) -> None:
        now = updated_at or self._timestamp()
        self._conn.execute(
            "INSERT INTO leaderboard "
            "(role, version_id, games_played, wins, win_rate, "
            "avg_speech_score, avg_vote_score, avg_skill_score, "
            "avg_information_score, avg_cooperation_score, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(role, version_id) DO UPDATE SET "
            "games_played = excluded.games_played, "
            "wins = excluded.wins, "
            "win_rate = excluded.win_rate, "
            "avg_speech_score = excluded.avg_speech_score, "
            "avg_vote_score = excluded.avg_vote_score, "
            "avg_skill_score = excluded.avg_skill_score, "
            "avg_information_score = excluded.avg_information_score, "
            "avg_cooperation_score = excluded.avg_cooperation_score, "
            "updated_at = excluded.updated_at",
            (
                role,
                version_id,
                games_played,
                wins,
                win_rate,
                avg_speech_score,
                avg_vote_score,
                avg_skill_score,
                avg_information_score,
                avg_cooperation_score,
                now,
            ),
        )
        self._conn.commit()

    def get_entry(self, role: str, version_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM leaderboard WHERE role = ? AND version_id = ?",
            (role, version_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_entries(
        self,
        *,
        role: str | None = None,
        version_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if role:
            conditions.append("role = ?")
            params.append(role)
        if version_id:
            conditions.append("version_id = ?")
            params.append(version_id)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM leaderboard{where} "
            "ORDER BY updated_at DESC, role ASC, version_id ASC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def top_by_win_rate(self, role: str, limit: int = 10) -> list[dict[str, Any]]:
        """Return top versions for a role sorted by win rate descending."""
        rows = self._conn.execute(
            "SELECT * FROM leaderboard WHERE role = ? "
            "ORDER BY win_rate DESC, games_played DESC LIMIT ?",
            (role, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_entry(self, role: str, version_id: str) -> int:
        cursor = self._conn.execute(
            "DELETE FROM leaderboard WHERE role = ? AND version_id = ?",
            (role, version_id),
        )
        self._conn.commit()
        return cursor.rowcount

    def count_entries(self, role: str | None = None) -> int:
        if role:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM leaderboard WHERE role = ?", (role,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM leaderboard").fetchone()
        return row[0] if row else 0
