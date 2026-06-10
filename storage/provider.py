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


def open_wolf_connection(
    provider: StorageProvider | None = None,
    *,
    paths: Any | None = None,
) -> StorageConnection:
    """Open a wolf-domain storage connection through the active provider."""
    if provider is not None:
        return provider.open_wolf_connection()
    if paths is None:
        return storage_provider_from_env().open_wolf_connection()
    return storage_provider_from_env(paths=paths).open_wolf_connection()


def open_registry_connection(
    provider: StorageProvider | None = None,
    *,
    paths: Any | None = None,
) -> StorageConnection:
    """Open a registry-domain storage connection through the active provider."""
    if provider is not None:
        return provider.open_registry_connection()
    if paths is None:
        return storage_provider_from_env().open_registry_connection()
    return storage_provider_from_env(paths=paths).open_registry_connection()


def open_evolution_connection(
    provider: StorageProvider | None = None,
    *,
    paths: Any | None = None,
) -> StorageConnection:
    """Open an evolution-domain storage connection through the active provider."""
    if provider is not None:
        return provider.open_evolution_connection()
    if paths is None:
        return storage_provider_from_env().open_evolution_connection()
    return storage_provider_from_env(paths=paths).open_evolution_connection()


__all__ = [
    "open_evolution_connection",
    "open_registry_connection",
    "open_wolf_connection",
    "PostgresStorageProvider",
    "StorageProvider",
    "storage_provider_from_env",
]
