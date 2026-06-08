"""Storage-layer default paths.

This module deliberately has no dependency on agent modules.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
WOLF_DB_PATH = DATA_DIR / "wolf.db"
EVOLUTION_DB_PATH = DATA_DIR / "evolution.db"
REGISTRY_DB_PATH = DATA_DIR / "registry" / "registry.db"


__all__ = [
    "DATA_DIR",
    "EVOLUTION_DB_PATH",
    "PROJECT_ROOT",
    "REGISTRY_DB_PATH",
    "WOLF_DB_PATH",
]
