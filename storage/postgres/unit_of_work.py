"""Explicit transaction scopes for PostgreSQL-backed storage repositories."""

from __future__ import annotations

from collections.abc import Callable
from types import TracebackType
from typing import Any, TypeVar

from storage.shared.database import StorageConnection, begin_write


ConnectionFactory = Callable[[], StorageConnection]
RepositoryT = TypeVar("RepositoryT")


class UnitOfWorkBoundaryError(RuntimeError):
    """Raised when code inside a UnitOfWork tries to own the transaction."""


class UnitOfWorkConnection:
    """Guarded repository-facing view of a UnitOfWork connection."""

    def __init__(self, unit_of_work: UnitOfWork) -> None:
        self._unit_of_work = unit_of_work

    def execute(self, sql: str, parameters: Any = (), /) -> Any:
        return self._unit_of_work._connection_or_raise().execute(sql, parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._unit_of_work._connection_or_raise(), name)

    def commit(self) -> None:
        raise UnitOfWorkBoundaryError("commit must be called on UnitOfWork")

    def rollback(self) -> None:
        raise UnitOfWorkBoundaryError("rollback must be called on UnitOfWork")

    def close(self) -> None:
        raise UnitOfWorkBoundaryError("close must be called on UnitOfWork")

    def __enter__(self) -> UnitOfWorkConnection:
        raise UnitOfWorkBoundaryError(
            "UnitOfWork connection cannot be used as a context manager"
        )

    def __exit__(self, exc_type: object, exc: object, tb: object) -> object:
        raise UnitOfWorkBoundaryError(
            "UnitOfWork connection cannot be used as a context manager"
        )

    def insert_returning_id(
        self,
        sql: str,
        parameters: Any = (),
        *,
        id_column: str = "id",
    ) -> int:
        custom = getattr(
            self._unit_of_work._connection_or_raise(),
            "insert_returning_id",
            None,
        )
        if callable(custom):
            return int(custom(sql, parameters, id_column=id_column))
        raise RuntimeError("insert_returning_id requires a PostgreSQL storage adapter")

    def begin_write(self) -> None:
        raise UnitOfWorkBoundaryError("begin_write must be called on UnitOfWork")

    def execute_for_update(self, sql: str, parameters: Any = ()) -> Any:
        custom = getattr(
            self._unit_of_work._connection_or_raise(),
            "execute_for_update",
            None,
        )
        if callable(custom):
            return custom(sql, parameters)
        raise RuntimeError("execute_for_update requires a PostgreSQL storage adapter")

    def table_exists(self, table_name: str) -> bool:
        custom = getattr(
            self._unit_of_work._connection_or_raise(),
            "table_exists",
            None,
        )
        if callable(custom):
            return bool(custom(table_name))
        raise RuntimeError("table_exists requires a PostgreSQL storage adapter")

    def table_columns(self, table_name: str) -> Any:
        custom = getattr(
            self._unit_of_work._connection_or_raise(),
            "table_columns",
            None,
        )
        if callable(custom):
            return custom(table_name)
        raise RuntimeError("table_columns requires a PostgreSQL storage adapter")

    def add_column(self, table_name: str, column_name: str, declaration: str) -> None:
        custom = getattr(
            self._unit_of_work._connection_or_raise(),
            "add_column",
            None,
        )
        if callable(custom):
            custom(table_name, column_name, declaration)
            return
        raise RuntimeError("add_column requires a PostgreSQL storage adapter")

    def record_schema_version(
        self,
        component: str,
        version: int,
        applied_at: str,
    ) -> None:
        custom = getattr(
            self._unit_of_work._connection_or_raise(),
            "record_schema_version",
            None,
        )
        if callable(custom):
            custom(component, int(version), applied_at)
            return
        raise RuntimeError("record_schema_version requires a PostgreSQL storage adapter")


