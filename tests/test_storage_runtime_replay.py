from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from storage.interfaces import DecisionRecordData
from storage.decision_store import DecisionStore
from storage.replay import (
    explain_replay_lookup,
    read_config_for_artifact,
    read_decisions_for_artifact,
    read_events_for_artifact,
)
from storage.runtime import GamePersistence, create_game_persistence


class _Cursor:
    rowcount = 0

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = list(rows or [])
        self.rowcount = len(self._rows)

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _MemoryStorageConn:
    def __init__(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = {
            "games": [],
            "players": [],
            "game_events": [],
            "decisions": [],
            "experience_candidates": [],
            "llm_judgments": [],
        }
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.entered = 0
        self._decision_insert_order = 0

    def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
        if self.closed:
            raise RuntimeError("connection closed")
        text = " ".join(sql.split())
        params = tuple(parameters)

        if text.startswith("INSERT INTO game_events"):
            self.tables["game_events"].append(
                {
                    "game_id": params[0],
                    "idx": params[1],
                    "day": params[2],
                    "phase": params[3],
                    "event_type": params[4],
                    "message": params[5],
                    "public": params[6],
                    "actor": params[7],
                    "target": params[8],
                    "payload": params[9],
                    "created_at": params[10],
                }
            )
            return _Cursor()

        if text.startswith("INSERT INTO decisions"):
            if "(id, game_id, player_id, seat," in text:
                row = {
                    "id": params[0],
                    "game_id": params[1],
                    "_insert_order": self._next_decision_insert_order(),
                    "player_id": params[2],
                    "seat": params[3],
                    "role": params[4],
                    "day": params[5],
                    "phase": params[6],
                    "action_type": params[7],
                    "selected_target": params[8],
                    "selected_choice": params[9],
                    "public_text": params[10],
                    "private_reasoning": params[11],
                    "confidence": params[12],
                    "alternatives": params[13],
                    "rejected_reasons": params[14],
                    "selected_skills": params[15],
                    "raw_output": params[16],
                    "source": params[17],
                    "policy_adjustments": params[18],
                    "errors": params[19],
                    "created_at": params[20],
                }
            else:
                row = {
                    "id": params[0],
                    "game_id": params[1],
                    "_insert_order": self._next_decision_insert_order(),
                    "player_id": None,
                    "seat": params[2],
                    "role": params[3],
                    "day": params[4],
                    "phase": params[5],
                    "action_type": params[6],
                    "selected_target": params[7],
                    "selected_choice": params[8],
                    "public_text": params[9],
                    "private_reasoning": params[10],
                    "confidence": params[11],
                    "alternatives": params[12],
                    "rejected_reasons": params[13],
                    "selected_skills": params[14],
                    "raw_output": params[15],
                    "source": params[16],
                    "policy_adjustments": params[17],
                    "errors": params[18],
                    "created_at": params[19],
                }
            row.update(
                {
                    "candidates": "[]",
                    "observation_summary": "{}",
                    "memory_context": "{}",
                    "prompt_messages": "[]",
                    "parsed_decision": "{}",
                    "final_response": "{}",
                }
            )
            self.tables["decisions"].append(row)
            return _Cursor()

        if text.startswith("INSERT INTO games"):
            self.tables["games"] = [
                row for row in self.tables["games"] if row["id"] != params[0]
            ]
            self.tables["games"].append(
                {
                    "id": params[0],
                    "seed": params[1],
                    "config": params[2],
                    "winner": params[3],
                    "started_at": params[4],
                    "finished_at": params[5],
                    "total_rounds": params[6],
                    "public_events": params[7],
                    "final_state": params[8],
                    "run_type": params[9],
                    "mode": params[10],
                    "learning_eligible": params[11],
                    "leaderboard_scope": params[12],
                    "promote_eligible": params[13],
                    "model_id": params[14],
                    "model_config_hash": params[15],
                    "ruleset_version": params[16],
                }
            )
            return _Cursor()

        if text.startswith("UPDATE games SET"):
            game_id = params[-1]
            game = self._game(game_id)
            if game is not None:
                assignments = text.removeprefix("UPDATE games SET ").split(" WHERE id = ?")[0]
                for column, value in zip(
                    [part.split(" = ")[0] for part in assignments.split(", ")],
                    params[:-1],
                    strict=False,
                ):
                    game[column] = value
            return _Cursor()

        if text.startswith("INSERT INTO players"):
            self.tables["players"].append(
                {
                    "game_id": params[0],
                    "seat": params[1],
                    "role": params[2],
                    "team": params[3],
                    "alive": params[4],
                    "killed_day": params[5],
                    "killed_cause": params[6],
                    "role_version_id": params[7],
                    "skill_package_hash": params[8],
                }
            )
            return _Cursor()

        if text.startswith("INSERT INTO experience_candidates"):
            self.tables["experience_candidates"].append(
                {
                    "game_id": params[0],
                    "candidate_id": params[1],
                    "role": params[2],
                    "candidate_type": params[4],
                    "topic": params[5],
                    "evidence_decision_ids": params[7],
                    "recommendation": params[10],
                    "raw_json": params[19],
                    "run_type": params[21],
                    "source_run_id": params[22],
                    "source_game_id": params[23],
                    "artifact_game_id": params[24],
                    "learning_eligible": params[25],
                    "mode": params[26],
                }
            )
            return _Cursor()

        if text.startswith("INSERT INTO llm_judgments"):
            self.tables["llm_judgments"] = [
                row for row in self.tables["llm_judgments"] if row["judgment_id"] != params[0]
            ]
            self.tables["llm_judgments"].append(
                {
                    "judgment_id": params[0],
                    "game_id": params[1],
                    "player_id": params[2],
                    "dimension": params[3],
                    "prompt_version": params[4],
                    "evaluator_config_hash": params[5],
                    "input_refs": params[6],
                    "raw_json": params[7],
                    "normalized_fields": params[8],
                    "validator_status": params[9],
                    "created_at": params[10],
                }
            )
            return _Cursor()

        if text == "SELECT id, config FROM games WHERE config IS NOT NULL":
            return _Cursor([row for row in self.tables["games"] if row.get("config")])

        if text == "SELECT seed, config FROM games WHERE id = ?":
            game = self._game(params[0])
            return _Cursor(
                [{"seed": game["seed"], "config": game["config"]}] if game else []
            )

        if text == "SELECT 1 FROM games WHERE id = ? LIMIT 1":
            return _Cursor([{"?column?": 1}] if self._game(params[0]) else [])

        if text.startswith("SELECT 1 FROM game_events WHERE game_id = ?"):
            return _Cursor(self._rows_for_game("game_events", params[0])[:1])

        if text.startswith("SELECT 1 FROM decisions WHERE game_id = ?"):
            return _Cursor(self._rows_for_game("decisions", params[0])[:1])

        if text.startswith("SELECT 1 FROM experience_candidates WHERE game_id = ?"):
            return _Cursor(self._rows_for_game("experience_candidates", params[0])[:1])

        if text.startswith("SELECT * FROM game_events WHERE game_id = ?"):
            rows = sorted(self._rows_for_game("game_events", params[0]), key=lambda row: row["idx"])
            return _Cursor(rows)

        if text.startswith("SELECT * FROM decisions WHERE game_id = ?"):
            rows = sorted(
                self._rows_for_game("decisions", params[0]),
                key=lambda row: (
                    row.get("decision_index") is None and row.get("index") is None,
                    row.get("decision_index", row.get("index")),
                    row.get("created_at") or "",
                    row.get("_insert_order", 0),
                    row["id"],
                ),
            )
            return _Cursor(rows)

        if text.startswith("SELECT * FROM experience_candidates WHERE game_id = ?"):
            rows = [
                row
                for row in self.tables["experience_candidates"]
                if row["game_id"] == params[0] and row["candidate_id"] == params[1]
            ]
            return _Cursor(rows)

        raise AssertionError(f"unexpected SQL: {text}")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_MemoryStorageConn":
        self.entered += 1
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def _game(self, game_id: str) -> dict[str, Any] | None:
        return next((row for row in self.tables["games"] if row["id"] == game_id), None)

    def _rows_for_game(self, table: str, game_id: str) -> list[dict[str, Any]]:
        return [row for row in self.tables[table] if row["game_id"] == game_id]

    def _next_decision_insert_order(self) -> int:
        self._decision_insert_order += 1
        return self._decision_insert_order


class _Provider:
    def __init__(self) -> None:
        self.wolf_conn = _MemoryStorageConn()
        self.registry_conn = _MemoryStorageConn()
        self.evolution_conn = _MemoryStorageConn()
        self.wolf_calls = 0
        self.evolution_calls = 0

    def open_wolf_connection(self) -> _MemoryStorageConn:
        self.wolf_calls += 1
        return self.wolf_conn

    def open_registry_connection(self) -> _MemoryStorageConn:
        return self.registry_conn

    def open_evolution_connection(self) -> _MemoryStorageConn:
        self.evolution_calls += 1
        return self.evolution_conn


def test_game_persistence_replaces_empty_timestamps_for_pg_boundary() -> None:
    conn = _MemoryStorageConn()
    persistence = GamePersistence(game_id="empty-started-at", conn=conn)

    persistence.save_game_result(
        seed=1,
        player_roles={1: "seer"},
        started_at="",
        finished_at="",
    )

    game = conn.tables["games"][0]
    assert game["started_at"]
    assert game["started_at"].endswith("+08:00")
    assert game["finished_at"] is None


def test_game_persistence_saves_llm_judgments_to_wolf_schema() -> None:
    conn = _MemoryStorageConn()
    persistence = GamePersistence(game_id="judge_game", conn=conn)

    saved = persistence.save_llm_judgments(
        [
            {
                "decision_id": "d_check",
                "player_id": 1,
                "role": "seer",
                "action_type": "seer_check",
                "score": 8.5,
                "quality": "good",
                "reason": "查验有价值",
                "evidence_refs": ["rule_natural_key_action"],
                "mistake_tags": [],
                "suggestion": "继续围绕查验链组织发言",
                "confidence": 0.8,
            },
            {
                "dimension": "decision_judge_report",
                "report_id": "summary",
                "raw_json": {"status": "ok", "summary": {"average_score": 8.5}},
                "normalized_fields": {"status": "ok", "metrics": {"judged": 1}},
                "input_refs": {"selected_decision_ids": ["d_check"]},
            },
        ]
    )

    rows = conn.tables["llm_judgments"]
    assert len(saved) == 2
    assert [row["dimension"] for row in rows] == ["decision_judge", "decision_judge_report"]
    assert rows[0]["game_id"] == "judge_game"
    assert rows[0]["player_id"] == 1
    assert json.loads(rows[0]["input_refs"])["storage_decision_id"] == "judge_game::d_check"
    assert json.loads(rows[0]["normalized_fields"])["score"] == 8.5
    assert json.loads(rows[1]["raw_json"])["summary"]["average_score"] == 8.5


def test_game_persistence_round_trips_postgres_replay_by_artifact_path(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    game_dir = runs_root / "eval 01" / "game-001"
    game_dir.mkdir(parents=True)
    conn = _MemoryStorageConn()

    with GamePersistence(
        game_id="game_roundtrip",
        game_dir=game_dir,
        conn=conn,
        source_game_id="artifact_game_001",
        commit_every=100,
    ) as persistence:
        logger = persistence.create_event_logger()
        logger.record(
            day=1,
            phase="night",
            event_type="death",
            message="2 died",
            target=2,
            payload={"cause": "werewolf"},
        )
        logger.record(
            day=1,
            phase="night",
            event_type="seer_result",
            message="seer checked 2",
            actor=1,
            target=2,
            payload={"result": "werewolves"},
            public=False,
        )

        sink = persistence.create_decision_sink()
        assert sink is not None
        sink.record_decision(
            DecisionRecordData(
                decision_id="d_check",
                player_id=1,
                role="seer",
                day=1,
                phase="night",
                action_type="seer_check",
                selected_target=2,
                public_text="checked 2",
                private_reasoning="2 is suspicious",
                confidence=0.8,
                selected_skills=["seer/check.md"],
                raw_output="{}",
            )
        )

        persistence.save_game_result(
            seed=42,
            player_roles={1: "seer", 2: "werewolf"},
            config={"mode": "e2e"},
            winner="villagers",
            started_at="2026-06-07T10:00:00+08:00",
            finished_at="2026-06-07T10:10:00+08:00",
            total_rounds=1,
            public_events=[event.to_dict() for event in logger.entries if event.public],
            final_state={"winner": "villagers"},
            deaths=[{"player_id": 2, "day": 1, "cause": "werewolf"}],
            final_alive={1: True, 2: False},
        )

    events = read_events_for_artifact(game_dir, root=runs_root, conn=conn)
    assert events is not None
    assert [event["event_type"] for event in events] == ["death", "seer_result"]
    assert events[0]["payload"] == {"cause": "werewolf"}
    assert events[1]["visibility"] == "private"

    decisions = read_decisions_for_artifact(game_dir, root=runs_root, conn=conn)
    assert decisions is not None
    assert decisions[0]["decision_id"] == "d_check"
    assert decisions[0]["selected_skills"] == ["seer/check.md"]
    assert decisions[0]["private_reasoning"] == "2 is suspicious"

    config = read_config_for_artifact(game_dir, root=runs_root, conn=conn)
    assert config is not None
    assert config["mode"] == "e2e"
    assert config["seed"] == 42
    assert config["_storage"]["source_game_id"] == "artifact_game_001"
    assert config["_storage"]["source_path"] == str(game_dir)


def test_replay_decisions_preserve_recorder_write_order(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    game_dir = runs_root / "game-decision-order"
    game_dir.mkdir(parents=True)
    conn = _MemoryStorageConn()

    with GamePersistence(
        game_id="game_decision_order",
        game_dir=game_dir,
        conn=conn,
        commit_every=100,
    ) as persistence:
        sink = persistence.create_decision_sink()
        assert sink is not None
        sink.record_decision(
            DecisionRecordData(
                decision_id="d_player_2_first",
                player_id=2,
                role="villager",
                day=1,
                phase="day",
                action_type="speak",
                public_text="2 speaks first",
            )
        )
        sink.record_decision(
            DecisionRecordData(
                decision_id="d_player_1_second",
                player_id=1,
                role="villager",
                day=1,
                phase="day",
                action_type="speak",
                public_text="1 speaks second",
            )
        )
        persistence.save_game_result(
            seed=7,
            player_roles={1: "villager", 2: "villager"},
            started_at="2026-06-08T10:00:00+08:00",
        )

    decisions = read_decisions_for_artifact(game_dir, root=runs_root, conn=conn)

    assert decisions is not None
    assert [decision["player_id"] for decision in decisions] == [2, 1]
    assert [decision["index"] for decision in decisions] == [1, 2]
    assert [decision["decision_id"] for decision in decisions] == [
        "d_player_2_first",
        "d_player_1_second",
    ]


def test_decision_store_get_for_game_preserves_write_order() -> None:
    conn = _MemoryStorageConn()
    store = DecisionStore(conn)  # type: ignore[arg-type]

    store.insert_record(
        "game_store_order",
        DecisionRecordData(
            decision_id="d_player_2_first",
            player_id=2,
            role="villager",
            day=1,
            phase="day",
            action_type="speak",
            public_text="2 speaks first",
        ),
        created_at="2026-06-08T10:00:00+08:00",
    )
    store.insert_record(
        "game_store_order",
        DecisionRecordData(
            decision_id="d_player_1_second",
            player_id=1,
            role="villager",
            day=1,
            phase="day",
            action_type="speak",
            public_text="1 speaks second",
        ),
        created_at="2026-06-08T10:00:00+08:00",
    )

    rows = store.get_for_game("game_store_order")

    assert [row["seat"] for row in rows] == [2, 1]
    assert [row["decision_id"] for row in rows] == [
        "d_player_2_first",
        "d_player_1_second",
    ]


def test_replay_lookup_explains_unsupported_type(tmp_path: Path) -> None:
    game_dir = tmp_path / "runs" / "game-bad-type"

    result = explain_replay_lookup(game_dir, replay_type="bad", conn=_MemoryStorageConn())

    assert result.ok is False
    assert result.status == "unsupported_type"
    assert result.table is None
    assert result.game_dir == str(game_dir)
    assert "events, decisions, config" in result.message


def test_replay_config_lookup_can_succeed_without_event_rows(tmp_path: Path) -> None:
    game_dir = tmp_path / "runs" / "game-config-only"
    game_dir.mkdir(parents=True)
    conn = _MemoryStorageConn()
    conn.tables["games"].append(
        {
            "id": "game_config_only",
            "seed": 11,
            "config": json.dumps(
                {"mode": "config-only", "_storage": {"source_path": str(game_dir)}}
            ),
        }
    )

    config_result = explain_replay_lookup(game_dir, replay_type="config", conn=conn)
    events_result = explain_replay_lookup(game_dir, replay_type="events", conn=conn)

    assert config_result.ok is True
    assert config_result.table == "games"
    assert config_result.data["mode"] == "config-only"
    assert config_result.data["seed"] == 11
    assert read_config_for_artifact(game_dir, conn=conn) == config_result.data
    assert events_result.status == "missing_rows"
    assert read_events_for_artifact(game_dir, conn=conn) is None


def test_replay_lookup_reports_storage_error(tmp_path: Path) -> None:
    class _BrokenConn:
        def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
            raise RuntimeError("database unavailable")

    game_dir = tmp_path / "runs" / "game-broken"

    result = explain_replay_lookup(game_dir, replay_type="events", conn=_BrokenConn())  # type: ignore[arg-type]

    assert read_events_for_artifact(game_dir, conn=_BrokenConn()) is None  # type: ignore[arg-type]
    assert result.ok is False
    assert result.status == "storage_error"
    assert result.table == "game_events"
    assert "database unavailable" in str(result.error)


def test_game_persistence_players_reflect_deaths(tmp_path: Path) -> None:
    conn = _MemoryStorageConn()

    with GamePersistence(game_id="game_players", game_dir=tmp_path / "game", conn=conn) as persistence:
        persistence.save_game_result(
            seed=1,
            player_roles={1: "seer", 2: "werewolf", 3: "villager"},
            deaths=[{"player_id": 2, "day": 1, "cause": "werewolf"}],
            final_alive={1: True, 2: True, 3: False},
            started_at="2026-06-07T10:00:00+08:00",
        )

    by_seat = {row["seat"]: row for row in conn.tables["players"]}
    assert by_seat[1]["alive"] == 1
    assert by_seat[2]["alive"] == 0
    assert by_seat[2]["killed_day"] == 1
    assert by_seat[2]["killed_cause"] == "werewolf"
    assert by_seat[3]["alive"] == 0


def test_game_persistence_rolls_back_invalid_player_batch(tmp_path: Path) -> None:
    conn = _MemoryStorageConn()

    with pytest.raises(ValueError, match="invalid literal"):
        with GamePersistence(game_id="game_bad_players", game_dir=tmp_path / "game", conn=conn) as persistence:
            persistence.save_game_result(
                seed=1,
                player_roles={1: "seer", "bad": "werewolf"},  # type: ignore[dict-item]
                started_at="2026-06-07T10:00:00+08:00",
            )

    assert conn.rollbacks == 1


def test_learning_candidates_are_written_to_provider_evolution_schema() -> None:
    from storage.run_policy import RunType, policy_for_run_type

    provider = _Provider()
    persistence = GamePersistence(
        game_id="training_game",
        provider=provider,
        source_game_id="artifact_training",
        run_policy=policy_for_run_type(RunType.EVOLUTION_TRAINING),
        run_metadata={"source_run_id": "run_1", "mode": "formal"},
    )
    try:
        saved = persistence.save_experience_candidates(
            [
                {
                    "candidate_id": "cand1",
                    "role": "seer",
                    "candidate_type": "decision",
                    "topic": "night check",
                    "recommendation": "check contested players",
                    "evidence_decision_ids": ["d1"],
                }
            ]
        )
    finally:
        persistence.close()

    assert saved == ["cand1"]
    assert provider.evolution_calls == 1
    row = provider.evolution_conn.tables["experience_candidates"][0]
    assert json.loads(row["evidence_decision_ids"]) == ["training_game::d1"]
    assert row["source_run_id"] == "run_1"
    assert row["source_game_id"] == "artifact_training"
    assert row["artifact_game_id"] == "training_game"
    assert row["learning_eligible"] == 1
    assert provider.wolf_conn.closed is True
    assert provider.evolution_conn.closed is True


def test_non_learning_policy_skips_evolution_connection() -> None:
    from storage.run_policy import RunType, policy_for_run_type

    provider = _Provider()
    persistence = GamePersistence(
        game_id="ordinary_game",
        provider=provider,
        run_policy=policy_for_run_type(RunType.ORDINARY_GAME),
    )
    try:
        saved = persistence.save_experience_candidates([{"candidate_id": "skip"}])
    finally:
        persistence.close()

    assert saved == []
    assert provider.evolution_calls == 0


def test_learning_write_requires_explicit_policy() -> None:
    persistence = GamePersistence(game_id="no_policy", conn=_MemoryStorageConn())

    with pytest.raises(PermissionError, match="explicit RunPolicy"):
        persistence.save_experience_candidates([{"candidate_id": "blocked"}])


def test_game_persistence_rejects_conflicting_provider_sources() -> None:
    provider = _Provider()
    conn = _MemoryStorageConn()

    with pytest.raises(ValueError, match="either conn or provider"):
        GamePersistence(game_id="bad", conn=conn, provider=provider)
    with pytest.raises(ValueError, match="either provider or evolution_conn"):
        GamePersistence(
            game_id="bad",
            provider=provider,
            evolution_conn=conn,
        )


def test_create_game_persistence_resolves_provider_with_paths(monkeypatch, tmp_path: Path) -> None:
    import storage.provider as provider_mod
    from storage.run_policy import RunType

    provider = _Provider()
    calls: list[Any] = []

    def provider_from_env(*, paths: Any | None = None) -> _Provider:
        calls.append(paths)
        return provider

    monkeypatch.setattr(provider_mod, "storage_provider_from_env", provider_from_env)

    persistence = create_game_persistence(
        game_id="factory_game",
        game_dir=tmp_path / "game",
        paths=tmp_path,
        source_game_id="source_game",
        run_type="evolution_training",
        run_metadata={"source_run_id": "run_1", "mode": "formal"},
    )
    try:
        assert persistence.game_id == "factory_game"
        assert persistence.game_dir == tmp_path / "game"
        assert persistence.source_game_id == "source_game"
        assert persistence.run_policy is not None
        assert persistence.run_policy.run_type is RunType.EVOLUTION_TRAINING
        assert persistence.run_metadata == {"source_run_id": "run_1", "mode": "formal"}
        assert provider.wolf_calls == 1
        assert calls == [tmp_path]
    finally:
        persistence.close()


def test_create_game_persistence_with_connection_does_not_resolve_provider(
    monkeypatch,
) -> None:
    import storage.provider as provider_mod

    def fail_provider_from_env(**_: Any) -> _Provider:
        raise AssertionError("provider should not be resolved for injected connections")

    monkeypatch.setattr(provider_mod, "storage_provider_from_env", fail_provider_from_env)
    conn = _MemoryStorageConn()

    persistence = create_game_persistence(
        game_id="injected_conn_game",
        conn=conn,
        paths=object(),
        run_type="ordinary_game",
    )
    try:
        assert persistence.has_db is True
        assert persistence.conn is conn
    finally:
        persistence.close()

    assert conn.closed is False


def test_injected_evolution_connection_is_not_closed() -> None:
    from storage.run_policy import RunType, policy_for_run_type

    wolf_conn = _MemoryStorageConn()
    evolution_conn = _MemoryStorageConn()
    persistence = GamePersistence(
        game_id="injected_training_game",
        conn=wolf_conn,
        evolution_conn=evolution_conn,
        run_policy=policy_for_run_type(RunType.EVOLUTION_TRAINING),
    )
    try:
        saved = persistence.save_experience_candidates(
            [{"candidate_id": "injected_cand", "role": "seer"}]
        )
    finally:
        persistence.close()

    assert saved == ["injected_cand"]
    assert wolf_conn.closed is False
    assert evolution_conn.closed is False
    assert evolution_conn.tables["experience_candidates"][0]["candidate_id"] == "injected_cand"
