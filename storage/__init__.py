"""SQLite storage layer for 521wolf runtime and learning data."""

from storage.schema import get_connection
from storage.game_store import GameStore
from storage.game_event_store import GameEventStore
from storage.decision_store import DecisionStore
from storage.version_store import VersionStoreDB
from storage.evolution_store import EvolutionStore
from storage.importer import ArchiveImporter
from storage.experience_store import ExperienceCandidateStore
from storage.leaderboard_store import LeaderboardStore
from storage.replay import read_decisions_for_artifact, read_events_for_artifact
from storage.runtime import GamePersistence, open_storage_connection

__all__ = [
    "get_connection",
    "GameStore",
    "GameEventStore",
    "DecisionStore",
    "VersionStoreDB",
    "EvolutionStore",
    "ArchiveImporter",
    "LeaderboardStore",
    "RebuildReport",
    "StorageRebuilder",
    "ExperienceCandidateStore",
    "read_decisions_for_artifact",
    "read_events_for_artifact",
    "GamePersistence",
    "open_storage_connection",
]


def __getattr__(name: str):
    if name in {"RebuildReport", "StorageRebuilder"}:
        from storage.rebuilder import RebuildReport, StorageRebuilder

        return {
            "RebuildReport": RebuildReport,
            "StorageRebuilder": StorageRebuilder,
        }[name]
    raise AttributeError(f"module 'storage' has no attribute {name!r}")
