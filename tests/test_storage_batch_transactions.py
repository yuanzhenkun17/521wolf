from __future__ import annotations

from typing import Any

import pytest


class _FakeCursor:
    rowcount = 0

    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = rows or []

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        return list(self._rows)


class _TransactionalConn:
    def __init__(self, *, fail_on_execute: int | None = None) -> None:
        self.fail_on_execute = fail_on_execute
        self.exec_count = 0
        self.sql: list[str] = []
        self.params: list[tuple[Any, ...]] = []
        self.entered = 0
        self.exit_args: list[tuple[Any, Any, Any]] = []
        self.begin_writes = 0
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def __enter__(self) -> "_TransactionalConn":
        self.entered += 1
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.exit_args.append((exc_type, exc, tb))
        if exc_type is None:
            self.commits += 1
        else:
            self.rollbacks += 1

    def execute(self, sql: str, parameters: Any = ()) -> _FakeCursor:
        self.exec_count += 1
        if self.fail_on_execute == self.exec_count:
            raise RuntimeError("write failed")
        self.sql.append(" ".join(sql.split()))
        self.params.append(tuple(parameters))
        return _FakeCursor()

    def begin_write(self) -> None:
        self.begin_writes += 1

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closes += 1


def test_evaluation_save_batch_uses_single_storage_transaction() -> None:
    from storage.battle.evaluation_repo import EvaluationStore

    conn = _TransactionalConn()
    store = EvaluationStore(
        conn,  # type: ignore[arg-type]
        timestamp_provider=lambda: "2026-01-01T00:00:00+08:00",
    )

    saved = store.save_batch(
        [
            {"id": "ev1", "game_id": "g1", "player_seat": 1, "role": "seer"},
            {"id": "ev2", "game_id": "g1", "player_seat": 2, "role": "werewolf"},
        ]
    )

    assert saved == ["ev1", "ev2"]
    assert conn.entered == 1
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert len(conn.sql) == 2
    assert all("INSERT INTO evaluations" in sql for sql in conn.sql)


def test_game_delete_uses_single_storage_transaction_and_child_order() -> None:
    from storage.game_store import GameStore, WOLF_GAME_CHILD_TABLES

    conn = _TransactionalConn()
    store = GameStore(conn)  # type: ignore[arg-type]

    store.delete_game("game-delete-1")

    expected_sql = [
        f"DELETE FROM {table} WHERE game_id = ?"
        for table in WOLF_GAME_CHILD_TABLES
    ]
    expected_sql.append("DELETE FROM games WHERE id = ?")
    assert conn.begin_writes == 1
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.sql == expected_sql
    assert conn.params == [("game-delete-1",)] * len(expected_sql)


def test_game_delete_rolls_back_on_child_delete_failure() -> None:
    from storage.game_store import GameStore

    conn = _TransactionalConn(fail_on_execute=3)
    store = GameStore(conn)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="write failed"):
        store.delete_game("game-delete-1")

    assert conn.begin_writes == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_game_delete_can_defer_transaction_to_caller() -> None:
    from storage.game_store import GameStore, WOLF_GAME_CHILD_TABLES

    conn = _TransactionalConn()
    store = GameStore(conn, autocommit=False)  # type: ignore[arg-type]

    store.delete_game("game-delete-1")

    assert conn.begin_writes == 0
    assert conn.commits == 0
    assert conn.rollbacks == 0
    assert len(conn.sql) == len(WOLF_GAME_CHILD_TABLES) + 1


def test_benchmark_evaluation_helpers_own_write_transactions() -> None:
    from storage.benchmark.evaluation_repo import (
        persist_leaderboard_entry,
        save_evaluation_batch,
    )

    conn = _TransactionalConn()

    batch_warning = save_evaluation_batch(conn, {"batch_id": "batch-1"})
    leaderboard_warning = persist_leaderboard_entry(
        conn,
        {"batch_id": "batch-1", "model_id": "model-a"},
    )

    assert batch_warning is None
    assert leaderboard_warning is None
    assert conn.begin_writes == 2
    assert conn.commits == 2
    assert conn.rollbacks == 0
    assert any("INSERT INTO evaluation_batches" in sql for sql in conn.sql)
    assert any("INSERT INTO benchmark_leaderboard" in sql for sql in conn.sql)


def test_benchmark_leaderboard_helper_rolls_back_on_write_error() -> None:
    from storage.benchmark.evaluation_repo import PersistenceWarning, persist_leaderboard_entry

    conn = _TransactionalConn(fail_on_execute=1)

    warning = persist_leaderboard_entry(
        conn,
        {"batch_id": "batch-1", "model_id": "model-a"},
    )

    assert isinstance(warning, PersistenceWarning)
    assert "persist_leaderboard_entry failed: RuntimeError: write failed" in warning
    assert conn.begin_writes == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1


