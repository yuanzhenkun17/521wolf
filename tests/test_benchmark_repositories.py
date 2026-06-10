from __future__ import annotations

from typing import Any

from storage.benchmark.batch_repo import BenchmarkBatchRepository
from storage.benchmark.evaluation_repo import (
    BenchmarkEvaluationRepository,
    PersistenceWarning,
    persist_leaderboard_entry,
    save_evaluation_batch,
)
from storage.benchmark.leaderboard_repo import BenchmarkLeaderboardRepository
from storage.benchmark.saved_view_repo import (
    BenchmarkSavedViewRepository,
    delete_benchmark_saved_view,
    persist_benchmark_saved_view,
)
from storage.benchmark.snapshot_repo import (
    BenchmarkSnapshotRepository,
    persist_benchmark_snapshot,
)


class _Cursor:
    def __init__(self, rows: list[Any] | None = None, *, rowcount: int = 0) -> None:
        self.rowcount = rowcount
        self._rows = rows or []

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return list(self._rows)


class _Connection:
    def __init__(
        self,
        *,
        rowcount: int = 1,
        fail_execute: bool = False,
        fail_commit: bool = False,
        rows: list[Any] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self.rowcount = rowcount
        self.fail_execute = fail_execute
        self.fail_commit = fail_commit
        self.rows = rows or []

    def begin_write(self) -> None:
        self.calls.append("begin_write")

    def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
        self.calls.append("execute")
        self.executions.append((sql, tuple(parameters)))
        if self.fail_execute:
            raise RuntimeError("write failed")
        return _Cursor(self.rows, rowcount=self.rowcount)

    def commit(self) -> None:
        self.calls.append("commit")
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


def _snapshot() -> dict[str, Any]:
    return {
        "snapshot_id": "snap-1",
        "title": "Release",
        "release_notes": "notes",
        "scope": "role_version",
        "benchmark_id": "role-baseline-v1",
        "benchmark_version": 1,
        "evaluation_set_id": "role-baseline-v1@v1",
        "seed_set_id": "role-baseline-quick-202606",
        "benchmark_config_hash": "sha256:contract",
        "target_role": "seer",
        "source_filter": {"rankable": "rankable"},
        "view_config": {"columns": ["score"]},
        "rows": [{"subject_id": "seer_candidate_v2"}],
        "summary": {"row_count": 1},
        "row_count": 1,
        "content_hash": "sha256:content",
        "created_at": "2026-06-10T00:00:00+08:00",
    }


def _view() -> dict[str, Any]:
    return {
        "view_key": "view-1",
        "name": "Release reviewer",
        "scope": "role_version",
        "benchmark_id": "role-baseline-v1",
        "evaluation_set_id": "role-baseline-v1@v1",
        "target_role": "seer",
        "view_config": {"columns": ["score"]},
        "created_at": "2026-06-10T00:00:00+08:00",
        "updated_at": "2026-06-10T00:00:00+08:00",
    }


def test_benchmark_snapshot_repository_default_autocommits() -> None:
    conn = _Connection()

    BenchmarkSnapshotRepository(conn).save(_snapshot())  # type: ignore[arg-type]

    assert conn.calls == ["execute", "commit"]


def test_benchmark_saved_view_repository_default_autocommits() -> None:
    conn = _Connection()

    deleted = BenchmarkSavedViewRepository(conn).delete("view-1")  # type: ignore[arg-type]
    BenchmarkSavedViewRepository(conn).save(_view())  # type: ignore[arg-type]

    assert deleted is True
    assert conn.calls == ["execute", "commit", "execute", "commit"]


def test_benchmark_batch_repository_autocommit_can_be_deferred() -> None:
    conn = _Connection()

    BenchmarkBatchRepository(conn, autocommit=False).save({"batch_id": "batch-1"})  # type: ignore[arg-type]

    assert conn.calls == ["execute"]


def test_benchmark_leaderboard_repository_autocommit_can_be_deferred() -> None:
    conn = _Connection()

    BenchmarkLeaderboardRepository(conn, autocommit=False).save(  # type: ignore[arg-type]
        {"batch_id": "batch-1", "model_id": "model-a"}
    )

    assert conn.calls == ["execute"]


def test_benchmark_storage_helpers_commit_with_unit_of_work() -> None:
    conn = _Connection()

    persist_benchmark_snapshot(lambda: conn, _snapshot())
    persist_benchmark_saved_view(lambda: conn, _view())
    deleted = delete_benchmark_saved_view(lambda: conn, "view-1")

    assert deleted is True
    assert conn.calls == [
        "begin_write",
        "execute",
        "commit",
        "close",
        "begin_write",
        "execute",
        "commit",
        "close",
        "begin_write",
        "execute",
        "commit",
        "close",
    ]


def test_benchmark_storage_helper_rolls_back_on_write_error() -> None:
    conn = _Connection(fail_execute=True)

    try:
        persist_benchmark_snapshot(lambda: conn, _snapshot())
    except RuntimeError as exc:
        assert str(exc) == "write failed"
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("write failure did not propagate")

    assert conn.calls == ["begin_write", "execute", "rollback", "close"]


def test_benchmark_leaderboard_repository_lists_rows_with_filters() -> None:
    row = {"subject_id": "seer_candidate_v2"}
    conn = _Connection(rows=[row])

    rows = BenchmarkLeaderboardRepository(conn).list(
        scope="role_version",
        evaluation_set_id="role-baseline-v1@v1",
        target_role="seer",
        limit=999,
    )

    assert rows == [row]
    assert conn.calls == ["execute"]
    sql, params = conn.executions[0]
    assert "FROM benchmark_leaderboard" in sql
    assert "AND scope = ?" in sql
    assert "AND evaluation_set_id = ?" in sql
    assert "AND target_role = ?" in sql
    assert "ORDER BY rankable DESC, strength_score DESC, avg_role_score DESC, updated_at DESC" in sql
    assert "LIMIT ?" in sql
    assert params == ("role_version", "role-baseline-v1@v1", "seer", 500)


def test_benchmark_leaderboard_repository_lists_role_rows_newest_first() -> None:
    row = {"target_role": "seer", "target_version_id": "seer_candidate_v2"}
    conn = _Connection(rows=[row])

    rows = BenchmarkLeaderboardRepository(conn).list_role_rows_for_roles(
        ["seer", "witch"],
        evaluation_set_id="role-baseline-v1@v1",
    )

    assert rows == [row]
    sql, params = conn.executions[0]
    assert "WHERE scope = 'role_version' AND target_role IN (?, ?)" in sql
    assert "AND evaluation_set_id = ?" in sql
    assert "ORDER BY updated_at DESC" in sql
    assert params == ("seer", "witch", "role-baseline-v1@v1")


def test_benchmark_leaderboard_repository_skips_empty_role_list() -> None:
    conn = _Connection()

    rows = BenchmarkLeaderboardRepository(conn).list_role_rows_for_roles([])

    assert rows == []
    assert conn.calls == []


def test_benchmark_batch_repository_loads_comparison_group_rows() -> None:
    conn = _Connection(
        rows=[
            {
                "id": "batch-2",
                "comparison_group_id": "group-1",
                "comparison_type": "model",
            }
        ]
    )

    rows = BenchmarkBatchRepository(conn).load_comparison_group(
        "group-1",
        exclude_batch_id="batch-1",
    )

    assert rows == [
        {
            "id": "batch-2",
            "comparison_group_id": "group-1",
            "comparison_type": "model",
            "batch_id": "batch-2",
        }
    ]
    sql, params = conn.executions[0]
    assert "FROM evaluation_batches WHERE comparison_group_id = ? AND id != ?" in sql
    assert params == ("group-1", "batch-1")


def test_benchmark_evaluation_repository_remains_compatible_facade() -> None:
    row = {"target_role": "seer", "target_version_id": "seer_candidate_v2"}
    conn = _Connection(rows=[row])

    rows = BenchmarkEvaluationRepository(conn).list_role_leaderboard_rows_for_roles(["seer"])

    assert rows == [row]
    assert conn.calls == ["execute"]


def test_benchmark_evaluation_facade_batch_warning_rolls_back() -> None:
    conn = _Connection(fail_execute=True)

    warning = save_evaluation_batch(conn, {"batch_id": "warn_batch"})

    assert isinstance(warning, PersistenceWarning)
    assert warning == "save_evaluation_batch failed: RuntimeError: write failed"
    assert warning.diagnostic == {
        "kind": "persistence_error",
        "stage": "persist_batch.save_evaluation_batch",
        "level": "warning",
        "message": "save_evaluation_batch failed: RuntimeError: write failed",
        "exception_type": "RuntimeError",
        "exception_message": "write failed",
    }
    assert conn.calls == ["begin_write", "execute", "rollback"]


def test_benchmark_evaluation_facade_commit_warning_rolls_back() -> None:
    conn = _Connection(fail_commit=True)

    warning = save_evaluation_batch(conn, {"batch_id": "warn_batch"})

    assert isinstance(warning, PersistenceWarning)
    assert warning == "save_evaluation_batch failed: RuntimeError: commit failed"
    assert warning.diagnostic["stage"] == "persist_batch.save_evaluation_batch"
    assert warning.diagnostic["exception_message"] == "commit failed"
    assert conn.calls == ["begin_write", "execute", "commit", "rollback"]


def test_benchmark_evaluation_facade_leaderboard_warning_keeps_diagnostic() -> None:
    conn = _Connection(fail_execute=True)

    warning = persist_leaderboard_entry(conn, {"batch_id": "warn_batch"})

    assert isinstance(warning, PersistenceWarning)
    assert warning == "persist_leaderboard_entry failed: RuntimeError: write failed"
    assert warning.diagnostic == {
        "kind": "persistence_error",
        "stage": "persist_batch.persist_leaderboard_entry",
        "level": "warning",
        "message": "persist_leaderboard_entry failed: RuntimeError: write failed",
        "exception_type": "RuntimeError",
        "exception_message": "write failed",
    }
    assert conn.calls == ["begin_write", "execute", "rollback"]


def test_score_persistence_facade_delegates_to_storage(monkeypatch) -> None:
    import app.lib.score as score_lib
    import storage.benchmark.evaluation_repo as evaluation_repo

    calls: list[tuple[str, Any]] = []

    class _Conn:
        pass

    conn = _Conn()

    def fake_open_eval_connection(paths: Any = None) -> _Conn:
        calls.append(("open", paths))
        return conn

    def fake_open_benchmark_connection(paths: Any = None) -> _Conn:
        calls.append(("open_benchmark", paths))
        return conn

    def fake_save_evaluation_batch(conn_arg: Any, batch: dict[str, Any]) -> str | None:
        calls.append(("save", (conn_arg, batch)))
        return None

    def fake_persist_leaderboard_entry(conn_arg: Any, entry: dict[str, Any]) -> str | None:
        calls.append(("leaderboard", (conn_arg, entry)))
        return None

    def fake_load_comparison_group(
        conn_arg: Any,
        comparison_group_id: str,
        *,
        exclude_batch_id: str = "",
    ) -> list[dict[str, Any]]:
        calls.append(("load", (conn_arg, comparison_group_id, exclude_batch_id)))
        return [{"batch_id": "sibling"}]

    monkeypatch.setattr(evaluation_repo, "open_eval_connection", fake_open_eval_connection)
    monkeypatch.setattr(evaluation_repo, "open_benchmark_connection", fake_open_benchmark_connection)
    monkeypatch.setattr(evaluation_repo, "save_evaluation_batch", fake_save_evaluation_batch)
    monkeypatch.setattr(evaluation_repo, "persist_leaderboard_entry", fake_persist_leaderboard_entry)
    monkeypatch.setattr(evaluation_repo, "load_comparison_group", fake_load_comparison_group)

    paths = object()
    batch = {"batch_id": "batch-1"}
    entry = {"batch_id": "batch-1"}

    assert score_lib.BenchmarkBatchRepository is evaluation_repo.BenchmarkBatchRepository
    assert score_lib.BenchmarkLeaderboardRepository is evaluation_repo.BenchmarkLeaderboardRepository
    assert score_lib.PersistenceWarning is evaluation_repo.PersistenceWarning
    assert score_lib.open_eval_connection(paths) is conn
    assert score_lib.open_benchmark_connection(paths) is conn
    assert score_lib.save_evaluation_batch(conn, batch) is None
    assert score_lib.persist_leaderboard_entry(conn, entry) is None
    assert score_lib.load_comparison_group(conn, "group-1", exclude_batch_id="batch-1") == [{"batch_id": "sibling"}]
    assert calls == [
        ("open", paths),
        ("open_benchmark", paths),
        ("save", (conn, batch)),
        ("leaderboard", (conn, entry)),
        ("load", (conn, "group-1", "batch-1")),
    ]
