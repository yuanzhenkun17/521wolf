"""Situational record repo: store game situation snapshots (evolution database)."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any

from storage.shared.interfaces import storage_timestamp, TimestampProvider

_log = logging.getLogger(__name__)


class SituationalRecordStore:
    """Store and query situational records captured during games."""

    def __init__(
        self,
        conn: sqlite3.Connection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_record(
        self,
        record_id: str,
        game_id: str,
        role: str,
        seat: int,
        *,
        day: int | None = None,
        phase: str | None = None,
        alive_players: list[int] | dict[str, Any] | None = None,
        key_events: list[dict[str, Any]] | None = None,
        outcome: str | dict[str, Any] | None = None,
        created_at: str | None = None,
    ) -> str:
        now = created_at or self._timestamp()
        self._conn.execute(
            "INSERT OR REPLACE INTO situational_records "
            "(id, game_id, role, seat, day, phase, alive_players, key_events, outcome, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record_id,
                game_id,
                role,
                seat,
                day,
                phase,
                json.dumps(alive_players, ensure_ascii=False) if alive_players is not None else None,
                json.dumps(key_events, ensure_ascii=False) if key_events is not None else None,
                json.dumps(outcome, ensure_ascii=False) if isinstance(outcome, (dict, list)) else outcome,
                now,
            ),
        )
        self._conn.commit()
        return record_id

    def save_batch(self, records: list[dict[str, Any]]) -> list[str]:
        """Save multiple situational records in a single transaction."""
        saved: list[str] = []
        now = self._timestamp()
        for rec in records:
            rid = str(rec["id"])
            alive = rec.get("alive_players")
            events = rec.get("key_events")
            outcome = rec.get("outcome")
            self._conn.execute(
                "INSERT OR REPLACE INTO situational_records "
                "(id, game_id, role, seat, day, phase, alive_players, key_events, outcome, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rid,
                    str(rec["game_id"]),
                    str(rec["role"]),
                    int(rec["seat"]),
                    rec.get("day"),
                    rec.get("phase"),
                    json.dumps(alive, ensure_ascii=False) if alive is not None else None,
                    json.dumps(events, ensure_ascii=False) if events is not None else None,
                    json.dumps(outcome, ensure_ascii=False) if isinstance(outcome, (dict, list)) else outcome,
                    str(rec.get("created_at") or now),
                ),
            )
            saved.append(rid)
        self._conn.commit()
        return saved

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM situational_records WHERE id = ?", (record_id,)
        ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def get_for_game(self, game_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM situational_records WHERE game_id = ? ORDER BY day, seat",
            (game_id,),
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def query(
        self,
        *,
        game_id: str | None = None,
        role: str | None = None,
        day: int | None = None,
        phase: str | None = None,
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
        if day is not None:
            conditions.append("day = ?")
            params.append(day)
        if phase:
            conditions.append("phase = ?")
            params.append(phase)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM situational_records{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def delete_for_game(self, game_id: str) -> int:
        cursor = self._conn.execute(
            "DELETE FROM situational_records WHERE game_id = ?", (game_id,)
        )
        self._conn.commit()
        return cursor.rowcount

    def count(self, role: str | None = None) -> int:
        if role:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM situational_records WHERE role = ?", (role,)
            ).fetchone()
        else:
            row = self._conn.execute("SELECT COUNT(*) FROM situational_records").fetchone()
        return row[0] if row else 0


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for field_name in ("alive_players", "key_events", "outcome"):
        raw = data.get(field_name)
        if raw and isinstance(raw, str):
            try:
                data[field_name] = json.loads(raw)
            except json.JSONDecodeError:
                pass
    return data
