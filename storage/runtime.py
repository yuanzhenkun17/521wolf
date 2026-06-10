"""Runtime persistence session for one game.

This module owns the bridge between raw artifacts (JSONL/archive files) and
PostgreSQL-backed indexes. Engine and agent runtime code should receive
loggers/recorders from here instead of constructing storage objects directly.
"""

from __future__ import annotations

import logging
import json
import hashlib
from pathlib import Path
from typing import Any, Protocol

from storage.interfaces import DecisionRecordData, storage_timestamp
from storage.run_policy import RunPolicy, RunType, policy_for_run_type
from storage.public_events import public_events_only
from storage.shared.database import StorageConnection

from storage.game_store import GameStore
from storage.ids import storage_decision_id
from storage.provider import StorageProvider, storage_provider_from_env

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


def open_storage_connection(provider: StorageProvider | None = None) -> StorageConnection:
    return (provider or storage_provider_from_env()).open_wolf_connection()


def create_game_persistence(
    *,
    game_id: str,
    game_dir: Path | str | None = None,
    storage_provider: StorageProvider | None = None,
    paths: Any | None = None,
    source_game_id: str | None = None,
    run_type: RunType | str = RunType.ORDINARY_GAME,
    run_metadata: dict[str, Any] | None = None,
    commit_every: int = DEFAULT_COMMIT_EVERY,
) -> "GamePersistence":
    """Create a runtime persistence handle with the route policy wired in."""
    import storage.provider as provider_mod

    resolved_run_type = run_type if isinstance(run_type, RunType) else RunType(str(run_type))
    if storage_provider:
        provider = storage_provider
    elif paths is None:
        provider = provider_mod.storage_provider_from_env()
    else:
        provider = provider_mod.storage_provider_from_env(paths=paths)
    return GamePersistence(
        game_id=game_id,
        game_dir=game_dir,
        provider=provider,
        source_game_id=source_game_id or game_id,
        run_policy=policy_for_run_type(resolved_run_type),
        run_metadata=run_metadata,
        commit_every=commit_every,
    )


