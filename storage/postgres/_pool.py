"""Connection pool management for PostgreSQL.

Provides lazy singleton pools keyed by (schema, conninfo) so callers
transparently reuse connections instead of opening a new TCP session
on every ``open_*_connection()`` call.
"""

from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)

_pools: dict[tuple[str, str], Any] = {}


def get_pool(
    schema: str,
    conninfo: str | None,
    connect_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Return a lazy singleton :class:`ConnectionPool` for *schema* + *conninfo*."""
    from psycopg_pool import ConnectionPool

    resolved_conninfo = conninfo or ""
    key = (schema, resolved_conninfo)
    pool = _pools.get(key)
    if pool is not None:
        return pool

    min_size = int(os.environ.get("PG_POOL_MIN_SIZE", "1"))
    max_size = int(os.environ.get("PG_POOL_MAX_SIZE", "10"))

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
        "Created PG connection pool: schema=%s min=%d max=%d",
        schema,
        min_size,
        max_size,
    )
    return pool


def close_pools() -> None:
    """Close all open connection pools. Call on application shutdown."""
    for key, pool in list(_pools.items()):
        try:
            pool.close()
        except Exception:  # noqa: BLE001 - best-effort shutdown
            _log.warning("Error closing pool %s", key, exc_info=True)
    _pools.clear()
