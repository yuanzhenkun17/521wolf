"""Registry storage domain backed by the PostgreSQL registry schema."""

from storage.postgres import get_registry_postgres_connection
from storage.registry.version_repo import RegistryVersionRepository

__all__ = ["RegistryVersionRepository", "get_registry_postgres_connection"]
