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
        """Immutable skill-version snapshots (was ``role_versions/``)."""
        return self.data_dir / "versions"

    # -- Convenience --
    def ensure(self) -> None:
        """Create all output directories so writers don't need mkdir boilerplate."""
        self.games_dir.mkdir(parents=True, exist_ok=True)
        self.selfplay_dir.mkdir(parents=True, exist_ok=True)
        self.evolution_dir.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT = PathConfig(root=_PROJECT_ROOT)
