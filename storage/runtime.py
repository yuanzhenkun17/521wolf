"""Runtime persistence session for one game.

This module owns the bridge between raw artifacts (JSONL/archive files) and
SQLite indexes. Engine and agent runtime code should receive loggers/recorders
from here instead of constructing SQLite storage objects directly.
"""

from __future__ import annotations

import logging
import sqlite3
import json
from pathlib import Path
from typing import Any, Protocol

from storage.interfaces import DecisionRecordData, storage_timestamp
from storage.run_policy import RunPolicy, RunType

from storage.game_store import GameStore
from storage.ids import storage_decision_id
from storage.schema import get_connection

DEFAULT_COMMIT_EVERY = 25


class EventEntry(Protocol):
    """Protocol describing the fields storage needs from a game log entry."""

    index: int
    day: int
    phase: Any
    type: str
    message: str
    actor: int | None
    target: int | None
    payload: dict[str, Any]
    public: bool


def open_storage_connection(db_path: Path | str) -> sqlite3.Connection:
    return get_connection(Path(db_path))


class SQLiteEventSink:
    def __init__(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        batch_committer: "BatchCommitter | None" = None,
        *,
        commit_every: int = DEFAULT_COMMIT_EVERY,
    ) -> None:
        self._conn = conn
        self._game_id = game_id
        self._batch_committer = batch_committer or BatchCommitter(conn, commit_every=commit_every)

    def record_event(self, entry: EventEntry) -> None:
        phase_val = entry.phase.value if hasattr(entry.phase, "value") else entry.phase
        self._conn.execute(
            "INSERT INTO game_events "
            "(game_id, idx, day, phase, event_type, message, public, actor, target, payload, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                self._game_id,
                entry.index,
                entry.day,
                phase_val,
                entry.type,
                entry.message,
                1 if entry.public else 0,
                entry.actor,
                entry.target,
                json.dumps(entry.payload, ensure_ascii=False),
                storage_timestamp(),
            ),
        )
        self._batch_committer.mark_write()

    def flush(self) -> None:
        self._batch_committer.flush()


class SQLiteDecisionSink:
    def __init__(
        self,
        conn: sqlite3.Connection,
        game_id: str,
        batch_committer: "BatchCommitter | None" = None,
        *,
        commit_every: int = DEFAULT_COMMIT_EVERY,
    ) -> None:
        self._conn = conn
        self._game_id = game_id
        self._batch_committer = batch_committer or BatchCommitter(conn, commit_every=commit_every)

    def record_decision(self, decision: DecisionRecordData) -> None:
        if decision.player_id is None:
            raise ValueError("DecisionRecordData.player_id is required for SQLite persistence")
        decision_id = storage_decision_id(self._game_id, decision.decision_id)
        self._conn.execute(
            "INSERT OR REPLACE INTO decisions "
            "(id, game_id, seat, role, day, phase, action_type, "
            "selected_target, selected_choice, public_text, private_reasoning, "
            "confidence, alternatives, rejected_reasons, selected_skills, "
            "raw_output, source, policy_adjustments, errors, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                decision_id,
                self._game_id,
                decision.player_id,
                decision.role,
                decision.day,
                decision.phase,
                decision.action_type,
                decision.selected_target,
                decision.selected_choice,
                decision.public_text,
                decision.private_reasoning,
                decision.confidence,
                json.dumps(decision.alternatives, ensure_ascii=False),
                json.dumps(decision.rejected_reasons, ensure_ascii=False),
                json.dumps(decision.selected_skills, ensure_ascii=False),
                decision.raw_output,
                decision.source,
                json.dumps(decision.policy_adjustments, ensure_ascii=False),
                json.dumps(decision.errors, ensure_ascii=False),
                storage_timestamp(),
            ),
        )
        self._batch_committer.mark_write()

    def flush(self) -> None:
        self._batch_committer.flush()


class BatchCommitter:
    """Commit a shared SQLite connection every N writes, with explicit flush."""

    def __init__(self, conn: sqlite3.Connection, *, commit_every: int = DEFAULT_COMMIT_EVERY) -> None:
        self._conn = conn
        self._commit_every = max(1, int(commit_every or DEFAULT_COMMIT_EVERY))
        self._pending = 0

    def mark_write(self) -> None:
        self._pending += 1
        if self._pending >= self._commit_every:
            self.flush()

    def flush(self) -> None:
        if self._pending <= 0:
            return
        self._conn.commit()
        self._pending = 0


