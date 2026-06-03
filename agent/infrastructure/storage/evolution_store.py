"""Evolution store — CRUD for evolution runs, proposals, and leaderboard."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from agent.common import beijing_now_iso
from agent.learning.evolution.models import (
    EvolutionRun,
    SkillConsolidation,
    SkillProposal,
)


class EvolutionStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def save_run(self, run: EvolutionRun) -> None:
        """Insert or update an evolution run."""
        now = beijing_now_iso()
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
        """Update specific fields of an evolution run."""
        allowed = {
            "status", "training_games", "battle_games",
            "candidate_hash", "battle_result", "errors", "finished_at",
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return

        set_parts = []
        params: list[Any] = []
        for k, v in updates.items():
            if k in ("battle_result", "errors") and v is not None:
                v = json.dumps(v, ensure_ascii=False)
            set_parts.append(f"{k} = ?")
            params.append(v)

        params.append(run_id)
        self._conn.execute(
            f"UPDATE evolution_runs SET {', '.join(set_parts)} WHERE id = ?",
            params,
        )
        self._conn.commit()

    def get_run(self, run_id: str) -> EvolutionRun | None:
        """Load an evolution run by ID."""
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
    ) -> list[EvolutionRun]:
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
        return [self._row_to_run(r) for r in rows]

    def save_proposals(
        self,
        proposals: list[SkillProposal],
        source_version_id: str,
        run_id: str | None = None,
    ) -> None:
        """Insert skill proposals linked to a source version."""
        now = beijing_now_iso()
        for p in proposals:
            self._conn.execute(
                "INSERT OR REPLACE INTO skill_proposals "
                "(id, source_version_id, target_file, action_type, content, rationale, "
                "confidence, risk, expected_metric, expected_direction, evidence, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    p.proposal_id,
                    source_version_id,
                    p.target_file,
                    p.action_type,
                    p.content,
                    p.rationale,
                    p.confidence,
                    p.risk,
                    p.expected_metric,
                    p.expected_direction,
                    json.dumps([e.to_dict() for e in p.evidence], ensure_ascii=False),
                    p.status,
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
        return [dict(r) for r in rows]

    def _row_to_run(self, row: sqlite3.Row) -> EvolutionRun:
        """Convert a DB row to an EvolutionRun dataclass."""
        config_raw = json.loads(row["config"]) if row["config"] else None
        battle_raw = json.loads(row["battle_result"]) if row["battle_result"] else None
        errors_raw = json.loads(row["errors"]) if row["errors"] else []

        from agent.learning.evolution.models import SkillVersionConfig

        baseline_config = None
        if config_raw is not None:
            baseline_config = SkillVersionConfig(
                name=config_raw.get("name", ""),
                created_at=config_raw.get("created_at", ""),
                role_versions=config_raw.get("role_versions", {}),
                notes=config_raw.get("notes", []),
            )

        return EvolutionRun(
            run_id=row["id"],
            role=row["role"],
            parent_hash=row["parent_hash"],
            status=row["status"],
            training_games=row["training_games"],
            battle_games=row["battle_games"],
            baseline_config=baseline_config,
            training_run_id=None,
            training_output_dir=None,
            candidate_hash=row["candidate_hash"],
            battle_result=battle_raw,
            errors=errors_raw,
        )
