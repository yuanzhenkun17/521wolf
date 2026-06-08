"""SQLite connection helpers for evolution database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from storage.interfaces import storage_timestamp

SQLITE_BUSY_TIMEOUT_MS = 30000
SCHEMA_MIGRATIONS_TABLE = "schema_migrations"


def configure_sqlite_connection(
    conn: sqlite3.Connection,
    *,
    busy_timeout_ms: int = SQLITE_BUSY_TIMEOUT_MS,
    foreign_keys: bool = True,
    prefer_wal: bool = True,
) -> None:
    """Apply project-wide SQLite pragmas, tolerating unsupported settings.

    WAL can fail for read-only databases, in-memory databases, or restricted
    filesystems. The connection should still be usable with busy timeout and
    foreign-key enforcement when possible.
    """
    for statement in (
        f"PRAGMA busy_timeout={int(busy_timeout_ms)}",
        "PRAGMA foreign_keys=ON" if foreign_keys else "PRAGMA foreign_keys=OFF",
    ):
        try:
            conn.execute(statement)
        except sqlite3.Error:
            pass
    if prefer_wal:
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass


def connect_sqlite(
    db_path: Path | str,
    *,
    timeout: float = 30,
    check_same_thread: bool = True,
    row_factory: type[sqlite3.Row] | None = sqlite3.Row,
) -> sqlite3.Connection:
    """Open a SQLite connection with shared project pragmas applied."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        timeout=timeout,
        check_same_thread=check_same_thread,
    )
    configure_sqlite_connection(conn)
    if row_factory is not None:
        conn.row_factory = row_factory
    return conn


def record_schema_version(
    conn: sqlite3.Connection,
    *,
    component: str,
    version: int,
) -> None:
    """Record the current schema version for a storage component."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SCHEMA_MIGRATIONS_TABLE} (
            component TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO {SCHEMA_MIGRATIONS_TABLE} (component, version, applied_at)
        VALUES (?, ?, ?)
        ON CONFLICT(component) DO UPDATE SET
            version = excluded.version,
            applied_at = excluded.applied_at
        """,
        (component, int(version), storage_timestamp()),
    )


def _init_connection(db_path: Path) -> sqlite3.Connection:
    """Open a WAL-mode SQLite connection with row factory and foreign keys."""
    return connect_sqlite(db_path)


def get_evolution_connection(
    db_path: Path | None = None,
    paths: Any | None = None,
) -> sqlite3.Connection:
    """Open a connection to the evolution database, initializing its schema."""
    from storage.evolution.schema import ensure_evolution_schema

    if db_path is not None:
        path = db_path
    elif paths is not None:
        path = paths.evolution_db_path
    else:
        from storage.paths import EVOLUTION_DB_PATH

        path = EVOLUTION_DB_PATH
    conn = _init_connection(path)
    ensure_evolution_schema(conn)
    return conn
