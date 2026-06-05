"""Decision outcome repo: store post-game decision quality assessments (evolution database)."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from storage.shared.interfaces import storage_timestamp, TimestampProvider

_log = logging.getLogger(__name__)


class DecisionOutcomeStore:
    """Store and query decision outcome assessments linked to decisions."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_outcome(
        self,
        decision_id: str,
        game_id: str,
        player_seat: int,
        role: str,
        action_type: str,
        day: int,
        phase: str,
        *,
        quality: str | None = None,
        reason: str | None = None,
        created_at: str | None = None,
    ) -> str:
        now = created_at or self._timestamp()
        self._conn.execute(
            "INSERT OR REPLACE INTO decision_outcomes "
            "(decision_id, game_id, player_seat, role, action_type, day, phase, "
            "quality, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision_id,
                game_id,
                player_seat,
                role,
                action_type,
                day,
                phase,
                quality,
                reason,
                now,
            ),
        )
        self._conn.commit()
        return decision_id

    def save_batch(self, outcomes: list[dict[str, Any]]) -> list[str]:
        """Save multiple decision outcomes in a single transaction."""
        saved: list[str] = []
        now = self._timestamp()
        for out in outcomes:
            did = str(out["decision_id"])
            self._conn.execute(
                "INSERT OR REPLACE INTO decision_outcomes "
                "(decision_id, game_id, player_seat, role, action_type, day, phase, "
                "quality, reason, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    did,
                    str(out["game_id"]),
                    int(out["player_seat"]),
                    str(out["role"]),
                    str(out["action_type"]),
                    int(out["day"]),
                    str(out["phase"]),
                    out.get("quality"),
                    out.get("reason"),
                    str(out.get("created_at") or now),
                ),
            )
            saved.append(did)
        self._conn.commit()
        return saved

    def get_outcome(self, decision_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM decision_outcomes WHERE decision_id = ?", (decision_id,)
        ).fetchone()
        return dict(row) if row is not None else None

    def get_for_game(self, game_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM decision_outcomes WHERE game_id = ? ORDER BY day, player_seat",
            (game_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def query(
        self,
        *,
        game_id: str | None = None,
        role: str | None = None,
        quality: str | None = None,
        action_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if game_id:
            conditions.append("game_id = ?")
            params.append(game_id)
        if role:
            conditions.append("role = ?")
            params.append(role)
        if quality:
            conditions.append("quality = ?")
            params.append(quality)
        if action_type:
            conditions.append("action_type = ?")
            params.append(action_type)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM decision_outcomes{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def quality_distribution(
        self,
        *,
        role: str | None = None,
        game_id: str | None = None,
    ) -> dict[str, int]:
        """Return counts of outcomes grouped by quality label."""
        conditions: list[str] = ["quality IS NOT NULL"]
        params: list[Any] = []

        if role:
            conditions.append("role = ?")
            params.append(role)
        if game_id:
            conditions.append("game_id = ?")
            params.append(game_id)

        where = " AND ".join(conditions)
        rows = self._conn.execute(
            f"SELECT quality, COUNT(*) AS cnt FROM decision_outcomes "
            f"WHERE {where} GROUP BY quality",
            params,
        ).fetchall()
        return {row["quality"]: row["cnt"] for row in rows}

    def delete_for_game(self, game_id: str) -> int:
        cursor = self._conn.execute(
            "DELETE FROM decision_outcomes WHERE game_id = ?", (game_id,)
        )
        self._conn.commit()
        return cursor.rowcount

    def count(self, role: str | None = None) -> int:
        if role:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM decision_outcomes WHERE role = ?", (role,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM decision_outcomes").fetchone()
        return row[0] if row else 0
