"""SQLite connection helpers for the registry database."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


def _init_connection(db_path: Path) -> sqlite3.Connection:
    """Open a WAL-mode SQLite connection with row factory and foreign keys."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


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
        from agent.common.paths import DEFAULT

        path = DEFAULT.registry_db_path
    conn = _init_connection(path)
    ensure_registry_schema(conn)
    return conn
