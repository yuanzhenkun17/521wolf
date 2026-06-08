"""SQLite connection helpers for the registry database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from storage.shared.connection import connect_sqlite


def _init_connection(db_path: Path) -> sqlite3.Connection:
    """Open a WAL-mode SQLite connection with row factory and foreign keys."""
    return connect_sqlite(db_path, check_same_thread=False)


def get_registry_connection(
    db_path: Path | None = None,
    paths: Any | None = None,
) -> sqlite3.Connection:
    """Open a connection to the registry database, initializing its schema."""
    from storage.registry.schema import ensure_registry_schema

    if db_path is not None:
        path = db_path
    elif paths is not None:
        path = paths.registry_db_path
    else:
        from storage.paths import REGISTRY_DB_PATH

        path = REGISTRY_DB_PATH
    conn = _init_connection(path)
    ensure_registry_schema(conn)
    return conn
