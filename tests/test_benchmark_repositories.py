from __future__ import annotations

from typing import Any

from storage.benchmark.batch_repo import BenchmarkBatchRepository
from storage.benchmark.evaluation_repo import BenchmarkEvaluationRepository
from storage.benchmark.leaderboard_repo import BenchmarkLeaderboardRepository
from storage.benchmark.saved_view_repo import BenchmarkSavedViewRepository
from storage.benchmark.snapshot_repo import BenchmarkSnapshotRepository
from storage.postgres.unit_of_work import UnitOfWork


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
        rows: list[Any] | None = None,
    ) -> None:
        self.calls: list[str] = []
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self.rowcount = rowcount
        self.fail_execute = fail_execute
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


def test_benchmark_repositories_can_be_committed_by_unit_of_work() -> None:
    conn = _Connection()

    with UnitOfWork(lambda: conn) as tx:
        BenchmarkSnapshotRepository(tx.connection, autocommit=False).save(_snapshot())
        BenchmarkSavedViewRepository(tx.connection, autocommit=False).save(_view())
        deleted = BenchmarkSavedViewRepository(tx.connection, autocommit=False).delete("view-1")
        tx.commit()

    assert deleted is True
    assert conn.calls == [
        "begin_write",
        "execute",
        "execute",
        "execute",
        "commit",
        "close",
    ]


def test_benchmark_repository_unit_of_work_rolls_back_on_write_error() -> None:
    conn = _Connection(fail_execute=True)

    try:
        with UnitOfWork(lambda: conn) as tx:
            BenchmarkSnapshotRepository(tx.connection, autocommit=False).save(_snapshot())
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
