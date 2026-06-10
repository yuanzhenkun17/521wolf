from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest


pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not os.environ.get("POSTGRES_ADMIN_DATABASE_URL"),
        reason="set POSTGRES_ADMIN_DATABASE_URL to run PostgreSQL integration tests",
    ),
]


@pytest.fixture()
def migrated_postgres_urls() -> Iterator[tuple[str, str]]:
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql
    from sqlalchemy.engine import make_url

    admin_url = make_url(os.environ["POSTGRES_ADMIN_DATABASE_URL"])
    database_name = f"wolf_it_{uuid.uuid4().hex[:16]}"
    admin_psycopg_url = admin_url.set(drivername="postgresql").render_as_string(
        hide_password=False
    )
    app_psycopg_url = admin_url.set(
        drivername="postgresql",
        database=database_name,
    ).render_as_string(hide_password=False)
    app_alembic_url = admin_url.set(
        drivername="postgresql+psycopg",
        database=database_name,
    ).render_as_string(hide_password=False)

    admin_conn = psycopg.connect(admin_psycopg_url, autocommit=True)
    try:
        with admin_conn.cursor() as cursor:
            cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    except Exception as exc:
        admin_conn.close()
        pytest.skip(f"cannot create PostgreSQL integration database: {exc}")

    try:
        env = dict(os.environ)
        env["POSTGRES_DATABASE_URL"] = app_alembic_url
        subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", "head"],
            cwd=Path(__file__).resolve().parent.parent,
            env=env,
            text=True,
            capture_output=True,
            check=True,
            timeout=120,
        )
        yield app_psycopg_url, database_name
    finally:
        with admin_conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = %s AND pid <> pg_backend_pid()
                """,
                (database_name,),
            )
            cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database_name)))
        admin_conn.close()


def test_postgres_domain_factories_use_separate_search_paths(
    migrated_postgres_urls: tuple[str, str],
) -> None:
    from storage.postgres import (
        get_evolution_postgres_connection,
        get_registry_postgres_connection,
        get_wolf_postgres_connection,
    )

    app_url, _ = migrated_postgres_urls
    domains = [
        ("wolf", get_wolf_postgres_connection, "games"),
        ("registry", get_registry_postgres_connection, "role_versions"),
        ("evolution", get_evolution_postgres_connection, "evolution_runs"),
    ]

    for schema, factory, table in domains:
        conn = factory(app_url)
        try:
            row = conn.execute("SELECT current_schema()").fetchone()
            assert row is not None
            assert row[0] == schema
            assert conn.table_exists(table) is True
        finally:
            conn.close()


def test_postgres_factories_support_repository_smoke(
    migrated_postgres_urls: tuple[str, str],
) -> None:
    from storage.evolution.experience_repo import ExperienceCandidateStore
    from storage.postgres import (
        get_evolution_postgres_connection,
        get_registry_postgres_connection,
        get_wolf_postgres_connection,
    )
    from storage.version_store import VersionStoreDB

    app_url, _ = migrated_postgres_urls

    wolf_conn = get_wolf_postgres_connection(app_url)
    try:
        _write_wolf_smoke(wolf_conn)
    finally:
        wolf_conn.close()

    registry_conn = get_registry_postgres_connection(app_url)
    try:
        store = VersionStoreDB(
            registry_conn,
            timestamp_provider=lambda: "2026-06-08T00:00:00+08:00",
        )
        version_id = store.save_version(
            "seer",
            {"main.md": "# skill\n\n- check carefully"},
            parent_hash=None,
            source="pg_smoke",
        )
        assert store.set_baseline("seer", version_id, expected_current=version_id) is True
    finally:
        registry_conn.close()

    evolution_conn = get_evolution_postgres_connection(app_url)
    try:
        repo = ExperienceCandidateStore(
            evolution_conn,
            timestamp_provider=lambda: "2026-06-08T00:00:00+08:00",
        )
        ids = repo.save_candidates(
            "pg-smoke-game",
            [
                {
                    "candidate_id": "pg-smoke-candidate",
                    "role": "seer",
                    "candidate_type": "pattern",
                    "raw": {"ok": True},
                    "evidence_decision_ids": ["d1"],
                }
            ],
            run_type="evolution_training",
            learning_eligible=True,
        )
        assert ids == ["pg-smoke-candidate"]
        row = repo.get_candidate("pg-smoke-game", "pg-smoke-candidate")
        assert row is not None
        assert row["learning_eligible"] == 1
        assert row["raw_json"]["candidate_id"] == "pg-smoke-candidate"
    finally:
        evolution_conn.close()


def test_postgres_provider_supports_game_persistence_runtime_smoke(
    migrated_postgres_urls: tuple[str, str],
) -> None:
    import json

    from storage.interfaces import DecisionRecordData
    from storage.provider import PostgresStorageProvider
    from storage.run_policy import RunType, policy_for_run_type
    from storage.runtime import GamePersistence

    app_url, _ = migrated_postgres_urls
    game_id = "pg-runtime-smoke-game"
    provider = PostgresStorageProvider(app_url)

    with GamePersistence(
        game_id=game_id,
        provider=provider,
        source_game_id="raw-pg-runtime-smoke",
        run_policy=policy_for_run_type(RunType.EVOLUTION_TRAINING),
        run_metadata={"source_run_id": "pg-runtime-run", "mode": "formal"},
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
            seed=20260608,
            player_roles={1: "seer", 2: "werewolf"},
            config={"mode": "pg-runtime"},
            winner="villagers",
            started_at="2026-06-08T00:00:00+08:00",
            finished_at="2026-06-08T00:01:00+08:00",
            total_rounds=1,
            public_events=[event.to_dict() for event in logger.entries if event.public],
            final_state={"winner": "villagers"},
            deaths=[{"player_id": 2, "day": 1, "cause": "werewolf"}],
            final_alive={1: True, 2: False},
        )
        saved = persistence.save_experience_candidates(
            [
                {
                    "candidate_id": "pg-runtime-candidate",
                    "role": "seer",
                    "candidate_type": "decision_pattern",
                    "topic": "night check",
                    "evidence_decision_ids": ["d_check"],
                    "recommendation": "check contested claimants",
                }
            ]
        )
        assert saved == ["pg-runtime-candidate"]

    wolf_conn = provider.open_wolf_connection()
    evolution_conn = provider.open_evolution_connection()
    try:
        game = wolf_conn.execute(
            "SELECT * FROM wolf.games WHERE id = ?",
            (game_id,),
        ).fetchone()
        assert game is not None
        assert json.loads(game["config"])["mode"] == "pg-runtime"
        assert json.loads(game["public_events"])[0]["type"] == "death"
        assert json.loads(game["final_state"])["winner"] == "villagers"
        assert game["learning_eligible"] == 1

        player = wolf_conn.execute(
            "SELECT alive FROM wolf.players WHERE game_id = ? AND seat = ?",
            (game_id, 2),
        ).fetchone()
        assert player is not None
        assert player["alive"] == 0

        event_count = wolf_conn.execute(
            "SELECT COUNT(*) AS n FROM wolf.game_events WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        assert event_count is not None
        assert event_count["n"] == 2

        decision = wolf_conn.execute(
            "SELECT id, selected_skills FROM wolf.decisions WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        assert decision is not None
        assert decision["id"] == f"{game_id}::d_check"
        assert json.loads(decision["selected_skills"]) == ["seer/check.md"]

        candidate = evolution_conn.execute(
            """
            SELECT evidence_decision_ids, learning_eligible, raw_json
            FROM evolution.experience_candidates
            WHERE game_id = ? AND candidate_id = ?
            """,
            (game_id, "pg-runtime-candidate"),
        ).fetchone()
        assert candidate is not None
        assert json.loads(candidate["evidence_decision_ids"]) == [
            f"{game_id}::d_check"
        ]
        assert candidate["learning_eligible"] == 1
        assert json.loads(candidate["raw_json"])["source_evidence_decision_ids"] == [
            "d_check"
        ]

        assert wolf_conn.execute("SELECT to_regclass('wolf.experience_candidates')").fetchone()[0] is None
        assert wolf_conn.execute("SELECT to_regclass('evolution.games')").fetchone()[0] is None
        assert wolf_conn.execute("SELECT to_regclass('evolution.decisions')").fetchone()[0] is None
    finally:
        wolf_conn.close()
        evolution_conn.close()


def test_postgres_delete_game_removes_wolf_runtime_child_rows(
    migrated_postgres_urls: tuple[str, str],
) -> None:
    from storage.battle.report_repo import ReportStore
    from storage.evaluation_store import EvaluationStore
    from storage.game_store import GameStore
    from storage.ids import storage_decision_id
    from storage.interfaces import DecisionRecordData
    from storage.provider import PostgresStorageProvider
    from storage.review_store import CounterfactualStore, DecisionReviewStore
    from storage.run_policy import RunType, policy_for_run_type
    from storage.runtime import GamePersistence

    app_url, _ = migrated_postgres_urls
    game_id = f"pg-delete-game-{uuid.uuid4().hex[:12]}"
    raw_decision_id = "d_vote_1"
    decision_id = storage_decision_id(game_id, raw_decision_id)
    created_at = "2026-06-08T00:00:00+08:00"
    provider = PostgresStorageProvider(app_url)

    with GamePersistence(
        game_id=game_id,
        provider=provider,
        source_game_id="raw-pg-delete-game",
        run_policy=policy_for_run_type(RunType.EVOLUTION_TRAINING),
        run_metadata={"source_run_id": "pg-delete-run", "mode": "formal"},
        commit_every=100,
    ) as persistence:
        logger = persistence.create_event_logger()
        logger.record(
            day=1,
            phase="day",
            event_type="speech",
            message="seer pushes a vote",
            actor=1,
            payload={"topic": "vote"},
        )
        logger.record(
            day=1,
            phase="day",
            event_type="vote",
            message="1 votes 2",
            actor=1,
            target=2,
            payload={"choice": 2},
        )

        sink = persistence.create_decision_sink()
        assert sink is not None
        sink.record_decision(
            DecisionRecordData(
                decision_id=raw_decision_id,
                player_id=1,
                role="seer",
                day=1,
                phase="day",
                action_type="vote",
                selected_target=2,
                public_text="vote 2",
                private_reasoning="2 contradicted earlier claim",
                confidence=0.7,
                selected_skills=["seer/day_vote.md"],
                raw_output='{"target": 2}',
            )
        )

        persistence.save_game_result(
            seed=20260608,
            player_roles={1: "seer", 2: "werewolf"},
            config={"mode": "pg-delete"},
            winner="villagers",
            started_at=created_at,
            finished_at="2026-06-08T00:02:00+08:00",
            total_rounds=1,
            public_events=[event.to_dict() for event in logger.entries if event.public],
            final_state={"winner": "villagers"},
            deaths=[{"player_id": 2, "day": 1, "cause": "vote"}],
            final_alive={1: True, 2: False},
        )

        conn = persistence.conn
        assert conn is not None
        ReportStore(conn).save_report(
            f"{game_id}-report",
            game_id,
            "seer vote created a village win",
            created_at=created_at,
        )
        EvaluationStore(conn).save_evaluation(
            f"{game_id}-eval-1",
            game_id,
            1,
            "seer",
            speech_score=0.8,
            vote_score=0.9,
            skill_score=0.7,
            overall_score=0.8,
            created_at=created_at,
        )
        DecisionReviewStore(conn).save_review(
            f"{game_id}-review-1",
            game_id,
            decision_id,
            1,
            1,
            "day",
            "vote",
            "good",
            reason="pressure matched evidence",
            created_at=created_at,
        )
        CounterfactualStore(conn).save_counterfactual(
            f"{game_id}-cf-1",
            game_id,
            decision_id,
            "what if the seer voted elsewhere",
            likely_outcome="werewolf survives",
            confidence=0.6,
            created_at=created_at,
        )
        judgment_ids = persistence.save_llm_judgments(
            [
                {
                    "decision_id": raw_decision_id,
                    "player_id": 1,
                    "role": "seer",
                    "action_type": "vote",
                    "score": 8,
                    "reason": "valid pressure vote",
                    "created_at": created_at,
                }
            ],
            prompt_version="decision_judge_delete_test_v1",
        )
        assert len(judgment_ids) == 1

    wolf_conn = provider.open_wolf_connection()
    try:
        expected_counts = {
            "games": 1,
            "players": 2,
            "game_events": 2,
            "decisions": 1,
            "reports": 1,
            "evaluations": 1,
            "decision_reviews": 1,
            "counterfactuals": 1,
            "llm_judgments": 1,
        }
        assert _wolf_runtime_row_counts(wolf_conn, game_id) == expected_counts

        wolf_conn.commit()
        GameStore(wolf_conn).delete_game(game_id)

        assert _wolf_runtime_row_counts(wolf_conn, game_id) == {
            table: 0 for table in expected_counts
        }
    finally:
        wolf_conn.close()


def _write_wolf_smoke(conn: Any) -> None:
    import json

    from storage.game_store import GameStore

    game_id = "pg-smoke-game"
    store = GameStore(conn)
    store.insert_game(
        game_id=game_id,
        seed=20260608,
        config={"mode": "pg-smoke", "nested": {"ok": True}},
        winner="good",
        started_at="2026-06-08T00:00:00+08:00",
        finished_at="2026-06-08T00:01:00+08:00",
        public_events=[{"type": "smoke"}],
        final_state={"winner": "good"},
        learning_eligible=1,
        promote_eligible=0,
        run_metadata={"rankable": True, "paired_seed": False},
    )
    store.insert_players(game_id, {1: "seer"}, final_alive={1: False})

    game = store.get_game(game_id)
    player = conn.execute(
        "SELECT alive FROM players WHERE game_id = ? AND seat = ?",
        (game_id, 1),
    ).fetchone()

    assert game is not None
    assert json.loads(game["config"])["nested"]["ok"] is True
    assert json.loads(game["public_events"])[0]["type"] == "smoke"
    assert json.loads(game["final_state"])["winner"] == "good"
    assert game["learning_eligible"] == 1
    assert game["promote_eligible"] == 0
    assert game["rankable"] == 1
    assert game["paired_seed"] == 0
    assert game["started_at"].endswith("+08:00")
    assert player is not None
    assert player["alive"] == 0


def _wolf_runtime_row_counts(conn: Any, game_id: str) -> dict[str, int]:
    game_scoped_tables = (
        "players",
        "game_events",
        "decisions",
        "reports",
        "evaluations",
        "decision_reviews",
        "counterfactuals",
        "llm_judgments",
    )
    counts: dict[str, int] = {}
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM wolf.games WHERE id = ?",
        (game_id,),
    ).fetchone()
    counts["games"] = int(row["n"] if row is not None else 0)
    for table in game_scoped_tables:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM wolf.{table} WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        counts[table] = int(row["n"] if row is not None else 0)
    return counts
