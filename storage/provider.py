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

        return get_wolf_postgres_connection(self.conninfo, connect_kwargs=self.connect_kwargs)

    def open_registry_connection(self) -> StorageConnection:
        from storage.postgres import get_registry_postgres_connection

        return get_registry_postgres_connection(self.conninfo, connect_kwargs=self.connect_kwargs)

    def open_evolution_connection(self) -> StorageConnection:
        from storage.postgres import get_evolution_postgres_connection

        return get_evolution_postgres_connection(self.conninfo, connect_kwargs=self.connect_kwargs)


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
    connect_kwargs: dict[str, Any] | None = None,
) -> StorageConnection:
    """Open a wolf-domain storage connection through the active provider."""
    if provider is not None:
        return provider.open_wolf_connection()
    return _provider_from_env(paths=paths, connect_kwargs=connect_kwargs).open_wolf_connection()


def open_registry_connection(
    provider: StorageProvider | None = None,
    *,
    paths: Any | None = None,
    connect_kwargs: dict[str, Any] | None = None,
) -> StorageConnection:
    """Open a registry-domain storage connection through the active provider."""
    if provider is not None:
        return provider.open_registry_connection()
    return _provider_from_env(paths=paths, connect_kwargs=connect_kwargs).open_registry_connection()


def open_evolution_connection(
    provider: StorageProvider | None = None,
    *,
    paths: Any | None = None,
    connect_kwargs: dict[str, Any] | None = None,
) -> StorageConnection:
    """Open an evolution-domain storage connection through the active provider."""
    if provider is not None:
        return provider.open_evolution_connection()
    return _provider_from_env(paths=paths, connect_kwargs=connect_kwargs).open_evolution_connection()


def _provider_from_env(
    *,
    paths: Any | None = None,
    connect_kwargs: dict[str, Any] | None = None,
) -> StorageProvider:
    if paths is None:
        provider = storage_provider_from_env()
    else:
        provider = storage_provider_from_env(paths=paths)
    return _with_connect_kwargs(provider, connect_kwargs)


def _with_connect_kwargs(
    provider: StorageProvider,
    connect_kwargs: dict[str, Any] | None,
) -> StorageProvider:
    if not connect_kwargs:
        return provider
    if not isinstance(provider, PostgresStorageProvider):
        return provider
    if provider.connect_kwargs:
        return provider
    return PostgresStorageProvider(
        provider.conninfo,
        connect_kwargs=dict(connect_kwargs),
    )


__all__ = [
    "open_evolution_connection",
    "open_registry_connection",
    "open_wolf_connection",
    "PostgresStorageProvider",
    "StorageProvider",
    "storage_provider_from_env",
]
