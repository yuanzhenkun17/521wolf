"""Storage-layer default paths.

This module deliberately has no dependency on agent modules.
Storage connections are resolved from PostgreSQL environment variables; these
paths are only for filesystem artifacts.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"


__all__ = [
    "DATA_DIR",
    "PROJECT_ROOT",
]
