"""PostgreSQL-only storage connection provider."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from storage.shared.database import StorageConnection


class StorageProvider(Protocol):
    """Open storage connections for the three storage domains."""

    def open_wolf_connection(self) -> StorageConnection:
        ...

    def open_registry_connection(self) -> StorageConnection:
        ...

    def open_evolution_connection(self) -> StorageConnection:
        ...


@dataclass(frozen=True, slots=True)
class PostgresStorageProvider:
    """PostgreSQL provider using one database and three schema namespaces."""

    conninfo: str | None = None
    connect_kwargs: dict[str, Any] = field(default_factory=dict)

    def open_wolf_connection(self) -> StorageConnection:
        from storage.postgres import get_wolf_postgres_connection

        return get_wolf_postgres_connection(self.conninfo, **self.connect_kwargs)

    def open_registry_connection(self) -> StorageConnection:
        from storage.postgres import get_registry_postgres_connection

        return get_registry_postgres_connection(self.conninfo, **self.connect_kwargs)

    def open_evolution_connection(self) -> StorageConnection:
        from storage.postgres import get_evolution_postgres_connection

        return get_evolution_postgres_connection(self.conninfo, **self.connect_kwargs)


def storage_provider_from_env(*, paths: Any | None = None) -> StorageProvider:
    """Build the only supported storage provider.

    ``paths`` is accepted temporarily for callers that still pass path bundles
    during the PostgreSQL-only transition; it is intentionally ignored.
    PostgreSQL connection details are resolved by the connection factories from
    ``POSTGRES_DATABASE_URL`` / ``DATABASE_URL``.
    """
    return PostgresStorageProvider()


__all__ = [
    "PostgresStorageProvider",
    "StorageProvider",
    "storage_provider_from_env",
]
