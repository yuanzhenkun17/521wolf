"""Storage for evidence-pipeline experience candidates."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from storage.interfaces import storage_timestamp, TimestampProvider


class ExperienceCandidateStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        timestamp_provider: TimestampProvider | None = None,
    ) -> None:
        self._conn = conn
        self._timestamp = timestamp_provider or storage_timestamp

    def save_candidates(
        self,
        game_id: str,
        candidates: list[Any],
        *,
        created_at: str | None = None,
    ) -> list[str]:
        saved: list[str] = []
        now = created_at or self._timestamp()
        for index, candidate in enumerate(candidates, start=1):
            data = _candidate_dict(candidate)
            candidate_id = str(data.get("candidate_id") or f"{game_id}_candidate_{index:03d}")
            data["candidate_id"] = candidate_id
            self._conn.execute(
                "INSERT OR REPLACE INTO experience_candidates "
                "(game_id, candidate_id, role, faction, candidate_type, topic, sample_source, "
                "evidence_decision_ids, scenario, conditions, recommendation, anti_pattern, "
                "risk_boundaries, counter_conditions, supporting_evidence, opposing_evidence, "
                "confidence, validation_need, misleading_risk, raw_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    game_id,
                    candidate_id,
                    str(data.get("role") or ""),
                    str(data.get("faction") or ""),
                    str(data.get("candidate_type") or ""),
                    str(data.get("topic") or ""),
                    str(data.get("sample_source") or ""),
                    _dump(data.get("evidence_decision_ids") or []),
                    str(data.get("scenario") or ""),
                    _dump(data.get("conditions") or []),
                    str(data.get("recommendation") or ""),
                    str(data.get("anti_pattern") or ""),
                    _dump(data.get("risk_boundaries") or []),
                    _dump(data.get("counter_conditions") or []),
                    _dump(data.get("supporting_evidence") or []),
                    _dump(data.get("opposing_evidence") or []),
                    str(data.get("confidence") or "low"),
                    _dump(data.get("validation_need") or {}),
                    str(data.get("misleading_risk") or "medium"),
                    _dump(data),
                    now,
                ),
            )
            saved.append(candidate_id)
        self._conn.commit()
        return saved

    def get_candidate(self, game_id: str, candidate_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM experience_candidates WHERE game_id = ? AND candidate_id = ?",
            (game_id, candidate_id),
        ).fetchone()
        return _row_to_dict(row) if row is not None else None

    def list_candidates(
        self,
        *,
        game_id: str | None = None,
        role: str | None = None,
        candidate_type: str | None = None,
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
        if candidate_type:
            conditions.append("candidate_type = ?")
            params.append(candidate_type)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM experience_candidates{where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def count_by_role(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT role, COUNT(*) AS cnt FROM experience_candidates GROUP BY role"
        ).fetchall()
        return {row["role"]: row["cnt"] for row in rows}

def _candidate_dict(candidate: Any) -> dict[str, Any]:
    if hasattr(candidate, "to_dict"):
        data = candidate.to_dict()
    elif isinstance(candidate, dict):
        data = dict(candidate)
    else:
        raise TypeError(f"Unsupported experience candidate type: {type(candidate)!r}")
    return data

def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)

def _load(value: str | None, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback

def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for field in (
        "evidence_decision_ids",
        "conditions",
        "risk_boundaries",
        "counter_conditions",
        "supporting_evidence",
        "opposing_evidence",
    ):
        data[field] = _load(data.get(field), [])
    data["validation_need"] = _load(data.get("validation_need"), {})
    data["raw_json"] = _load(data.get("raw_json"), {})
    return data