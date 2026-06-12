"""Evolution run repo: CRUD for evolution runs and proposals (evolution database)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from storage.shared.database import StorageConnection, StorageRow
from storage.shared.interfaces import EvolutionRunData, SkillProposalData, storage_timestamp

_log = logging.getLogger(__name__)
_VALID_COLUMN_RE = re.compile(r"^[a-z_]+$")


class ConcurrencyError(Exception):
    """Raised when an optimistic locking check fails."""


class EvolutionStore:
    def __init__(self, conn: StorageConnection) -> None:
        self._conn = conn

    def save_run(self, run: EvolutionRunData) -> None:
        now = storage_timestamp()
        started_at = run.started_at or _runtime_state_timestamp(run.runtime_state, "started_at") or now
        finished_at = run.finished_at or _runtime_state_timestamp(run.runtime_state, "finished_at")
        self._conn.execute(
            "INSERT INTO evolution_runs "
            "(id, role, parent_hash, status, training_games, battle_games, "
            "config, candidate_hash, battle_result, runtime_state, errors, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "role = excluded.role, "
            "parent_hash = excluded.parent_hash, "
            "status = excluded.status, "
            "training_games = excluded.training_games, "
            "battle_games = excluded.battle_games, "
            "config = excluded.config, "
            "candidate_hash = excluded.candidate_hash, "
            "battle_result = excluded.battle_result, "
            "runtime_state = excluded.runtime_state, "
            "errors = excluded.errors, "
            "started_at = COALESCE(evolution_runs.started_at, excluded.started_at), "
            "finished_at = COALESCE(excluded.finished_at, evolution_runs.finished_at), "
            "optimistic_version = evolution_runs.optimistic_version + 1",
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
                json.dumps(run.runtime_state, ensure_ascii=False) if run.runtime_state else None,
                json.dumps(run.errors, ensure_ascii=False),
                started_at,
                finished_at,
            ),
        )
        self._conn.commit()

    def update_run(self, run_id: str, *, expected_version: int | None = None, **fields: Any) -> None:
        allowed = {
            "status",
            "training_games",
            "battle_games",
            "candidate_hash",
            "battle_result",
            "runtime_state",
            "errors",
            "finished_at",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return

        set_parts = []
        params: list[Any] = []
        for key, value in updates.items():
            if not _VALID_COLUMN_RE.match(key):
                raise ValueError(f"invalid column name: {key}")
            if key in ("battle_result", "runtime_state", "errors") and value is not None:
                value = json.dumps(value, ensure_ascii=False)
            set_parts.append(f"{key} = ?")
            params.append(value)

        set_parts.append("optimistic_version = optimistic_version + 1")
        params.append(run_id)

        if expected_version is not None:
            params.append(expected_version)
            cursor = self._conn.execute(
                f"UPDATE evolution_runs SET {', '.join(set_parts)} "
                "WHERE id = ? AND optimistic_version = ?",
                params,
            )
            if cursor.rowcount == 0:
                raise ConcurrencyError(
                    f"evolution run {run_id} was modified concurrently "
                    f"(expected version {expected_version})"
                )
        else:
            self._conn.execute(
                f"UPDATE evolution_runs SET {', '.join(set_parts)} WHERE id = ?",
                params,
            )
        self._conn.commit()

    def save_runtime_state(
        self,
        run_id: str,
        *,
        role: str,
        parent_hash: str,
        status: str,
        training_games: int = 0,
        battle_games: int = 0,
        baseline_config: Any = None,
        candidate_hash: str | None = None,
        battle_result: dict[str, Any] | None = None,
        errors: list[str] | None = None,
        runtime_state: dict[str, Any] | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        self.save_run(
            EvolutionRunData(
                run_id=run_id,
                role=role,
                parent_hash=parent_hash,
                status=status,
                training_games=training_games,
                battle_games=battle_games,
                baseline_config=baseline_config,
                candidate_hash=candidate_hash,
                battle_result=battle_result,
                errors=list(errors or []),
                runtime_state=runtime_state,
                started_at=started_at,
                finished_at=finished_at,
            )
        )

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

    def list_runtime_states(
        self,
        *,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT runtime_state FROM evolution_runs "
            "WHERE runtime_state IS NOT NULL "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        states: list[dict[str, Any]] = []
        for row in rows:
            value = _json_value(row["runtime_state"])
            if isinstance(value, dict):
                states.append(value)
        return states

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
                value = _json_value(row["battle_result"])
            except (TypeError, json.JSONDecodeError) as exc:
                _log.warning("list_battle_summaries: skipping corrupted battle_result: %s", exc)
                continue
            if isinstance(value, dict):
                summaries.append(value)
        return summaries

    def save_trust_bundle(self, bundle: dict[str, Any]) -> dict[str, Any]:
        """Persist the trust bundle as a first-class audit artifact."""
        if not isinstance(bundle, dict):
            raise TypeError("trust bundle must be a dict")
        run_id = str(bundle.get("run_id") or "").strip()
        if not run_id:
            raise ValueError("trust bundle requires run_id")
        row = _trust_bundle_row_from_bundle(bundle)
        now = storage_timestamp()
        self._conn.execute(
            "INSERT INTO trust_bundles "
            "(id, run_id, role, baseline_version, candidate_version, bundle_hash, "
            "gate_report_id, attribution_report_id, bundle_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET "
            "id = excluded.id, "
            "role = excluded.role, "
            "baseline_version = excluded.baseline_version, "
            "candidate_version = excluded.candidate_version, "
            "bundle_hash = excluded.bundle_hash, "
            "gate_report_id = excluded.gate_report_id, "
            "attribution_report_id = excluded.attribution_report_id, "
            "bundle_json = excluded.bundle_json, "
            "updated_at = excluded.updated_at",
            (
                row["id"],
                row["run_id"],
                row["role"],
                row["baseline_version"],
                row["candidate_version"],
                row["bundle_hash"],
                row["gate_report_id"],
                row["attribution_report_id"],
                json.dumps(row["bundle_json"], ensure_ascii=False),
                now,
                now,
            ),
        )
        self._conn.commit()
        return row

    def get_trust_bundle(self, run_id_or_bundle_id: str) -> dict[str, Any] | None:
        """Return one trust bundle audit row by run id or trust bundle id."""
        lookup = str(run_id_or_bundle_id or "").strip()
        if not lookup:
            return None
        row = self._conn.execute(
            "SELECT * FROM trust_bundles WHERE run_id = ? OR id = ? LIMIT 1",
            (lookup, lookup),
        ).fetchone()
        if row is None:
            return None
        return _trust_bundle_row_to_payload(row)

    def list_trust_bundles(
        self,
        *,
        role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List trust bundle audit rows, newest first."""
        conditions: list[str] = []
        params: list[Any] = []
        if role:
            conditions.append("role = ?")
            params.append(role)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM trust_bundles{where} ORDER BY updated_at DESC LIMIT ?",
            params,
        ).fetchall()
        return [_trust_bundle_row_to_payload(row) for row in rows]

    def save_proposals(
        self,
        proposals: list[SkillProposalData],
        source_version_id: str,
        run_id: str | None = None,
    ) -> None:
        now = storage_timestamp()
        with self._conn:
            for proposal in proposals:
                self._conn.execute(
                    "INSERT INTO skill_proposals "
                    "(id, source_version_id, target_file, action_type, content, rationale, "
                    "confidence, risk, expected_metric, expected_direction, evidence, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(id) DO UPDATE SET "
                    "source_version_id = excluded.source_version_id, "
                    "target_file = excluded.target_file, "
                    "action_type = excluded.action_type, "
                    "content = excluded.content, "
                    "rationale = excluded.rationale, "
                    "confidence = excluded.confidence, "
                    "risk = excluded.risk, "
                    "expected_metric = excluded.expected_metric, "
                    "expected_direction = excluded.expected_direction, "
                    "evidence = excluded.evidence, "
                    "status = excluded.status, "
                    "created_at = excluded.created_at",
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

    def _row_to_run(self, row: StorageRow) -> EvolutionRunData:
        config_raw = _json_value(row["config"]) if row["config"] else None
        battle_raw = _json_value(row["battle_result"]) if row["battle_result"] else None
        errors_raw = _json_value(row["errors"]) if row["errors"] else []
        runtime_raw = _json_value(row["runtime_state"]) if _has_key(row, "runtime_state") and row["runtime_state"] else None

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
            runtime_state=runtime_raw if isinstance(runtime_raw, dict) else None,
            started_at=row["started_at"],
            finished_at=row["finished_at"],
        )