def test_benchmark_uow_rolls_back_combined_writes_on_later_failure() -> None:
    from storage.benchmark.evaluation_repo import BenchmarkEvaluationRepository
    from storage.postgres.unit_of_work import UnitOfWork

    conn = _TransactionalConn(fail_on_execute=2)

    with pytest.raises(RuntimeError, match="write failed"):
        with UnitOfWork(lambda: conn) as tx:
            repo = BenchmarkEvaluationRepository(tx.connection, autocommit=False)
            repo.save_batch({"batch_id": "batch-1"})
            repo.save_leaderboard_entry(
                {"batch_id": "batch-1", "model_id": "model-a"}
            )
            tx.commit()

    assert conn.begin_writes == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1
    assert conn.closes == 1
    assert len(conn.sql) == 1
    assert "INSERT INTO evaluation_batches" in conn.sql[0]


def test_benchmark_uow_default_repo_defers_commit_to_owned_transaction() -> None:
    from storage.benchmark.batch_repo import BenchmarkBatchRepository
    from storage.postgres.unit_of_work import UnitOfWork

    conn = _TransactionalConn()

    with UnitOfWork(lambda: conn) as tx:
        BenchmarkBatchRepository(tx.connection).save({"batch_id": "batch-1"})
        assert conn.commits == 0
        tx.commit()

    assert conn.begin_writes == 1
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.closes == 1
    assert len(conn.sql) == 1
    assert "INSERT INTO evaluation_batches" in conn.sql[0]


def test_benchmark_uow_rejects_explicit_autocommit_repo_inside_owned_transaction() -> None:
    from storage.benchmark.evaluation_repo import BenchmarkEvaluationRepository
    from storage.postgres.unit_of_work import UnitOfWork, UnitOfWorkBoundaryError

    conn = _TransactionalConn()

    with pytest.raises(
        UnitOfWorkBoundaryError,
        match="commit must be called on UnitOfWork",
    ):
        with UnitOfWork(lambda: conn) as tx:
            BenchmarkEvaluationRepository(tx.connection, autocommit=True).save_batch(
                {"batch_id": "batch-1"}
            )

    assert conn.begin_writes == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1
    assert conn.closes == 1
    assert len(conn.sql) == 1
    assert "INSERT INTO evaluation_batches" in conn.sql[0]


def test_delete_game_from_provider_opens_and_closes_connection() -> None:
    from storage.game_store import WOLF_GAME_CHILD_TABLES, delete_game_from_provider

    conn = _TransactionalConn()

    class _Provider:
        def __init__(self) -> None:
            self.opens = 0

        def open_wolf_connection(self) -> _TransactionalConn:
            self.opens += 1
            return conn

    provider = _Provider()

    delete_game_from_provider(provider, "game-delete-1")

    expected_sql = [
        f"DELETE FROM {table} WHERE game_id = ?"
        for table in WOLF_GAME_CHILD_TABLES
    ]
    expected_sql.append("DELETE FROM games WHERE id = ?")
    assert provider.opens == 1
    assert conn.sql == expected_sql
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert conn.closes == 1


def test_delete_game_from_provider_closes_connection_on_delete_failure() -> None:
    from storage.game_store import delete_game_from_provider

    conn = _TransactionalConn(fail_on_execute=2)

    class _Provider:
        def open_wolf_connection(self) -> _TransactionalConn:
            return conn

    with pytest.raises(RuntimeError, match="write failed"):
        delete_game_from_provider(_Provider(), "game-delete-1")

    assert conn.begin_writes == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1
    assert conn.closes == 1


def test_delete_game_from_env_resolves_provider_with_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import storage.provider as provider_mod
    from storage.game_store import WOLF_GAME_CHILD_TABLES, delete_game_from_env

    conn = _TransactionalConn()
    calls: list[Any] = []

    class _Provider:
        def open_wolf_connection(self) -> _TransactionalConn:
            return conn

    def provider_from_env(*, paths: Any = None) -> _Provider:
        calls.append(paths)
        return _Provider()

    paths = object()
    monkeypatch.setattr(provider_mod, "storage_provider_from_env", provider_from_env)

    delete_game_from_env("game-delete-1", paths=paths)

    expected_sql = [
        f"DELETE FROM {table} WHERE game_id = ?"
        for table in WOLF_GAME_CHILD_TABLES
    ]
    expected_sql.append("DELETE FROM games WHERE id = ?")
    assert calls == [paths]
    assert conn.sql == expected_sql
    assert conn.commits == 1
    assert conn.closes == 1


