"""Registry sub-package -- independent database for role version tracking."""

from storage.registry.connection import get_registry_connection
from storage.registry.schema import ensure_registry_schema

__all__ = [
    "get_registry_connection",
    "ensure_registry_schema",
]
