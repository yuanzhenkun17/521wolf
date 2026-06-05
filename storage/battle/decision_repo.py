"""Decision repo: insert and query agent decision traces (battle database)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from storage.shared.interfaces import DecisionArchiveData, DecisionRecordData


class DecisionStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_archive(
        self,
        game_id: str,
        archive: DecisionArchiveData,
        player_id: int | None = None,
        created_at: str = "",
    ) -> str:
        self._conn.execute(
            "INSERT OR REPLACE INTO decisions "
            "(id, game_id, player_id, seat, role, day, phase, action_type, "
            "candidates, observation_summary, memory_context, selected_skills, "
            "prompt_messages, raw_output, parsed_decision, final_response, "
            "selected_target, selected_choice, public_text, private_reasoning, "
            "confidence, alternatives, rejected_reasons, source, "
            "policy_adjustments, errors, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                archive.decision_id,
                game_id,
                player_id,
                archive.player_id,
                archive.role,
                archive.day,
                archive.phase,
                archive.action_type,
                json.dumps(archive.candidates, ensure_ascii=False),
                json.dumps(archive.observation_summary, ensure_ascii=False),
                json.dumps(archive.memory_context, ensure_ascii=False),
                json.dumps(archive.selected_skills, ensure_ascii=False),
                json.dumps(archive.prompt_messages, ensure_ascii=False),
                archive.raw_output,
                json.dumps(archive.parsed_decision, ensure_ascii=False),
                json.dumps(archive.final_response, ensure_ascii=False),
                archive.parsed_decision.get("target") if archive.parsed_decision else None,
                archive.parsed_decision.get("choice") if archive.parsed_decision else None,
                archive.final_response.get("text", ""),
                "",
                archive.confidence,
                json.dumps([], ensure_ascii=False),
                json.dumps([], ensure_ascii=False),
                archive.source,
                json.dumps(archive.policy_adjustments, ensure_ascii=False),
                json.dumps(archive.errors, ensure_ascii=False),
                created_at,
            ),
        )
        self._conn.commit()
        return archive.decision_id

    def insert_record(
        self,
        game_id: str,
        record: DecisionRecordData,
        created_at: str = "",
    ) -> str:
        self._conn.execute(
            "INSERT OR REPLACE INTO decisions "
            "(id, game_id, seat, role, day, phase, action_type, "
            "selected_target, selected_choice, public_text, private_reasoning, "
            "confidence, alternatives, rejected_reasons, selected_skills, "
            "raw_output, source, policy_adjustments, errors, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                record.decision_id,
                game_id,
                record.player_id or 0,
                record.role,
                record.day,
                record.phase,
                record.action_type,
                record.selected_target,
                record.selected_choice,
                record.public_text,
                record.private_reasoning,
                record.confidence,
                json.dumps(record.alternatives, ensure_ascii=False),
                json.dumps(record.rejected_reasons, ensure_ascii=False),
                json.dumps(record.selected_skills, ensure_ascii=False),
                record.raw_output,
                record.source,
                json.dumps(record.policy_adjustments, ensure_ascii=False),
                json.dumps(record.errors, ensure_ascii=False),
                created_at,
            ),
        )
        self._conn.commit()
        return record.decision_id

    def query(
        self,
        game_id: str | None = None,
        role: str | None = None,
        action_type: str | None = None,
        version_id: str | None = None,
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
        if action_type:
            conditions.append("action_type = ?")
            params.append(action_type)
        if version_id:
            conditions.append("version_id = ?")
            params.append(version_id)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        query = f"SELECT * FROM decisions{where} ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._conn.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def count_by_role(self, role: str) -> dict[str, int]:
        row = self._conn.execute(
            "SELECT COUNT(*) as total, "
            "SUM(CASE WHEN selected_target IS NOT NULL THEN 1 ELSE 0 END) as with_target "
            "FROM decisions WHERE role = ?",
            (role,),
        ).fetchone()
        if row is None:
            return {"total": 0, "with_target": 0}
        return {"total": row["total"], "with_target": row["with_target"] or 0}

    def get_for_game(self, game_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE game_id = ? ORDER BY day, seat",
            (game_id,),
        ).fetchall()
        return [dict(row) for row in rows]
