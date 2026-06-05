"""Centralized path configuration — single source of truth for all directories.

Every module that needs a filesystem path should accept an optional
``paths: PathConfig`` parameter and fall back to the module-level DEFAULT.
Tests can inject ``PathConfig(root=tmp_path)`` without touching real disks.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PathConfig:
    """All project directories derived from a single *root*."""

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    # -- Runtime outputs (gitignored) --
    @property
    def runs_dir(self) -> Path:
        return self.root / "runs"

    @property
    def games_dir(self) -> Path:
        """UI interactive games (was ``logs/``)."""
        return self.runs_dir / "games"

    @property
    def selfplay_dir(self) -> Path:
        """Batch selfplay runs."""
        return self.runs_dir / "selfplay"

    @property
    def evolution_dir(self) -> Path:
        """Per-role evolution pipeline runs."""
        return self.runs_dir / "evolution"

    # -- Persistent state --
    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def versions_dir(self) -> Path:
        """Filesystem version store for role skill snapshots."""
        return self.data_dir / "versions"

    @property
    def battle_db_path(self) -> Path:
        """SQLite database for battle results (now shares main wolf.db)."""
        return self.data_dir / "wolf.db"

    @property
    def evolution_db_path(self) -> Path:
        """SQLite database for evolution pipeline state."""
        return self.data_dir / "evolution.db"

    @property
    def registry_dir(self) -> Path:
        """Version registry for role snapshots."""
        return self.data_dir / "registry"


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT = PathConfig(root=_PROJECT_ROOT)