def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _trust_bundle_row_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    payload = dict(bundle)
    bundle_hash = str(payload.get("bundle_hash") or "").strip()
    if not bundle_hash:
        payload_for_hash = {
            key: value
            for key, value in payload.items()
            if key not in {"trust_bundle_id", "bundle_hash", "completeness"}
        }
        bundle_hash = _sha256_json(payload_for_hash)
        payload["bundle_hash"] = bundle_hash
    run_id = str(payload.get("run_id") or "").strip()
    bundle_id = str(payload.get("trust_bundle_id") or "").strip()
    if not bundle_id:
        bundle_id = f"trust_bundle_{run_id}_{bundle_hash[:12]}" if run_id else f"trust_bundle_{bundle_hash[:12]}"
        payload["trust_bundle_id"] = bundle_id
    return {
        "id": bundle_id,
        "run_id": run_id,
        "role": str(payload.get("role") or ""),
        "baseline_version": payload.get("baseline_version"),
        "candidate_version": payload.get("candidate_version"),
        "bundle_hash": bundle_hash,
        "gate_report_id": payload.get("gate_report_id"),
        "attribution_report_id": payload.get("attribution_report_id"),
        "bundle_json": payload,
    }


def _trust_bundle_row_to_payload(row: StorageRow) -> dict[str, Any]:
    bundle = _json_value(row["bundle_json"])
    if not isinstance(bundle, dict):
        bundle = {}
    return {
        "kind": "evolution_trust_bundle",
        "schema_version": 1,
        "trust_bundle_id": str(row["id"]),
        "run_id": str(row["run_id"]),
        "role": row["role"],
        "baseline_version": row["baseline_version"],
        "candidate_version": row["candidate_version"],
        "bundle_hash": row["bundle_hash"],
        "gate_report_id": row["gate_report_id"],
        "attribution_report_id": row["attribution_report_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "trust_bundle": bundle,
    }


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _runtime_state_timestamp(runtime_state: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(runtime_state, dict):
        return None
    value = runtime_state.get(key)
    return str(value) if value else None


def _has_key(row: StorageRow, key: str) -> bool:
    try:
        return key in set(row.keys())
    except Exception:
        return False