class UnitOfWork:
    """Own a single write transaction across one storage connection.

    Repositories used inside this scope should not commit by themselves. The
    caller must explicitly call :meth:`commit`; otherwise the scope rolls back
    on exit, even when no exception occurred.
    """

    def __init__(
        self,
        connection_factory: ConnectionFactory | None = None,
        *,
        connection: StorageConnection | None = None,
    ) -> None:
        if (connection_factory is None) == (connection is None):
            raise ValueError("UnitOfWork requires exactly one connection source")
        self._connection_factory = connection_factory
        self._provided_connection = connection
        self._connection: StorageConnection | None = None
        self._guarded_connection = UnitOfWorkConnection(self)
        self._owns_connection = connection_factory is not None
        self._active = False
        self._finished = False
        self._used = False

    @property
    def conn(self) -> UnitOfWorkConnection:
        return self.connection

    @property
    def connection(self) -> UnitOfWorkConnection:
        self._connection_or_raise()
        return self._guarded_connection

    def repo(self, repository_factory: Callable[[UnitOfWorkConnection], RepositoryT]) -> RepositoryT:
        return repository_factory(self.connection)

    def __enter__(self) -> UnitOfWork:
        if self._used:
            raise RuntimeError("UnitOfWork cannot be reused")
        self._used = True
        self._connection = self._open_connection()
        try:
            begin_write(self._connection)
        except BaseException:
            self.close()
            raise
        self._active = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        try:
            if self._active and not self._finished:
                self._connection_or_raise().rollback()
                self._finished = True
        finally:
            self._active = False
            self.close()
        return False

    def commit(self) -> None:
        if self._finished:
            raise RuntimeError("UnitOfWork transaction already finished")
        self._connection_or_raise().commit()
        self._finished = True

    def rollback(self) -> None:
        if self._finished:
            raise RuntimeError("UnitOfWork transaction already finished")
        self._connection_or_raise().rollback()
        self._finished = True

    def close(self) -> None:
        if self._active and not self._finished and self._connection is not None:
            self._connection.rollback()
            self._finished = True
        if self._owns_connection and self._connection is not None:
            self._connection.close()
        self._connection = None

    def _open_connection(self) -> StorageConnection:
        if self._connection_factory is not None:
            return self._connection_factory()
        if self._provided_connection is None:
            raise RuntimeError("UnitOfWork has no connection source")
        return self._provided_connection

    def _connection_or_raise(self) -> StorageConnection:
        if self._finished:
            raise RuntimeError("UnitOfWork transaction already finished")
        if not self._active or self._connection is None:
            raise RuntimeError("UnitOfWork is not active")
        return self._connection


PostgresUnitOfWork = UnitOfWork


def from_connection(connection: StorageConnection) -> UnitOfWork:
    return UnitOfWork(connection=connection)


def from_connection_factory(connection_factory: ConnectionFactory) -> UnitOfWork:
    return UnitOfWork(connection_factory)


def wolf(*, provider: Any | None = None, paths: Any | None = None) -> UnitOfWork:
    return UnitOfWork(_provider_connection_factory("open_wolf_connection", provider, paths))


def registry(*, provider: Any | None = None, paths: Any | None = None) -> UnitOfWork:
    return UnitOfWork(_provider_connection_factory("open_registry_connection", provider, paths))


def evolution(*, provider: Any | None = None, paths: Any | None = None) -> UnitOfWork:
    return UnitOfWork(_provider_connection_factory("open_evolution_connection", provider, paths))


def _provider_connection_factory(
    method_name: str,
    provider: Any | None,
    paths: Any | None,
) -> ConnectionFactory:
    def open_connection() -> StorageConnection:
        resolved_provider = provider
        if resolved_provider is None:
            from storage.provider import storage_provider_from_env

            resolved_provider = storage_provider_from_env(paths=paths)
        return getattr(resolved_provider, method_name)()

    return open_connection


__all__ = [
    "ConnectionFactory",
    "PostgresUnitOfWork",
    "UnitOfWorkBoundaryError",
    "UnitOfWorkConnection",
    "UnitOfWork",
    "evolution",
    "from_connection",
    "from_connection_factory",
    "registry",
    "wolf",
]
