"""Runtime factories for the registry storage domain."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_registry_dir(registry_dir: Path | str | None = None, paths: Any | None = None) -> Path:
    if registry_dir is not None:
        return Path(registry_dir)
    if paths is not None and hasattr(paths, "registry_dir"):
        value = getattr(paths, "registry_dir")
        if value is not None:
            return Path(value)
    from app.config import DEFAULT_PATHS

    return DEFAULT_PATHS.registry_dir


def version_registry_from_env(
    registry_dir: Path | str | None = None,
    *,
    paths: Any | None = None,
) -> Any:
    """Build the PostgreSQL-backed runtime registry."""
    import storage.provider as provider_mod
    from app.lib.version import PostgresVersionRegistry

    provider = provider_mod.storage_provider_from_env(paths=paths)
    return PostgresVersionRegistry(
        provider.open_registry_connection(),
        registry_dir=resolve_registry_dir(registry_dir, paths),
        owns_conn=True,
    )


__all__ = ["resolve_registry_dir", "version_registry_from_env"]
