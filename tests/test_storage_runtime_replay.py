from __future__ import annotations

import json
import sqlite3

import pytest

from storage.interfaces import DecisionRecordData
from storage.replay import (
    explain_replay_lookup,
    read_config_for_artifact,
    read_decisions_for_artifact,
    read_events_for_artifact,
)
from storage.runtime import GamePersistence


def test_game_persistence_round_trips_sqlite_replay_by_artifact_path(tmp_path):
    db_path = tmp_path / "wolf.db"
    runs_root = tmp_path / "runs"
    game_dir = runs_root / "eval 01" / "game-001"
    game_dir.mkdir(parents=True)

    with GamePersistence(
        game_id="game_roundtrip",
        game_dir=game_dir,
        db_path=db_path,
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

    events = read_events_for_artifact(db_path, game_dir, root=runs_root)
    assert events is not None
    assert [event["event_type"] for event in events] == ["death", "seer_result"]
    assert events[0]["target"] == 2
    assert events[0]["payload"] == {"cause": "werewolf"}
    assert events[1]["visibility"] == "private"
    assert events[1]["public"] is False

    decisions = read_decisions_for_artifact(db_path, game_dir, root=runs_root)
    assert decisions is not None
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision["decision_id"] == "d_check"
    assert decision["player_id"] == 1
    assert decision["role"] == "seer"
    assert decision["selected_target"] == 2
    assert decision["selected_skills"] == ["seer/check.md"]
    assert decision["private_reasoning"] == "2 is suspicious"

    config = read_config_for_artifact(db_path, game_dir, root=runs_root)
    assert config is not None
    assert config["mode"] == "e2e"
    assert config["seed"] == 42
    assert config["_storage"]["source_game_id"] == "artifact_game_001"
    assert config["_storage"]["source_path"] == str(game_dir)


def test_replay_lookup_explains_missing_database(tmp_path):
    db_path = tmp_path / "missing.db"
    game_dir = tmp_path / "runs" / "game-missing"

    result = explain_replay_lookup(db_path, game_dir, replay_type="events")

    assert read_events_for_artifact(db_path, game_dir) is None
    assert result.ok is False
    assert result.status == "missing_db"
    assert result.table == "game_events"
    assert "does not exist" in result.message


def test_replay_lookup_explains_unsupported_type(tmp_path):
    db_path = tmp_path / "wolf.db"
    game_dir = tmp_path / "runs" / "game-bad-type"

    result = explain_replay_lookup(db_path, game_dir, replay_type="bad")

    assert result.ok is False
    assert result.status == "unsupported_type"
    assert result.table is None
    assert result.db_path == str(db_path)
    assert result.game_dir == str(game_dir)
    assert "bad" in result.message
    assert "events, decisions, config" in result.message
    assert result.error == "unsupported replay_type: bad"


def test_replay_lookup_explains_missing_table(tmp_path):
    db_path = tmp_path / "wolf.db"
    game_dir = tmp_path / "runs" / "game-missing-table"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE games (id TEXT PRIMARY KEY, config TEXT)")
        conn.commit()
    finally:
        conn.close()

    result = explain_replay_lookup(db_path, game_dir, replay_type="events")

    assert read_events_for_artifact(db_path, game_dir) is None
    assert result.ok is False
    assert result.status == "missing_table"
    assert result.table == "game_events"


def test_replay_lookup_explains_matched_game_with_no_rows(tmp_path):
    from storage.schema import get_connection

    db_path = tmp_path / "wolf.db"
    game_dir = tmp_path / "runs" / "game-empty"
    game_dir.mkdir(parents=True)
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO games (id, seed, config, started_at) VALUES (?, ?, ?, ?)",
            (
                "game_empty",
                7,
                json.dumps({"_storage": {"source_path": str(game_dir)}}),
                "2026-06-07T10:00:00+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = explain_replay_lookup(db_path, game_dir, replay_type="events")

    assert read_events_for_artifact(db_path, game_dir) is None
    assert result.ok is False
    assert result.status == "missing_rows"
    assert result.game_id == "game_empty"
    assert result.table == "game_events"


def test_replay_config_lookup_uses_games_row_without_replay_rows(tmp_path):
    from storage.schema import get_connection

    db_path = tmp_path / "wolf.db"
    game_dir = tmp_path / "runs" / "game-config-only"
    game_dir.mkdir(parents=True)
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO games (id, seed, config, started_at) VALUES (?, ?, ?, ?)",
            (
                "game_config_only",
                11,
                json.dumps({"mode": "config-only", "_storage": {"source_path": str(game_dir)}}),
                "2026-06-07T10:00:00+08:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    config_result = explain_replay_lookup(db_path, game_dir, replay_type="config")
    events_result = explain_replay_lookup(db_path, game_dir, replay_type="events")

    assert config_result.ok is True
    assert config_result.status == "ok"
    assert config_result.table == "games"
    assert config_result.game_id == "game_config_only"
    assert config_result.data["mode"] == "config-only"
    assert config_result.data["seed"] == 11
    assert read_config_for_artifact(db_path, game_dir) == config_result.data
    assert events_result.status == "missing_rows"
    assert read_events_for_artifact(db_path, game_dir) is None


def test_replay_lookup_explains_sqlite_error(tmp_path):
    db_path = tmp_path / "broken.db"
    db_path.write_text("not a sqlite database", encoding="utf-8")
    game_dir = tmp_path / "runs" / "game-broken"

    result = explain_replay_lookup(db_path, game_dir, replay_type="events")

    assert read_events_for_artifact(db_path, game_dir) is None
    assert result.ok is False
    assert result.status == "sqlite_error"
    assert result.error


def test_game_persistence_players_reflect_deaths(tmp_path):
    from storage.schema import get_connection

    db_path = tmp_path / "wolf.db"
    game_dir = tmp_path / "runs" / "game-players"
    game_dir.mkdir(parents=True)

    with GamePersistence(game_id="game_players", game_dir=game_dir, db_path=db_path) as persistence:
        persistence.save_game_result(
            seed=7,
            player_roles={1: "seer", 2: "werewolf"},
            started_at="2026-06-07T10:00:00+08:00",
            deaths=[{"player_id": 2, "day": 1, "cause": "werewolf"}],
            final_alive={1: True, 2: False},
        )

    conn = get_connection(db_path)
    try:
        rows = {
            row["seat"]: dict(row)
            for row in conn.execute("SELECT * FROM players WHERE game_id = ?", ("game_players",))
        }
    finally:
        conn.close()

    assert rows[1]["alive"] == 1
    assert rows[2]["alive"] == 0
    assert rows[2]["killed_day"] == 1
    assert rows[2]["killed_cause"] == "werewolf"


def test_game_persistence_save_game_result_rolls_back_partial_result(tmp_path):
    from storage.schema import get_connection

    db_path = tmp_path / "wolf.db"
    with GamePersistence(game_id="game_bad_players", db_path=db_path) as persistence:
        with pytest.raises(sqlite3.IntegrityError):
            persistence.save_game_result(
                seed=8,
                player_roles={1: None},  # type: ignore[dict-item]
                started_at="2026-06-07T10:00:00+08:00",
            )

    conn = get_connection(db_path)
    try:
        game_count = conn.execute(
            "SELECT COUNT(*) AS n FROM games WHERE id = ?",
            ("game_bad_players",),
        ).fetchone()["n"]
        player_count = conn.execute(
            "SELECT COUNT(*) AS n FROM players WHERE game_id = ?",
            ("game_bad_players",),
        ).fetchone()["n"]
    finally:
        conn.close()

    assert game_count == 0
    assert player_count == 0


def test_game_store_insert_players_updates_existing_rows(tmp_path):
    from storage.game_store import GameStore
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        store = GameStore(conn)
        store.insert_game(
            game_id="game_players_upsert",
            seed=9,
            started_at="2026-06-07T10:00:00+08:00",
        )
        store.insert_players(
            "game_players_upsert",
            {1: "seer"},
            final_alive={1: False},
            role_version_ids={1: "v1"},
            skill_package_hashes={1: "hash1"},
        )
        store.insert_players(
            "game_players_upsert",
            {1: "werewolf"},
            final_alive={1: True},
            role_version_ids={1: "v2"},
            skill_package_hashes={1: "hash2"},
        )
        row = conn.execute(
            "SELECT role, team, alive, role_version_id, skill_package_hash "
            "FROM players WHERE game_id = ? AND seat = ?",
            ("game_players_upsert", 1),
        ).fetchone()
    finally:
        conn.close()

    assert dict(row) == {
        "role": "werewolf",
        "team": "werewolves",
        "alive": 1,
        "role_version_id": "v2",
        "skill_package_hash": "hash2",
    }


def test_storage_connection_uses_busy_timeout(tmp_path):
    from storage.schema import get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    finally:
        conn.close()

    assert timeout_ms == 30000
    assert foreign_keys == 1
    assert journal_mode in {"wal", "delete", "memory", "off"}


def test_storage_schema_records_wolf_schema_version(tmp_path):
    from storage.schema import SCHEMA_VERSION, get_connection

    conn = get_connection(tmp_path / "wolf.db")
    try:
        row = conn.execute(
            "SELECT version, applied_at FROM schema_migrations WHERE component = ?",
            ("wolf",),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["version"] == SCHEMA_VERSION
    assert row["applied_at"]


def test_evolution_and_registry_connections_apply_pragmas_and_schema_versions(tmp_path):
    from storage.evolution.schema import SCHEMA_VERSION as EVOLUTION_SCHEMA_VERSION
    from storage.registry.schema import SCHEMA_VERSION as REGISTRY_SCHEMA_VERSION
    from storage.registry.connection import get_registry_connection
    from storage.shared.connection import get_evolution_connection

    cases = [
        (
            get_evolution_connection(tmp_path / "evolution.db"),
            "evolution",
            EVOLUTION_SCHEMA_VERSION,
        ),
        (
            get_registry_connection(tmp_path / "registry.db"),
            "registry",
            REGISTRY_SCHEMA_VERSION,
        ),
    ]

    for conn, component, expected_version in cases:
        try:
            assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
            assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            assert conn.execute("PRAGMA journal_mode").fetchone()[0] in {
                "wal",
                "delete",
                "memory",
                "off",
            }
            row = conn.execute(
                "SELECT version, applied_at FROM schema_migrations WHERE component = ?",
                (component,),
            ).fetchone()
            assert row is not None
            assert row["version"] == expected_version
            assert row["applied_at"]
        finally:
            conn.close()


def test_game_persistence_training_candidates_write_evolution_db_only(tmp_path):
    import json
    import sqlite3

    from storage.run_policy import RunType, policy_for_run_type

    wolf_db = tmp_path / "wolf.db"
    evolution_db = tmp_path / "evolution.db"
    policy = policy_for_run_type(RunType.EVOLUTION_TRAINING)
    persistence = GamePersistence(
        game_id="training_game_1",
        db_path=wolf_db,
        source_game_id="raw_game_1",
        run_policy=policy,
        run_metadata={"source_run_id": "run_1", "mode": "formal"},
        evolution_db_path=evolution_db,
    )
    try:
        saved = persistence.save_experience_candidates([
            {
                "candidate_id": "cand_1",
                "role": "seer",
                "candidate_type": "decision_pattern",
                "topic": "night check",
                "evidence_decision_ids": ["d_check"],
                "recommendation": "check contested claimants",
                "confidence": "medium",
            }
        ])
    finally:
        persistence.close()

    assert saved == ["cand_1"]

    evo_conn = sqlite3.connect(evolution_db)
    evo_conn.row_factory = sqlite3.Row
    try:
        row = evo_conn.execute(
            "SELECT * FROM experience_candidates WHERE game_id = ? AND candidate_id = ?",
            ("training_game_1", "cand_1"),
        ).fetchone()
        assert row is not None
        assert json.loads(row["evidence_decision_ids"]) == ["training_game_1::d_check"]
        assert row["run_type"] == "evolution_training"
        assert row["source_run_id"] == "run_1"
        assert row["source_game_id"] == "raw_game_1"
        assert row["artifact_game_id"] == "training_game_1"
        assert row["learning_eligible"] == 1
        raw_json = json.loads(row["raw_json"])
        assert raw_json["source_evidence_decision_ids"] == ["d_check"]
    finally:
        evo_conn.close()

    wolf_conn = sqlite3.connect(wolf_db)
    try:
        tables = {
            row[0]
            for row in wolf_conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'experience_candidates'"
            )
        }
    finally:
        wolf_conn.close()
    assert tables == set()


def test_game_persistence_non_learning_policy_skips_experience_candidates(tmp_path):
    import sqlite3

    from storage.run_policy import RunType, policy_for_run_type

    evolution_db = tmp_path / "evolution.db"
    persistence = GamePersistence(
        game_id="eval_game_1",
        db_path=tmp_path / "wolf.db",
        run_policy=policy_for_run_type(RunType.EVALUATION_BATCH),
        evolution_db_path=evolution_db,
    )
    try:
        saved = persistence.save_experience_candidates([
            {
                "candidate_id": "cand_skip",
                "role": "seer",
                "evidence_decision_ids": ["d1"],
            }
        ])
    finally:
        persistence.close()

    assert saved == []

    conn = sqlite3.connect(evolution_db)
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'experience_candidates'"
            )
        }
    finally:
        conn.close()
    assert tables == set()