def test_delete_game_from_env_resolves_provider_without_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    import storage.provider as provider_mod
    from storage.game_store import WOLF_GAME_CHILD_TABLES, delete_game_from_env

    conn = _TransactionalConn()
    calls = 0

    class _Provider:
        def open_wolf_connection(self) -> _TransactionalConn:
            return conn

    def provider_from_env() -> _Provider:
        nonlocal calls
        calls += 1
        return _Provider()

    monkeypatch.setattr(provider_mod, "storage_provider_from_env", provider_from_env)

    delete_game_from_env("game-delete-1")

    expected_sql = [
        f"DELETE FROM {table} WHERE game_id = ?"
        for table in WOLF_GAME_CHILD_TABLES
    ]
    expected_sql.append("DELETE FROM games WHERE id = ?")
    assert calls == 1
    assert conn.sql == expected_sql
    assert conn.commits == 1
    assert conn.closes == 1


def test_evaluation_save_batch_rolls_back_whole_batch_on_failure() -> None:
    from storage.battle.evaluation_repo import EvaluationStore

    conn = _TransactionalConn(fail_on_execute=2)
    store = EvaluationStore(
        conn,  # type: ignore[arg-type]
        timestamp_provider=lambda: "2026-01-01T00:00:00+08:00",
    )

    with pytest.raises(RuntimeError, match="write failed"):
        store.save_batch(
            [
                {"id": "ev1", "game_id": "g1", "player_seat": 1, "role": "seer"},
                {"id": "ev2", "game_id": "g1", "player_seat": 2, "role": "werewolf"},
            ]
        )

    assert conn.entered == 1
    assert conn.commits == 0
    assert conn.rollbacks == 1
    assert conn.exit_args[0][0] is RuntimeError


def test_review_and_counterfactual_batches_use_transactions() -> None:
    from storage.battle.review_repo import CounterfactualStore, DecisionReviewStore

    conn = _TransactionalConn()
    reviews = DecisionReviewStore(
        conn,  # type: ignore[arg-type]
        timestamp_provider=lambda: "2026-01-01T00:00:00+08:00",
    )
    counterfactuals = CounterfactualStore(
        conn,  # type: ignore[arg-type]
        timestamp_provider=lambda: "2026-01-01T00:00:00+08:00",
    )

    assert reviews.save_batch(
        [
            {
                "id": "r1",
                "game_id": "g1",
                "decision_id": "d1",
                "player_seat": 1,
                "day": 1,
                "phase": "day",
                "action_type": "vote",
                "quality": "good",
            }
        ]
    ) == ["r1"]
    assert counterfactuals.save_batch(
        [
            {
                "id": "cf1",
                "game_id": "g1",
                "decision_id": "d1",
                "what_if": "vote 2",
                "confidence": 0.7,
            }
        ]
    ) == ["cf1"]

    assert conn.entered == 2
    assert conn.commits == 2
    assert any("INSERT INTO decision_reviews" in sql for sql in conn.sql)
    assert any("INSERT INTO counterfactuals" in sql for sql in conn.sql)


def test_experience_save_candidates_uses_transaction_and_pg_upsert() -> None:
    from storage.evolution.experience_repo import ExperienceCandidateStore

    conn = _TransactionalConn()
    store = ExperienceCandidateStore(
        conn,  # type: ignore[arg-type]
        timestamp_provider=lambda: "2026-01-01T00:00:00+08:00",
    )

    saved = store.save_candidates(
        "g1",
        [
            {
                "role": "seer",
                "candidate_type": "decision",
                "topic": "night check",
                "recommendation": "check contested players",
            }
        ],
        run_type="evolution_training",
        learning_eligible=True,
    )

    assert saved == ["g1_candidate_001"]
    assert conn.entered == 1
    assert conn.commits == 1
    assert "INSERT INTO experience_candidates" in conn.sql[0]
    assert "ON CONFLICT(game_id, candidate_id) DO UPDATE SET" in conn.sql[0]


def test_evolution_save_proposals_uses_transaction() -> None:
    from storage.evolution.run_repo import EvolutionStore
    from storage.interfaces import SkillProposalData

    class _Evidence:
        def __init__(self, game_id: str) -> None:
            self.game_id = game_id

        def to_dict(self) -> dict[str, str]:
            return {"game_id": self.game_id}

    conn = _TransactionalConn()
    store = EvolutionStore(conn)  # type: ignore[arg-type]

    store.save_proposals(
        [
            SkillProposalData(
                proposal_id="p1",
                target_file="seer/vote.md",
                action_type="append_rule",
                content="Wait for evidence.",
                rationale="two games",
                confidence=0.8,
                risk="low",
                expected_metric="role_score",
                expected_direction="improve",
                evidence=[_Evidence("g1")],
            )
        ],
        source_version_id="baseline_v1",
    )

    assert conn.entered == 1
    assert conn.commits == 1
    assert len(conn.sql) == 1
    assert "INSERT INTO skill_proposals" in conn.sql[0]
