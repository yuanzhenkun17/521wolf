from __future__ import annotations

from typing import Any

import pytest

from storage.shared.database import (
    add_column,
    begin_write,
    ensure_columns,
    execute_for_update,
    insert_returning_id,
    record_schema_version,
    table_columns,
    table_exists,
)


class _FakeCursor:
    rowcount = 0

    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


class _DelegatingConn:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.cursor = _FakeCursor()
        self.existing_tables = {"sample"}
        self.existing_columns = {"id"}

    def execute(self, sql: str, parameters: Any = ()) -> _FakeCursor:
        self.calls.append(("execute", sql, parameters))
        return self.cursor

    def insert_returning_id(
        self,
        sql: str,
        parameters: Any = (),
        *,
        id_column: str = "id",
    ) -> int:
        self.calls.append(("insert_returning_id", sql, parameters, id_column))
        return 42

    def begin_write(self) -> None:
        self.calls.append(("begin_write",))

    def execute_for_update(self, sql: str, parameters: Any = ()) -> _FakeCursor:
        self.calls.append(("execute_for_update", sql, parameters))
        return self.cursor

    def table_exists(self, table_name: str) -> bool:
        self.calls.append(("table_exists", table_name))
        return table_name in self.existing_tables

    def table_columns(self, table_name: str) -> set[str]:
        self.calls.append(("table_columns", table_name))
        return set(self.existing_columns)

    def add_column(self, table_name: str, column_name: str, declaration: str) -> None:
        self.calls.append(("add_column", table_name, column_name, declaration))
        self.existing_columns.add(column_name)

    def record_schema_version(
        self,
        component: str,
        version: int,
        applied_at: str,
    ) -> None:
        self.calls.append(("record_schema_version", component, version, applied_at))


class _NoHooksConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.cursor = _FakeCursor()

    def execute(self, sql: str, parameters: Any = ()) -> _FakeCursor:
        self.calls.append((sql, parameters))
        return self.cursor


def test_insert_returning_id_requires_adapter_method() -> None:
    conn = _DelegatingConn()

    result = insert_returning_id(conn, "INSERT INTO t DEFAULT VALUES", (), id_column="custom_id")  # type: ignore[arg-type]

    assert result == 42
    assert conn.calls == [
        ("insert_returning_id", "INSERT INTO t DEFAULT VALUES", (), "custom_id")
    ]


def test_insert_returning_id_without_adapter_hook_fails_fast() -> None:
    conn = _NoHooksConn()

    with pytest.raises(RuntimeError, match="PostgreSQL storage adapter"):
        insert_returning_id(conn, "INSERT INTO sample (name) VALUES (?)", ("one",))  # type: ignore[arg-type]


def test_begin_write_delegates_to_adapter_method() -> None:
    conn = _DelegatingConn()

    begin_write(conn)  # type: ignore[arg-type]

    assert conn.calls == [("begin_write",)]


def test_begin_write_without_adapter_hook_is_rejected() -> None:
    conn = _NoHooksConn()

    with pytest.raises(RuntimeError, match="PostgreSQL storage adapter"):
        begin_write(conn)  # type: ignore[arg-type]

    assert conn.calls == []


def test_execute_for_update_delegates_to_adapter_method() -> None:
    conn = _DelegatingConn()

    cursor = execute_for_update(conn, "SELECT * FROM t WHERE id = ?", (1,))  # type: ignore[arg-type]

    assert cursor is conn.cursor
    assert conn.calls == [("execute_for_update", "SELECT * FROM t WHERE id = ?", (1,))]


def test_record_schema_version_requires_adapter_method() -> None:
    conn = _DelegatingConn()

    record_schema_version(conn, component="wolf", version=3)  # type: ignore[arg-type]

    assert len(conn.calls) == 1
    call = conn.calls[0]
    assert call[:3] == ("record_schema_version", "wolf", 3)
    assert call[3]


def test_record_schema_version_without_adapter_hook_fails_fast() -> None:
    conn = _NoHooksConn()

    with pytest.raises(RuntimeError, match="PostgreSQL storage adapter"):
        record_schema_version(conn, component="wolf", version=3)  # type: ignore[arg-type]


def test_schema_helpers_delegate_catalog_operations() -> None:
    conn = _DelegatingConn()

    assert table_exists(conn, "sample", allowed_tables={"sample"}) is True  # type: ignore[arg-type]
    assert table_columns(conn, "sample", allowed_tables={"sample"}) == {"id"}  # type: ignore[arg-type]
    add_column(
        conn,  # type: ignore[arg-type]
        "sample",
        "name",
        "TEXT",
        allowed_tables={"sample"},
        allowed_columns={"name"},
    )

    assert conn.existing_columns == {"id", "name"}
    assert conn.calls == [
        ("table_exists", "sample"),
        ("table_columns", "sample"),
        ("add_column", "sample", "name", "TEXT"),
    ]


def test_ensure_columns_delegates_schema_catalog_operations() -> None:
    conn = _DelegatingConn()

    ensure_columns(
        conn,  # type: ignore[arg-type]
        "sample",
        [("id", "INTEGER"), ("name", "TEXT"), ("created_at", "TEXT NOT NULL")],
        allowed_tables={"sample"},
    )

    assert conn.existing_columns == {"id", "name", "created_at"}
    assert conn.calls == [
        ("table_exists", "sample"),
        ("table_columns", "sample"),
        ("add_column", "sample", "name", "TEXT"),
        ("add_column", "sample", "created_at", "TEXT NOT NULL"),
    ]


def test_ensure_columns_skips_missing_table() -> None:
    conn = _DelegatingConn()

    ensure_columns(
        conn,  # type: ignore[arg-type]
        "missing",
        [("name", "TEXT")],
        allowed_tables={"missing"},
    )

    assert conn.calls == [("table_exists", "missing")]


def test_schema_helpers_reject_unapproved_or_unsafe_identifiers() -> None:
    conn = _DelegatingConn()

    with pytest.raises(ValueError, match="unsupported table identifier"):
        table_exists(conn, "sample", allowed_tables={"other"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid table identifier"):
        table_exists(conn, "sample; DROP TABLE sample")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="invalid column identifier"):
        add_column(conn, "sample", "bad-name", "TEXT", allowed_tables={"sample"})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="unsafe column declaration"):
        add_column(
            conn,  # type: ignore[arg-type]
            "sample",
            "name",
            "TEXT; DROP TABLE sample",
            allowed_tables={"sample"},
            allowed_columns={"name"},
        )
