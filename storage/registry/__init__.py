"""Registry storage domain backed by the PostgreSQL registry schema."""

from storage.postgres import get_registry_postgres_connection

__all__ = ["get_registry_postgres_connection"]
