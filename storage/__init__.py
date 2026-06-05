"""SQLite storage layer for 521wolf runtime and learning data.

Facade: re-exports the active storage modules and shared data interfaces.
"""

# ---------------------------------------------------------------------------
# Core storage imports
# ---------------------------------------------------------------------------
from storage.schema import get_connection
from storage.game_store import GameStore
from storage.game_event_store import GameEventStore
from storage.decision_store import DecisionStore
from storage.version_store import VersionStoreDB
from storage.evolution_store import EvolutionStore
from storage.evolution.experience_repo import ExperienceCandidateStore
from storage.leaderboard_store import LeaderboardStore
from storage.replay import read_decisions_for_artifact, read_events_for_artifact
from storage.runtime import GamePersistence, open_storage_connection

# ---------------------------------------------------------------------------
# New shared re-exports
# ---------------------------------------------------------------------------
from storage.shared.connection import (
    get_evolution_connection,
)
from storage.registry.connection import (
    get_registry_connection,
)
from storage.shared.interfaces import (
    compute_hash,
    normalize_skill_text,
    normalize_skill_path,
    DecisionArchiveData,
    DecisionRecordData,
    EvolutionRunData,
    SkillProposalData,
    SkillVersionConfigData,
)

# ---------------------------------------------------------------------------
# New battle re-exports
# ---------------------------------------------------------------------------
from storage.battle.evaluation_repo import EvaluationStore
from storage.battle.review_repo import DecisionReviewStore, CounterfactualStore
from storage.battle.report_repo import ReportStore
from storage.battle.leaderboard_repo import BattleLeaderboardStore

# ---------------------------------------------------------------------------
# New evolution re-exports
# ---------------------------------------------------------------------------
from storage.evolution.pattern_repo import PatternStore
from storage.evolution.rejected_repo import RejectedProposalStore
from storage.evolution.situational_repo import SituationalRecordStore
from storage.evolution.outcome_repo import DecisionOutcomeStore

__all__ = [
    # Core
    "get_connection",
    "GameStore",
    "GameEventStore",
    "DecisionStore",
    "VersionStoreDB",
    "EvolutionStore",
    "LeaderboardStore",
    "ExperienceCandidateStore",
    "read_decisions_for_artifact",
    "read_events_for_artifact",
    "GamePersistence",
    "open_storage_connection",
    # Shared
    "get_evolution_connection",
    "get_registry_connection",
    "compute_hash",
    "normalize_skill_text",
    "normalize_skill_path",
    "DecisionArchiveData",
    "DecisionRecordData",
    "EvolutionRunData",
    "SkillProposalData",
    "SkillVersionConfigData",
    # Battle
    "EvaluationStore",
    "DecisionReviewStore",
    "CounterfactualStore",
    "ReportStore",
    "BattleLeaderboardStore",
    # Evolution
    "PatternStore",
    "RejectedProposalStore",
    "SituationalRecordStore",
    "DecisionOutcomeStore",
]
