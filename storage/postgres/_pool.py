"""Connection pool management for PostgreSQL.

Provides lazy singleton pools keyed by (schema, conninfo, process role) so
callers transparently reuse connections without letting API and worker
processes share the same sizing policy.
"""

from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

_pools: dict[tuple[str, str, str], Any] = {}


def get_pool(
    schema: str,
    conninfo: str | None,
    connect_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Return a lazy singleton :class:`ConnectionPool` for *schema* + *conninfo*."""
    from psycopg_pool import ConnectionPool

    resolved_conninfo = conninfo or ""
    role = _pool_role()
    key = (schema, resolved_conninfo, role)
    pool = _pools.get(key)
    if pool is not None:
        return pool

    min_size = _pool_int("MIN_SIZE", default=1, role=role)
    max_size = _pool_int("MAX_SIZE", default=10, role=role)

    kwargs = dict(connect_kwargs or {})
    conninfo_str = resolved_conninfo or None

    search_path = (schema, "public")

    def configure(conn: Any) -> None:
        conn.execute(
            "SET search_path TO "
            + ", ".join(f'"{name}"' for name in search_path)
        )
        conn.commit()

    check_connection = os.environ.get("PG_POOL_CHECK_CONNECTION", "true").lower() not in {"0", "false", "no"}
    pool_kwargs: dict[str, Any] = {}
    if check_connection:
        pool_kwargs["check"] = ConnectionPool.check_connection

    pool = ConnectionPool(
        conninfo=conninfo_str,
        min_size=min_size,
        max_size=max_size,
        kwargs=kwargs,
        configure=configure,
        open=True,
        **pool_kwargs,
    )
    _pools[key] = pool
    _log.info(
        "Created PG connection pool: schema=%s role=%s min=%d max=%d",
        schema,
        role,
        min_size,
        max_size,
    )
    return pool


def _pool_role() -> str:
    raw = os.environ.get("PG_POOL_ROLE") or os.environ.get("WOLF_PROCESS_ROLE") or "api"
    role = str(raw).strip().lower().replace("-", "_")
    return role if role else "api"


def _pool_int(suffix: str, *, default: int, role: str) -> int:
    role_key = f"PG_{role.upper()}_POOL_{suffix}"
    raw = os.environ.get(role_key)
    if raw is None:
        raw = os.environ.get(f"PG_POOL_{suffix}", str(default))
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return default


def close_pools() -> None:
    """Close all open connection pools. Call on application shutdown."""
    for key, pool in list(_pools.items()):
        try:
            pool.close()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            _log.warning("Error closing pool %s", key, exc_info=True)
    _pools.clear()
