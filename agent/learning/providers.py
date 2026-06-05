"""Provider factories for memory injection.

Creates pattern_provider and episodic_provider that can be passed to
inject_memory_step. These query the evolution database for cross-game
knowledge.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


class PatternProvider:
    """Loads patterns from evolution.db and delegates to PatternEngine."""

    def __init__(self, db_path: Path, *, statuses: tuple[str, ...] | None = None) -> None:
        self._db_path = db_path
        self._statuses = statuses or ("active", "crystallized")
        self._engine = None

    def _ensure_engine(self):
        if self._engine is not None:
            return
        from agent.learning.pattern_engine import PatternEngine, Pattern
        from storage.evolution.pattern_repo import PatternStore
        from storage.shared.connection import get_evolution_connection

        self._engine = PatternEngine()
        try:
            conn = get_evolution_connection(self._db_path)
            store = PatternStore(conn)
            # list_patterns accepts a single status string, so query each
            # status we care about and merge the results.
            patterns: list[dict[str, Any]] = []
            for status in self._statuses:
                patterns.extend(store.list_patterns(status=status))
            for p_dict in patterns:
                pattern = Pattern.from_dict(p_dict)
                self._engine._patterns[pattern.pattern_id] = pattern
            conn.close()
        except Exception:
            _log.warning("Failed to load patterns from DB", exc_info=True)

    def get_relevant_patterns(
        self, role: str, phase: str, day: int, action_type: str | None = None
    ) -> list:
        self._ensure_engine()
        return self._engine.get_relevant_patterns(
            role=role, phase=phase, day=day, action_type=action_type
        )


class EpisodicProvider:
    """Queries situational_records from evolution.db."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def __call__(
        self, role: str, day: int, phase: str
    ) -> list[dict]:
        """Return top-3 relevant situational records for the current situation.

        Callable so it can be passed directly as ``episodic_provider`` to
        ``inject_memory_step``, which invokes it as
        ``episodic_provider(role, day, phase)``.
        """
        try:
            from storage.evolution.situational_repo import SituationalRecordStore
            from storage.shared.connection import get_evolution_connection

            conn = get_evolution_connection(self._db_path)
            store = SituationalRecordStore(conn)
            records = store.query(role=role, limit=3)
            conn.close()
            return [
                {
                    "game_id": r.get("game_id", ""),
                    "outcome": r.get("outcome", ""),
                    "day": r.get("day"),
                    "phase": r.get("phase"),
                    "key_events": r.get("key_events", []),
                }
                for r in records
            ]
        except Exception:
            _log.warning("Failed to load episodic records", exc_info=True)
            return []


def create_providers(
    paths: Any | None = None,
) -> tuple[PatternProvider | None, EpisodicProvider | None]:
    """Create pattern and episodic providers from PathConfig.

    Returns ``(None, None)`` when the evolution database does not yet exist,
    so that ``inject_memory_step`` remains a harmless no-op.
    """
    if paths is None:
        from agent.common.paths import DEFAULT as paths

    db_path = paths.evolution_db_path
    if not db_path.exists():
        return None, None

    return PatternProvider(db_path), EpisodicProvider(db_path)


def create_pattern_update_provider(paths: Any | None = None) -> PatternProvider:
    """Create a provider for post-game updates, including candidate patterns."""
    if paths is None:
        from agent.common.paths import DEFAULT as paths

    return PatternProvider(
        paths.evolution_db_path,
        statuses=("candidate", "active", "crystallized"),
    )
