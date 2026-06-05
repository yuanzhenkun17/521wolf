"""Game repo: CRUD operations for games and players (battle database)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from engine.models import Role, Team


def _role_team(role_str: str) -> str:
    try:
        return Role(role_str).team.value
    except ValueError:
        return Team.VILLAGERS.value


class GameStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_game(
        self,
        game_id: str,
        seed: int,
        config: dict[str, Any] | None = None,
        winner: str | None = None,
        started_at: str = "",
        finished_at: str | None = None,
        total_rounds: int = 0,
        public_events: list[dict] | None = None,
        final_state: dict | None = None,
    ) -> str:
        self._conn.execute(
            "INSERT OR REPLACE INTO games "
            "(id, seed, config, winner, started_at, finished_at, total_rounds, public_events, final_state) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                game_id,
                seed,
                json.dumps(config, ensure_ascii=False) if config else None,
                winner,
                started_at,
                finished_at,
                total_rounds,
                json.dumps(public_events, ensure_ascii=False) if public_events else None,
                json.dumps(final_state, ensure_ascii=False) if final_state else None,
            ),
        )
        self._conn.commit()
        return game_id

    def insert_players(
        self,
        game_id: str,
        player_roles: dict[int, str],
        final_alive: dict[int, bool] | None = None,
        deaths: list[dict] | None = None,
    ) -> None:
        death_lookup: dict[int, dict] = {}
        if deaths:
            for death in deaths:
                seat = death.get("player_id")
                if seat is not None:
                    death_lookup[int(seat)] = death

        for seat_raw, role_str in player_roles.items():
            seat = int(seat_raw)
            team = _role_team(role_str)
            alive = 1
            killed_day = None
            killed_cause = None

            if seat in death_lookup:
                alive = 0
                killed_day = death_lookup[seat].get("day")
                killed_cause = death_lookup[seat].get("cause")
            elif final_alive is not None and seat in final_alive:
                alive = 1 if final_alive[seat] else 0

            self._conn.execute(
                "INSERT OR IGNORE INTO players "
                "(game_id, seat, role, team, alive, killed_day, killed_cause) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (game_id, seat, role_str, team, alive, killed_day, killed_cause),
            )
        self._conn.commit()

    def get_game(self, game_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def list_games(
        self,
        role: str | None = None,
        winner: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = "SELECT g.* FROM games g"
        params: list[Any] = []
        conditions: list[str] = []

        if role:
            query += " JOIN players p ON p.game_id = g.id"
            conditions.append("p.role = ?")
            params.append(role)
        if winner:
            conditions.append("g.winner = ?")
            params.append(winner)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY g.started_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def count_games(self, role: str | None = None) -> int:
        if role:
            row = self._conn.execute(
                "SELECT COUNT(DISTINCT g.id) FROM games g "
                "JOIN players p ON p.game_id = g.id WHERE p.role = ?",
                (role,),
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM games").fetchone()
        return row[0] if row else 0
