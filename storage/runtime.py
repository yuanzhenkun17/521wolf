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
from typing import Any, Protocol, TYPE_CHECKING

from storage.interfaces import DecisionRecordData

from storage.experience_store import ExperienceCandidateStore
from storage.game_store import GameStore
from storage.ids import storage_decision_id
from storage.schema import get_connection

if TYPE_CHECKING:
    from agent.infrastructure.decision_log import AgentDecisionRecorder
    from engine.logging import GameLogEntry, GameLogger


class EventEntry(Protocol):
    """Protocol describing the fields storage needs from a game log entry."""

    index: int
    day: int
    phase: str
    event_type: str
    message: str
    level: Any  # has .value
    visibility: Any  # has .value
    actor: int | None
    target: int | None
    payload: dict[str, Any]


def open_storage_connection(db_path: Path | str) -> sqlite3.Connection:
    return get_connection(Path(db_path))


class SQLiteEventSink:
    def __init__(self, conn: sqlite3.Connection, game_id: str) -> None:
        self._conn = conn
        self._game_id = game_id

    def record_event(self, entry: EventEntry) -> None:
        self._conn.execute(
            "INSERT INTO game_events "
            "(game_id, idx, day, phase, event_type, message, level, "
            "visibility, actor, target, payload) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                self._game_id,
                entry.index,
                entry.day,
                entry.phase,
                entry.event_type,
                entry.message,
                entry.level.value,
                entry.visibility.value,
                entry.actor,
                entry.target,
                json.dumps(entry.payload, ensure_ascii=False),
            ),
        )


class SQLiteDecisionSink:
    def __init__(self, conn: sqlite3.Connection, game_id: str) -> None:
        self._conn = conn
        self._game_id = game_id

    def record_decision(self, decision: DecisionRecordData) -> None:
        decision_id = storage_decision_id(self._game_id, decision.decision_id)
        self._conn.execute(
            "INSERT OR REPLACE INTO decisions "
            "(id, game_id, seat, role, day, phase, action_type, "
            "selected_target, selected_choice, public_text, private_reasoning, "
            "confidence, alternatives, rejected_reasons, selected_skills, "
            "raw_output, source, policy_adjustments, errors, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
            (
                decision_id,
                self._game_id,
                decision.player_id or 0,
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
            ),
        )


class GamePersistence:
    def __init__(
        self,
        *,
        game_id: str,
        game_dir: Path | str | None = None,
        db_path: Path | str | None = None,
        conn: sqlite3.Connection | None = None,
        source_game_id: str | None = None,
    ) -> None:
        if db_path is not None and conn is not None:
            raise ValueError("Pass either db_path or conn, not both")
        self.game_id = game_id
        self.game_dir = Path(game_dir) if game_dir is not None else None
        self.source_game_id = source_game_id or game_id
        self._conn = get_connection(Path(db_path)) if db_path is not None else conn
        self._owns_conn = db_path is not None
        self._closed = False

    @property
    def conn(self) -> sqlite3.Connection | None:
        return self._conn

    @property
    def has_db(self) -> bool:
        return self._conn is not None

    def create_event_sink(self) -> SQLiteEventSink | None:
        return SQLiteEventSink(self._conn, self.game_id) if self._conn is not None else None

    def create_decision_sink(self) -> SQLiteDecisionSink | None:
        return SQLiteDecisionSink(self._conn, self.game_id) if self._conn is not None else None

    def create_event_logger(
        self,
        stream_path: Path | str | None = None,
    ) -> Any:
        from engine.logging import GameLogger
        sink = self.create_event_sink()
        return GameLogger(stream_path=stream_path, sink=sink)

    def create_decision_recorder(
        self,
        stream_path: Path | str | None = None,
    ) -> Any:
        from agent.infrastructure.decision_log import AgentDecisionRecorder
        sink = self.create_decision_sink()
        return AgentDecisionRecorder(stream_path=stream_path, sink=sink)

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
        store = GameStore(self._conn)
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
        )
        store.insert_players(
            self.game_id,
            player_roles,
            final_alive=final_alive,
            deaths=deaths,
        )

    def save_experience_candidates(self, candidates: list[Any]) -> list[str]:
        if self._conn is None or not candidates:
            return []
        return ExperienceCandidateStore(self._conn).save_candidates(
            self.game_id,
            [self._candidate_with_storage_evidence(candidate) for candidate in candidates],
        )

    def commit(self) -> None:
        if self._conn is not None:
            self._conn.commit()

    def close(self) -> None:
        if self._closed:
            return
        if self._conn is not None:
            self._conn.commit()
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