class GamePersistence:
    def __init__(
        self,
        *,
        game_id: str,
        game_dir: Path | str | None = None,
        db_path: Path | str | None = None,
        conn: sqlite3.Connection | None = None,
        source_game_id: str | None = None,
        run_policy: RunPolicy | None = None,
        run_metadata: dict[str, Any] | None = None,
        evolution_db_path: Path | str | None = None,
        commit_every: int = DEFAULT_COMMIT_EVERY,
    ) -> None:
        if db_path is not None and conn is not None:
            raise ValueError("Pass either db_path or conn, not both")
        self.game_id = game_id
        self.game_dir = Path(game_dir) if game_dir is not None else None
        self.source_game_id = source_game_id or game_id
        self.run_policy = run_policy
        self.run_metadata = run_metadata
        self.evolution_db_path = Path(evolution_db_path) if evolution_db_path is not None else None
        self._conn = get_connection(Path(db_path)) if db_path is not None else conn
        self._committer = (
            BatchCommitter(self._conn, commit_every=commit_every)
            if self._conn is not None
            else None
        )
        self._owns_conn = db_path is not None
        self._closed = False

    @property
    def conn(self) -> sqlite3.Connection | None:
        return self._conn

    @property
    def has_db(self) -> bool:
        return self._conn is not None

    def create_event_sink(self) -> SQLiteEventSink | None:
        return SQLiteEventSink(self._conn, self.game_id, self._committer) if self._conn is not None else None

    def create_decision_sink(self) -> SQLiteDecisionSink | None:
        return SQLiteDecisionSink(self._conn, self.game_id, self._committer) if self._conn is not None else None

    def create_event_logger(
        self,
        stream_path: Path | str | None = None,
    ) -> Any:
        from engine.logging import GameLogger
        sink = self.create_event_sink()
        return GameLogger(stream_path=stream_path, sink=sink)

    def save_game_result(
        self,
        *,
        seed: int,
        player_roles: dict[int, str],
        config: dict[str, Any] | None = None,
        winner: str | None = None,
        started_at: str = "",
        finished_at: str | None = None,
        total_rounds: int = 0,
        public_events: list[dict] | None = None,
        final_state: dict | None = None,
        deaths: list[dict] | None = None,
        final_alive: dict[int, bool] | None = None,
        role_version_ids: dict[int, str] | None = None,
        skill_package_hashes: dict[int, str] | None = None,
    ) -> None:
        if self._conn is None:
            return
        config_payload = dict(config or {})
        if self.game_dir is not None:
            config_payload.setdefault(
                "_storage",
                {
                    "source_game_id": self.source_game_id,
                    "source_path": str(self.game_dir),
                },
            )
        # Derive run policy fields
        rp = self.run_policy
        if self._committer is not None:
            self._committer.flush()
        store = GameStore(self._conn, autocommit=False)
        try:
            store.insert_game(
                game_id=self.game_id,
                seed=seed,
                config=config_payload,
                winner=winner,
                started_at=started_at,
                finished_at=finished_at,
                total_rounds=total_rounds,
                public_events=public_events,
                final_state=final_state,
                run_type=rp.run_type.value if rp else None,
                mode=self.run_metadata.get("mode") if self.run_metadata else None,
                learning_eligible=1 if rp and rp.learning_eligible else 0,
                leaderboard_scope=rp.leaderboard_scope.value if rp else None,
                promote_eligible=1 if rp and rp.promote_eligible else 0,
                model_id=self.run_metadata.get("model_id") if self.run_metadata else None,
                model_config_hash=self.run_metadata.get("model_config_hash") if self.run_metadata else None,
                ruleset_version=self.run_metadata.get("ruleset_version", "werewolf_12p_v1") if self.run_metadata else None,
                run_metadata=self.run_metadata,
            )
            store.insert_players(
                self.game_id,
                player_roles,
                final_alive=final_alive,
                deaths=deaths,
                role_version_ids=role_version_ids,
                skill_package_hashes=skill_package_hashes,
            )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()

    def save_experience_candidates(self, candidates: list[Any]) -> list[str]:
        if not candidates:
            return []
        # Gate: only explicit evolution_training runs may write learning facts.
        if self.run_policy is None:
            raise PermissionError("Experience writes require an explicit RunPolicy")
        if (
            self.run_policy.run_type is not RunType.EVOLUTION_TRAINING
            or not self.run_policy.learning_eligible
        ):
            return []
        # Experience goes to evolution.db, NOT wolf.db
        from storage.shared.connection import get_evolution_connection
        evo_conn = get_evolution_connection(self.evolution_db_path)
        try:
            from storage.evolution.experience_repo import ExperienceCandidateStore
            repo = ExperienceCandidateStore(evo_conn)
            return repo.save_candidates(
                self.game_id,
                [self._candidate_with_storage_evidence(c) for c in candidates],
                run_type=self.run_policy.run_type.value,
                source_run_id=str(self.run_metadata.get("source_run_id") or "")
                if self.run_metadata else "",
                source_game_id=self.source_game_id,
                artifact_game_id=self.game_id,
                learning_eligible=self.run_policy.learning_eligible,
                mode=str(self.run_metadata.get("mode") or "formal")
                if self.run_metadata else "formal",
            )
        finally:
            evo_conn.close()

    def commit(self) -> None:
        if self._committer is not None:
            self._committer.flush()
        if self._conn is not None:
            self._conn.commit()

    def close(self) -> None:
        if self._closed:
            return
        if self._conn is not None:
            self.commit()
            if self._owns_conn:
                self._conn.close()
        self._closed = True

    def __enter__(self) -> GamePersistence:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def _candidate_with_storage_evidence(self, candidate: Any) -> dict[str, Any]:
        if hasattr(candidate, "to_dict"):
            data = candidate.to_dict()
        elif isinstance(candidate, dict):
            data = dict(candidate)
        else:
            raise TypeError(f"Unsupported experience candidate type: {type(candidate)!r}")
        original_ids = [str(item) for item in data.get("evidence_decision_ids") or []]
        if original_ids:
            data.setdefault("source_evidence_decision_ids", original_ids)
            data["evidence_decision_ids"] = [
                storage_decision_id(self.game_id, decision_id)
                for decision_id in original_ids
            ]
        return data
