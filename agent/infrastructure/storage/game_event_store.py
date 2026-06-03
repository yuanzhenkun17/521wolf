"""Game event store — query and insert engine-level game events."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class GameEventStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get_events(
        self,
        game_id: str,
        day: int | None = None,
        event_type: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = ["game_id = ?"]
        params: list[Any] = [game_id]

        if day is not None:
            conditions.append("day = ?")
            params.append(day)
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        where = " AND ".join(conditions)
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT * FROM game_events WHERE {where} ORDER BY idx LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def count_by_type(self, game_id: str | None = None) -> dict[str, int]:
        if game_id:
            rows = self._conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM game_events "
                "WHERE game_id = ? GROUP BY event_type",
                (game_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM game_events "
                "GROUP BY event_type"
            ).fetchall()
        return {r["event_type"]: r["cnt"] for r in rows}

    def search(self, query: str, game_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        conditions: list[str] = ["message LIKE ?"]
        params: list[Any] = [f"%{query}%"]

        if game_id:
            conditions.append("game_id = ?")
            params.append(game_id)

        where = " AND ".join(conditions)
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT * FROM game_events WHERE {where} ORDER BY idx LIMIT ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
