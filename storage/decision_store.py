"""Decision store: insert and query agent decision traces."""

from __future__ import annotations

import json
from typing import Any

from storage.decision_order import decision_timeline_order_clause
from storage.ids import public_decision_id, storage_decision_id
from storage.interfaces import DecisionArchiveData, DecisionRecordData
from storage.shared.database import StorageConnection, StorageRow


class DecisionStore:
    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def insert_archive(
        self,
        game_id: str,
        archive: DecisionArchiveData,
        player_id: int | None = None,
        created_at: str = "",
    ) -> str:
        decision_id = storage_decision_id(game_id, archive.decision_id)
        self._conn.execute(
            "INSERT INTO decisions "
            "(id, game_id, player_id, seat, role, day, phase, action_type, "
            "candidates, observation_summary, memory_context, selected_skills, "
            "prompt_messages, raw_output, parsed_decision, final_response, "
            "selected_target, selected_choice, public_text, private_reasoning, "
            "confidence, alternatives, rejected_reasons, source, "
            "policy_adjustments, errors, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "game_id = excluded.game_id, "
            "player_id = excluded.player_id, "
            "seat = excluded.seat, "
            "role = excluded.role, "
            "day = excluded.day, "
            "phase = excluded.phase, "
            "action_type = excluded.action_type, "
            "candidates = excluded.candidates, "
            "observation_summary = excluded.observation_summary, "
            "memory_context = excluded.memory_context, "
            "selected_skills = excluded.selected_skills, "
            "prompt_messages = excluded.prompt_messages, "
            "raw_output = excluded.raw_output, "
            "parsed_decision = excluded.parsed_decision, "
            "final_response = excluded.final_response, "
            "selected_target = excluded.selected_target, "
            "selected_choice = excluded.selected_choice, "
            "public_text = excluded.public_text, "
            "private_reasoning = excluded.private_reasoning, "
            "confidence = excluded.confidence, "
            "alternatives = excluded.alternatives, "
            "rejected_reasons = excluded.rejected_reasons, "
            "source = excluded.source, "
            "policy_adjustments = excluded.policy_adjustments, "
            "errors = excluded.errors, "
            "created_at = excluded.created_at",
            (
                decision_id,
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
        if record.player_id is None:
            raise ValueError("DecisionRecordData.player_id is required for persistence")
        decision_id = storage_decision_id(game_id, record.decision_id)
        action_type = record.action_type.value if hasattr(record.action_type, "value") else record.action_type
        self._conn.execute(
            "INSERT INTO decisions "
            "(id, game_id, player_id, seat, role, day, phase, action_type, "
            "selected_target, selected_choice, public_text, private_reasoning, "
            "confidence, alternatives, rejected_reasons, selected_skills, "
            "raw_output, source, policy_adjustments, errors, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "game_id = excluded.game_id, "
            "player_id = excluded.player_id, "
            "seat = excluded.seat, "
            "role = excluded.role, "
            "day = excluded.day, "
            "phase = excluded.phase, "
            "action_type = excluded.action_type, "
            "selected_target = excluded.selected_target, "
            "selected_choice = excluded.selected_choice, "
            "public_text = excluded.public_text, "
            "private_reasoning = excluded.private_reasoning, "
            "confidence = excluded.confidence, "
            "alternatives = excluded.alternatives, "
            "rejected_reasons = excluded.rejected_reasons, "
            "selected_skills = excluded.selected_skills, "
            "raw_output = excluded.raw_output, "
            "source = excluded.source, "
            "policy_adjustments = excluded.policy_adjustments, "
            "errors = excluded.errors, "
            "created_at = excluded.created_at",
            (
                decision_id,
                game_id,
                record.player_id,
                record.player_id,
                record.role,
                record.day,
                record.phase,
                action_type,
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
        return [_public_decision_row(row) for row in rows]

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
            "SELECT * FROM decisions WHERE game_id = ? "
            f"ORDER BY {decision_timeline_order_clause(self._conn)}",
            (game_id,),
        ).fetchall()
        return [_public_decision_row(row) for row in rows]


def _public_decision_row(row: StorageRow) -> dict[str, Any]:
    data = dict(row)
    game_id = str(data.get("game_id") or "")
    storage_id = str(data.get("id") or "")
    public_id = public_decision_id(storage_id, game_id) if game_id and storage_id else storage_id
    data["storage_id"] = storage_id
    data["id"] = public_id
    data["decision_id"] = public_id
    return data