class DatabaseEventSink:
    def __init__(
        self,
        conn: StorageConnection,
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


class DatabaseDecisionSink:
    def __init__(
        self,
        conn: StorageConnection,
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
            raise ValueError("DecisionRecordData.player_id is required for persistence")
        decision_id = storage_decision_id(self._game_id, decision.decision_id)
        action_type = decision.action_type.value if hasattr(decision.action_type, "value") else decision.action_type
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
                self._game_id,
                decision.player_id,
                decision.player_id,
                decision.role,
                decision.day,
                decision.phase,
                action_type,
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
    """Commit a shared storage connection every N writes, with explicit flush."""

    def __init__(self, conn: StorageConnection, *, commit_every: int = DEFAULT_COMMIT_EVERY) -> None:
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
        conn: StorageConnection | None = None,
        evolution_conn: StorageConnection | None = None,
        provider: StorageProvider | None = None,
        source_game_id: str | None = None,
        run_policy: RunPolicy | None = None,
        run_metadata: dict[str, Any] | None = None,
        commit_every: int = DEFAULT_COMMIT_EVERY,
    ) -> None:
        if conn is not None and provider is not None:
            raise ValueError("Pass either conn or provider, not both")
        if provider is not None and evolution_conn is not None:
            raise ValueError("Pass either provider or evolution_conn, not both")
        self.game_id = game_id
        self.game_dir = Path(game_dir) if game_dir is not None else None
        self.source_game_id = source_game_id or game_id
        self.run_policy = run_policy
        self.run_metadata = run_metadata
        self._provider = provider
        if self._provider is None and conn is None:
            self._provider = storage_provider_from_env()
        self._conn = conn if conn is not None else self._provider.open_wolf_connection()
        self._evolution_conn = evolution_conn
        self._committer = (
            BatchCommitter(self._conn, commit_every=commit_every)
            if self._conn is not None
            else None
        )
        self._owns_conn = conn is None
        self._owns_evolution_conn = False
        self._closed = False

    @property
    def conn(self) -> StorageConnection | None:
        return self._conn

    @property
    def has_db(self) -> bool:
        return self._conn is not None

    def create_event_sink(self) -> DatabaseEventSink | None:
        return DatabaseEventSink(self._conn, self.game_id, self._committer) if self._conn is not None else None

    def create_decision_sink(self) -> DatabaseDecisionSink | None:
        return DatabaseDecisionSink(self._conn, self.game_id, self._committer) if self._conn is not None else None

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
                public_events=public_events_only(public_events),
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
        evo_conn = self._open_evolution_connection()
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
            if self._evolution_conn is None:
                evo_conn.close()

    def save_llm_judgments(
        self,
        judgments: list[dict[str, Any]],
        *,
        dimension: str = "decision_judge",
        prompt_version: str = "decision_judge_v1",
        evaluator_config_hash: str | None = None,
    ) -> list[str]:
        """Persist LLM judge rows for a game in the existing wolf.llm_judgments table."""
        if self._conn is None or not judgments:
            return []
        if self._committer is not None:
            self._committer.flush()

        saved: list[str] = []
        now = storage_timestamp()
        try:
            for index, item in enumerate(judgments):
                if not isinstance(item, dict):
                    continue
                row_dimension = str(item.get("dimension") or dimension)
                dedup_key = str(
                    item.get("decision_id")
                    or item.get("report_id")
                    or item.get("key")
                    or index
                )
                judgment_id = str(
                    item.get("judgment_id")
                    or _llm_judgment_id(self.game_id, row_dimension, dedup_key)
                )
                raw_json = item.get("raw_json") if isinstance(item.get("raw_json"), dict) else item
                normalized_fields = (
                    item.get("normalized_fields")
                    if isinstance(item.get("normalized_fields"), dict)
                    else _normalized_judgment_fields(item)
                )
                input_refs = (
                    item.get("input_refs")
                    if isinstance(item.get("input_refs"), dict)
                    else _judgment_input_refs(self.game_id, item)
                )
                self._conn.execute(
                    "INSERT INTO llm_judgments "
                    "(judgment_id, game_id, player_id, dimension, prompt_version, "
                    "evaluator_config_hash, input_refs, raw_json, normalized_fields, "
                    "validator_status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(judgment_id) DO UPDATE SET "
                    "game_id = excluded.game_id, "
                    "player_id = excluded.player_id, "
                    "dimension = excluded.dimension, "
                    "prompt_version = excluded.prompt_version, "
                    "evaluator_config_hash = excluded.evaluator_config_hash, "
                    "input_refs = excluded.input_refs, "
                    "raw_json = excluded.raw_json, "
                    "normalized_fields = excluded.normalized_fields, "
                    "validator_status = excluded.validator_status, "
                    "created_at = excluded.created_at",
                    (
                        judgment_id,
                        self.game_id,
                        _as_int(item.get("player_id")),
                        row_dimension,
                        str(item.get("prompt_version") or prompt_version),
                        item.get("evaluator_config_hash") or evaluator_config_hash,
                        _json_payload(input_refs),
                        _json_payload(raw_json),
                        _json_payload(normalized_fields),
                        str(item.get("validator_status") or "valid"),
                        str(item.get("created_at") or now),
                    ),
                )
                saved.append(judgment_id)
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()
        return saved

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
        if self._evolution_conn is not None and self._owns_evolution_conn:
            self._evolution_conn.commit()
            self._evolution_conn.close()
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

    def _open_evolution_connection(self) -> StorageConnection:
        if self._evolution_conn is not None:
            return self._evolution_conn
        if self._provider is not None:
            self._evolution_conn = self._provider.open_evolution_connection()
            self._owns_evolution_conn = True
            return self._evolution_conn
        self._evolution_conn = storage_provider_from_env().open_evolution_connection()
        self._owns_evolution_conn = True
        return self._evolution_conn


def _llm_judgment_id(game_id: str, dimension: str, key: str) -> str:
    digest = hashlib.sha256(f"{game_id}|{dimension}|{key}".encode("utf-8")).hexdigest()[:16]
    return f"{game_id}::{dimension}::{digest}"


def _judgment_input_refs(game_id: str, item: dict[str, Any]) -> dict[str, Any]:
    decision_id = str(item.get("decision_id") or "")
    refs: dict[str, Any] = {
        "decision_id": decision_id or None,
        "evidence_refs": item.get("evidence_refs") or [],
    }
    if decision_id:
        refs["storage_decision_id"] = _storage_decision_ref(game_id, decision_id)
    return refs


def _storage_decision_ref(game_id: str, decision_id: str) -> str:
    try:
        return storage_decision_id(game_id, decision_id)
    except ValueError:
        digest = hashlib.sha256(decision_id.encode("utf-8")).hexdigest()[:16]
        return f"{game_id}::decision::{digest}"


def _normalized_judgment_fields(item: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in (
        "decision_id",
        "player_id",
        "role",
        "action_type",
        "day",
        "phase",
        "score",
        "quality",
        "reason",
        "mistake_tags",
        "suggestion",
        "confidence",
        "status",
        "summary",
        "metrics",
    ):
        if key in item:
            fields[key] = item[key]
    return fields


def _json_payload(value: Any) -> str:
    return json.dumps(_plain_json(value), ensure_ascii=False, default=str)


def _plain_json(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return _plain_json(value.to_dict())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_plain_json(item) for item in value]
    return value


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
