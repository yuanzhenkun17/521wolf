"""Evolution run repo: CRUD for evolution runs and proposals (evolution database)."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from storage.shared.interfaces import EvolutionRunData, SkillProposalData, storage_timestamp


class EvolutionStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_run(self, run: EvolutionRunData) -> None:
        now = storage_timestamp()
        self._conn.execute(
            "INSERT OR REPLACE INTO evolution_runs "
            "(id, role, parent_hash, status, training_games, battle_games, "
            "config, candidate_hash, battle_result, errors, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.run_id,
                run.role,
                run.parent_hash,
                run.status,
                run.training_games,
                run.battle_games,
                json.dumps(run.baseline_config.to_dict(), ensure_ascii=False)
                if run.baseline_config else None,
                run.candidate_hash,
                json.dumps(run.battle_result, ensure_ascii=False) if run.battle_result else None,
                json.dumps(run.errors, ensure_ascii=False),
                now,
                None,
            ),
        )
        self._conn.commit()

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "training_games",
            "battle_games",
            "candidate_hash",
            "battle_result",
            "errors",
            "finished_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return

        set_parts = []
        params: list[Any] = []
        for key, value in updates.items():
            if key in ("battle_result", "errors") and value is not None:
                value = json.dumps(value, ensure_ascii=False)
            set_parts.append(f"{key} = ?")
            params.append(value)

        params.append(run_id)
        self._conn.execute(
            f"UPDATE evolution_runs SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> EvolutionRunData | None:
        row = self._conn.execute(
            "SELECT * FROM evolution_runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def list_runs(
        self,
        role: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[EvolutionRunData]:
        conditions: list[str] = []
        params: list[Any] = []

        if role:
            conditions.append("role = ?")
            params.append(role)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT * FROM evolution_runs{where} ORDER BY started_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def list_battle_summaries(
        self,
        role: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        conditions = ["battle_result IS NOT NULL"]
        params: list[Any] = []

        if role:
            conditions.append("role = ?")
            params.append(role)

        params.append(limit)
        rows = self._conn.execute(
            "SELECT battle_result FROM evolution_runs "
            f"WHERE {' AND '.join(conditions)} "
            "ORDER BY started_at DESC LIMIT ?",
            params,
        ).fetchall()

        summaries: list[dict[str, Any]] = []
        for row in rows:
            try:
                value = json.loads(row["battle_result"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                summaries.append(value)
        return summaries

    def save_proposals(
        self,
        proposals: list[SkillProposalData],
        source_version_id: str,
        run_id: str | None = None,
    ) -> None:
        now = storage_timestamp()
        for proposal in proposals:
            self._conn.execute(
                "INSERT OR REPLACE INTO skill_proposals "
                "(id, source_version_id, target_file, action_type, content, rationale, "
                "confidence, risk, expected_metric, expected_direction, evidence, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    proposal.proposal_id,
                    source_version_id,
                    proposal.target_file,
                    proposal.action_type,
                    proposal.content,
                    proposal.rationale,
                    proposal.confidence,
                    proposal.risk,
                    proposal.expected_metric,
                    proposal.expected_direction,
                    json.dumps([e.to_dict() for e in proposal.evidence], ensure_ascii=False),
                    proposal.status,
                    now,
                ),
            )
        self._conn.commit()

    def list_proposals(
        self,
        source_version_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        params: list[Any] = []

        if source_version_id:
            conditions.append("source_version_id = ?")
            params.append(source_version_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        rows = self._conn.execute(
            f"SELECT * FROM skill_proposals{where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def _row_to_run(self, row: sqlite3.Row) -> EvolutionRunData:
        config_raw = json.loads(row["config"]) if row["config"] else None
        battle_raw = json.loads(row["battle_result"]) if row["battle_result"] else None
        errors_raw = json.loads(row["errors"]) if row["errors"] else []

        from storage.shared.interfaces import SkillVersionConfigData

        baseline_config = None
        if config_raw is not None:
            baseline_config = SkillVersionConfigData.from_dict(config_raw)

        return EvolutionRunData(
            run_id=row["id"],
            role=row["role"],
            parent_hash=row["parent_hash"],
            status=row["status"],
            training_games=row["training_games"],
            battle_games=row["battle_games"],
            baseline_config=baseline_config,
            candidate_hash=row["candidate_hash"],
            battle_result=battle_raw,
            errors=errors_raw,
        )
