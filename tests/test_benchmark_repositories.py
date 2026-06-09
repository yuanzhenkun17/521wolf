from __future__ import annotations

from typing import Any

from storage.benchmark.saved_view_repo import BenchmarkSavedViewRepository
from storage.benchmark.snapshot_repo import BenchmarkSnapshotRepository
from storage.postgres.unit_of_work import UnitOfWork


class _Cursor:
    def __init__(self, *, rowcount: int = 0) -> None:
        self.rowcount = rowcount

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


class _Connection:
    def __init__(self, *, rowcount: int = 1, fail_execute: bool = False) -> None:
        self.calls: list[str] = []
        self.rowcount = rowcount
        self.fail_execute = fail_execute

    def begin_write(self) -> None:
        self.calls.append("begin_write")

    def execute(self, sql: str, parameters: Any = ()) -> _Cursor:
        self.calls.append("execute")
        if self.fail_execute:
            raise RuntimeError("write failed")
        return _Cursor(rowcount=self.rowcount)

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
