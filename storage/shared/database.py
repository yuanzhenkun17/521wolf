"""Small storage connection protocols for the PostgreSQL storage adapter."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Collection, Iterable, Protocol, Sequence, runtime_checkable


@runtime_checkable
class StorageRow(Protocol):
    def __getitem__(self, key: str | int) -> Any:
        ...

    def keys(self) -> Iterable[str]:
        ...


@runtime_checkable
class StorageCursor(Protocol):
    @property
    def rowcount(self) -> int:
        ...

    def fetchone(self) -> StorageRow | None:
        ...

    def fetchall(self) -> list[StorageRow]:
        ...


@runtime_checkable
class StorageConnection(Protocol):
    def execute(self, sql: str, parameters: Iterable[Any] = (), /) -> StorageCursor:
        ...

    def commit(self) -> None:
        ...

    def rollback(self) -> None:
        ...

    def close(self) -> None:
        ...

    def __enter__(self) -> "StorageConnection":
        ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> object:
        ...


class InsertReturningIdConnection(StorageConnection, Protocol):
    def insert_returning_id(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
        *,
        id_column: str = "id",
    ) -> int:
        ...


class WriteTransactionConnection(StorageConnection, Protocol):
    def begin_write(self) -> None:
        ...


class ForUpdateConnection(StorageConnection, Protocol):
    def execute_for_update(
        self,
        sql: str,
        parameters: Sequence[Any] = (),
    ) -> StorageCursor:
        ...


class SchemaIntrospectionConnection(StorageConnection, Protocol):
    def table_exists(self, table_name: str) -> bool:
        ...

    def table_columns(self, table_name: str) -> Iterable[str]:
        ...


class SchemaMigrationConnection(StorageConnection, Protocol):
    def add_column(self, table_name: str, column_name: str, declaration: str) -> None:
        ...


class SchemaVersionConnection(StorageConnection, Protocol):
    def record_schema_version(
        self,
        component: str,
        version: int,
        applied_at: str,
    ) -> None:
        ...


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def insert_returning_id(
    conn: StorageConnection,
    sql: str,
    parameters: Sequence[Any] = (),
    *,
    id_column: str = "id",
) -> int:
    """Execute an insert and return its generated id through adapter hooks."""
    custom = getattr(conn, "insert_returning_id", None)
    if callable(custom):
        return int(custom(sql, parameters, id_column=id_column))
    raise RuntimeError("insert_returning_id requires a PostgreSQL storage adapter")


def begin_write(conn: StorageConnection) -> None:
    """Begin a write transaction with adapter-specific locking."""
    custom = getattr(conn, "begin_write", None)
    if callable(custom):
        custom()
        return
    raise RuntimeError("begin_write requires a PostgreSQL storage adapter")


def execute_for_update(
    conn: StorageConnection,
    sql: str,
    parameters: Sequence[Any] = (),
) -> StorageCursor:
    """Execute a locking read when the adapter supports row-level locks."""
    custom = getattr(conn, "execute_for_update", None)
    if callable(custom):
        return custom(sql, parameters)
    raise RuntimeError("execute_for_update requires a PostgreSQL storage adapter")


def table_exists(
    conn: StorageConnection,
    table_name: str,
    *,
    allowed_tables: Collection[str] | None = None,
) -> bool:
    """Return whether a table exists, using adapter catalog hooks when present."""
    _validate_identifier(table_name, kind="table", allowed=allowed_tables)
    custom = getattr(conn, "table_exists", None)
    if callable(custom):
        return bool(custom(table_name))
    raise RuntimeError("table_exists requires a PostgreSQL storage adapter")


def table_columns(
    conn: StorageConnection,
    table_name: str,
    *,
    allowed_tables: Collection[str] | None = None,
) -> set[str]:
    """Return a table's column names, using adapter catalog hooks when present."""
    _validate_identifier(table_name, kind="table", allowed=allowed_tables)
    custom = getattr(conn, "table_columns", None)
    if callable(custom):
        return {str(column) for column in custom(table_name)}
    raise RuntimeError("table_columns requires a PostgreSQL storage adapter")


def add_column(
    conn: StorageConnection,
    table_name: str,
    column_name: str,
    declaration: str,
    *,
    allowed_tables: Collection[str] | None = None,
    allowed_columns: Collection[str] | None = None,
) -> None:
    """Add a column through adapter hooks."""
    _validate_identifier(table_name, kind="table", allowed=allowed_tables)
    _validate_identifier(column_name, kind="column", allowed=allowed_columns)
    _validate_column_declaration(declaration)
    custom = getattr(conn, "add_column", None)
    if callable(custom):
        custom(table_name, column_name, declaration)
        return
    raise RuntimeError("add_column requires a PostgreSQL storage adapter")


def record_schema_version(
    conn: StorageConnection,
    *,
    component: str,
    version: int,
    applied_at: str | None = None,
) -> None:
    """Record schema version metadata through adapter hooks."""
    custom = getattr(conn, "record_schema_version", None)
    if callable(custom):
        custom(
            component,
            int(version),
            applied_at or datetime.now().astimezone().isoformat(),
        )
        return
    raise RuntimeError("record_schema_version requires a PostgreSQL storage adapter")


def ensure_columns(
    conn: StorageConnection,
    table_name: str,
    columns: Sequence[tuple[str, str]],
    *,
    allowed_tables: Collection[str] | None = None,
) -> None:
    """Add missing columns to an existing table and skip absent tables."""
    if not table_exists(conn, table_name, allowed_tables=allowed_tables):
        return
    existing = table_columns(conn, table_name, allowed_tables=allowed_tables)
    allowed_columns = {column for column, _ in columns}
    for column, declaration in columns:
        if column in existing:
            continue
        add_column(
            conn,
            table_name,
            column,
            declaration,
            allowed_tables=allowed_tables,
            allowed_columns=allowed_columns,
        )
        existing.add(column)


def _validate_identifier(
    identifier: str,
    *,
    kind: str,
    allowed: Collection[str] | None = None,
) -> None:
    if allowed is not None and identifier not in allowed:
        raise ValueError(f"unsupported {kind} identifier: {identifier!r}")
    if not _IDENTIFIER_RE.fullmatch(identifier):
        raise ValueError(f"invalid {kind} identifier: {identifier!r}")


def _validate_column_declaration(declaration: str) -> None:
    if not declaration.strip():
        raise ValueError("column declaration must not be empty")
    forbidden = (";", "--", "/*", "*/", "\x00")
    if any(token in declaration for token in forbidden):
        raise ValueError(f"unsafe column declaration: {declaration!r}")


__all__ = [
    "ForUpdateConnection",
    "InsertReturningIdConnection",
    "SchemaIntrospectionConnection",
    "SchemaMigrationConnection",
    "SchemaVersionConnection",
    "StorageConnection",
    "StorageCursor",
    "StorageRow",
    "WriteTransactionConnection",
    "add_column",
    "begin_write",
    "ensure_columns",
    "execute_for_update",
    "insert_returning_id",
    "record_schema_version",
    "table_columns",
    "table_exists",
]
