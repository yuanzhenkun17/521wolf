from __future__ import annotations

from typing import Any

import pytest

from storage.postgres.unit_of_work import (
    UnitOfWork,
    UnitOfWorkBoundaryError,
    evolution,
    registry,
    wolf,
)


class _FakeConnection:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.storage_timezone = "Asia/Shanghai"

    def begin_write(self) -> None:
        self.calls.append("begin_write")

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        self.calls.append("execute")
        return None

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


class _NoBeginWriteConnection:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        self.calls.append("execute")
        return None

    def commit(self) -> None:
        self.calls.append("commit")

    def rollback(self) -> None:
        self.calls.append("rollback")

    def close(self) -> None:
        self.calls.append("close")


class _Provider:
    def __init__(self) -> None:
        self.wolf_conn = _FakeConnection()
        self.registry_conn = _FakeConnection()
        self.evolution_conn = _FakeConnection()

    def open_wolf_connection(self) -> _FakeConnection:
        return self.wolf_conn

    def open_registry_connection(self) -> _FakeConnection:
        return self.registry_conn

    def open_evolution_connection(self) -> _FakeConnection:
        return self.evolution_conn


class _SelfCommittingRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def save(self) -> None:
        self._conn.execute("INSERT INTO sample (id) VALUES (?)", ("one",))
        self._conn.commit()


class _CommitNeutralRepository:
    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def save(self) -> None:
        self._conn.execute("INSERT INTO sample (id) VALUES (?)", ("one",))


def test_unit_of_work_begins_write_transaction_and_commits_once() -> None:
    conn = _FakeConnection()

    with UnitOfWork(lambda: conn) as tx:
        assert tx.conn is tx.connection
        assert tx.conn is not conn
        assert tx.conn.storage_timezone == "Asia/Shanghai"
        tx.conn.execute("SELECT 1")
        tx.commit()

    assert conn.calls == ["begin_write", "execute", "commit", "close"]


def test_unit_of_work_rolls_back_by_default_without_commit() -> None:
    conn = _FakeConnection()

    with UnitOfWork(lambda: conn) as tx:
        assert tx.conn is tx.connection

    assert conn.calls == ["begin_write", "rollback", "close"]


def test_unit_of_work_rolls_back_on_exception_and_closes_owned_connection() -> None:
    conn = _FakeConnection()

    with pytest.raises(RuntimeError, match="boom"):
        with UnitOfWork(lambda: conn):
            raise RuntimeError("boom")

    assert conn.calls == ["begin_write", "rollback", "close"]


def test_unit_of_work_explicit_rollback_prevents_exit_rollback() -> None:
    conn = _FakeConnection()

    with UnitOfWork(lambda: conn) as tx:
        tx.rollback()

    assert conn.calls == ["begin_write", "rollback", "close"]


def test_unit_of_work_does_not_close_provided_connection() -> None:
    conn = _FakeConnection()

    with UnitOfWork(connection=conn) as tx:
        assert tx.conn is not conn
        tx.commit()

    assert conn.calls == ["begin_write", "commit"]


def test_unit_of_work_closes_owned_connection_when_begin_write_fails() -> None:
    conn = _NoBeginWriteConnection()

    with pytest.raises(RuntimeError, match="PostgreSQL storage adapter"):
        with UnitOfWork(lambda: conn):
            pass

    assert conn.calls == ["close"]


def test_unit_of_work_requires_one_connection_source() -> None:
    conn = _FakeConnection()

    with pytest.raises(ValueError, match="exactly one"):
        UnitOfWork()
    with pytest.raises(ValueError, match="exactly one"):
        UnitOfWork(lambda: conn, connection=conn)


def test_unit_of_work_rejects_late_commit_or_reuse() -> None:
    conn = _FakeConnection()
    tx = UnitOfWork(lambda: conn)

    with tx:
        tx.commit()
        with pytest.raises(RuntimeError, match="already finished"):
            tx.commit()
        with pytest.raises(RuntimeError, match="already finished"):
            tx.conn.execute("SELECT 1")

    with pytest.raises(RuntimeError, match="cannot be reused"):
        with tx:
            pass


def test_unit_of_work_connection_rejects_lifecycle_methods() -> None:
    conn = _FakeConnection()

    with UnitOfWork(lambda: conn) as tx:
        for action in (tx.conn.commit, tx.conn.rollback, tx.conn.close, tx.conn.begin_write):
            with pytest.raises(UnitOfWorkBoundaryError, match="UnitOfWork"):
                action()
        with pytest.raises(UnitOfWorkBoundaryError, match="context manager"):
            with tx.conn:
                pass
        tx.commit()

    assert conn.calls == ["begin_write", "commit", "close"]


def test_unit_of_work_rejects_self_committing_repository() -> None:
    conn = _FakeConnection()

    with pytest.raises(UnitOfWorkBoundaryError, match="commit must be called"):
        with UnitOfWork(lambda: conn) as tx:
            _SelfCommittingRepository(tx.conn).save()

    assert conn.calls == ["begin_write", "execute", "rollback", "close"]


def test_unit_of_work_repo_helper_uses_guarded_connection() -> None:
    conn = _FakeConnection()

    with UnitOfWork(lambda: conn) as tx:
        repo = tx.repo(_CommitNeutralRepository)
        repo.save()
        tx.commit()

    assert conn.calls == ["begin_write", "execute", "commit", "close"]


def test_domain_helpers_open_provider_connections() -> None:
    provider = _Provider()

    with wolf(provider=provider) as tx:
        assert tx.conn is not provider.wolf_conn
        tx.commit()
    with registry(provider=provider) as tx:
        assert tx.conn is not provider.registry_conn
        tx.commit()
    with evolution(provider=provider) as tx:
        assert tx.conn is not provider.evolution_conn
        tx.commit()

    assert provider.wolf_conn.calls == ["begin_write", "commit", "close"]
    assert provider.registry_conn.calls == ["begin_write", "commit", "close"]
    assert provider.evolution_conn.calls == ["begin_write", "commit", "close"]
