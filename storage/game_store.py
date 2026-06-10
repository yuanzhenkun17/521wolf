"""Game store: CRUD operations for games and players."""

from __future__ import annotations

import json
from typing import Any

from engine.models import Role, Team
from storage.interfaces import storage_timestamp
from storage.public_events import public_events_only
from storage.shared.database import StorageConnection

WOLF_GAME_CHILD_TABLES = (
    "decision_reviews",
    "counterfactuals",
    "llm_judgments",
    "evaluations",
    "reports",
    "decisions",
    "game_events",
    "players",
)


def _role_team(role_str: str) -> str:
    try:
        return Role(role_str).team.value
    except ValueError:
        return Team.VILLAGERS.value


class GameStore:
    def __init__(self, conn: StorageConnection, *, autocommit: bool = True) -> None:
        self._conn = conn
        self._autocommit = autocommit

    def _commit(self) -> None:
        if self._autocommit:
            self._conn.commit()

    def _rollback(self) -> None:
        if self._autocommit:
            self._conn.rollback()

    def _begin_write(self) -> None:
        if not self._autocommit:
            return
        begin = getattr(self._conn, "begin_write", None)
        if callable(begin):
            begin()

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
        # Run policy fields
        run_type: str | None = None,
        mode: str | None = None,
        learning_eligible: int | None = None,
        leaderboard_scope: str | None = None,
        promote_eligible: int | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        ruleset_version: str | None = None,
        run_metadata: dict[str, Any] | None = None,
    ) -> str:
        safe_public_events = public_events_only(public_events)
        safe_started_at = started_at or storage_timestamp()
        safe_finished_at = finished_at or None
        self._conn.execute(
            "INSERT INTO games "
            "(id, seed, config, winner, started_at, finished_at, total_rounds, "
            "public_events, final_state, "
            "run_type, mode, learning_eligible, leaderboard_scope, promote_eligible, "
            "model_id, model_config_hash, ruleset_version) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "seed = excluded.seed, "
            "config = excluded.config, "
            "winner = excluded.winner, "
            "started_at = excluded.started_at, "
            "finished_at = excluded.finished_at, "
            "total_rounds = excluded.total_rounds, "
            "public_events = excluded.public_events, "
            "final_state = excluded.final_state, "
            "run_type = excluded.run_type, "
            "mode = excluded.mode, "
            "learning_eligible = excluded.learning_eligible, "
            "leaderboard_scope = excluded.leaderboard_scope, "
            "promote_eligible = excluded.promote_eligible, "
            "model_id = excluded.model_id, "
            "model_config_hash = excluded.model_config_hash, "
            "ruleset_version = excluded.ruleset_version",
            (
                game_id,
                seed,
                json.dumps(config, ensure_ascii=False) if config else None,
                winner,
                safe_started_at,
                safe_finished_at,
                total_rounds,
                json.dumps(safe_public_events, ensure_ascii=False) if safe_public_events else None,
                json.dumps(final_state, ensure_ascii=False) if final_state else None,
                run_type or "ordinary_game",
                mode or "dev",
                learning_eligible if learning_eligible is not None else 0,
                leaderboard_scope or "demo",
                promote_eligible if promote_eligible is not None else 0,
                model_id,
                model_config_hash,
                ruleset_version or "werewolf_12p_v1",
            ),
        )
        # Write additional run_metadata columns if provided
        if run_metadata:
            _run_meta_cols = {
                "source_run_id", "comparison_group_id", "comparison_type",
                "target_role", "target_version_id", "seed_set_id",
                "evaluation_set_id", "paired_seed", "rankable",
            }
            updates = []
            values = []
            for col in _run_meta_cols:
                if col in run_metadata:
                    updates.append(f"{col} = ?")
                    val = run_metadata[col]
                    values.append(1 if val is True else 0 if val is False else val)
            if updates:
                values.append(game_id)
                self._conn.execute(
                    f"UPDATE games SET {', '.join(updates)} WHERE id = ?",
                    values,
                )
        self._commit()
        return game_id

    def insert_players(
        self,
        game_id: str,
        player_roles: dict[int, str],
        final_alive: dict[int, bool] | None = None,
        deaths: list[dict] | None = None,
        role_version_ids: dict[int, str] | None = None,
        skill_package_hashes: dict[int, str] | None = None,
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
                "INSERT INTO players "
                "(game_id, seat, role, team, alive, killed_day, killed_cause, "
                "role_version_id, skill_package_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(game_id, seat) DO UPDATE SET "
                "role = excluded.role, "
                "team = excluded.team, "
                "alive = excluded.alive, "
                "killed_day = excluded.killed_day, "
                "killed_cause = excluded.killed_cause, "
                "role_version_id = excluded.role_version_id, "
                "skill_package_hash = excluded.skill_package_hash",
                (
                    game_id,
                    seat,
                    role_str,
                    team,
                    alive,
                    killed_day,
                    killed_cause,
                    (role_version_ids or {}).get(seat),
                    (skill_package_hashes or {}).get(seat),
                ),
            )
        self._commit()

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

    def delete_game(self, game_id: str) -> None:
        """Delete a game and its wolf-schema child rows."""
        try:
            self._begin_write()
            for table in WOLF_GAME_CHILD_TABLES:
                self._conn.execute(f"DELETE FROM {table} WHERE game_id = ?", (game_id,))
            self._conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
            self._commit()
        except Exception:
            self._rollback()
            raise


def delete_game_from_provider(provider: Any, game_id: str) -> None:
    """Open a wolf connection from a provider and delete one game through storage."""
    import storage.provider as provider_mod

    conn = provider_mod.open_wolf_connection(provider)
    try:
        GameStore(conn).delete_game(game_id)
    finally:
        conn.close()


def delete_game_from_env(game_id: str, *, paths: Any | None = None) -> None:
    """Resolve the configured storage provider and delete one game."""
    import storage.provider as provider_mod

    conn = provider_mod.open_wolf_connection(paths=paths)
    try:
        GameStore(conn).delete_game(game_id)
    finally:
        conn.close()
