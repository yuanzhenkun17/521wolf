"""PostgreSQL storage layer for 521wolf runtime and learning data.

Facade: re-exports the active storage modules and shared data interfaces.
"""

from storage.game_store import GameStore
from storage.game_event_store import GameEventStore
from storage.decision_store import DecisionStore
from storage.version_store import VersionStoreDB
from storage.evolution.run_repo import EvolutionStore
from storage.evolution.experience_repo import ExperienceCandidateStore
from storage.evaluation_store import EvaluationStore
from storage.review_store import CounterfactualStore, DecisionReviewStore
from storage.replay import read_decisions_for_artifact, read_events_for_artifact
from storage.run_policy import LeaderboardScope, RunPolicy, RunType, policy_for_run_type
from storage.runtime import GamePersistence
from storage.provider import (
    PostgresStorageProvider,
    StorageProvider,
    storage_provider_from_env,
)

from storage.interfaces import (
    compute_hash,
    normalize_skill_text,
    normalize_skill_path,
    DecisionArchiveData,
    DecisionRecordData,
    EvolutionRunData,
    RoleHistoryData,
    RoleVersionData,
    SkillProposalData,
    SkillVersionConfigData,
)

# ---------------------------------------------------------------------------
# Battle compatibility re-exports
# ---------------------------------------------------------------------------
from storage.battle.report_repo import ReportStore
from storage.battle.leaderboard_repo import BattleLeaderboardStore

# ---------------------------------------------------------------------------
# New evolution re-exports
# ---------------------------------------------------------------------------
from storage.evolution.rejected_repo import RejectedProposalStore

__all__ = [
    # Core
    "GameStore",
    "GameEventStore",
    "DecisionStore",
    "VersionStoreDB",
    "EvolutionStore",
    "ExperienceCandidateStore",
    "LeaderboardScope",
    "RunPolicy",
    "RunType",
    "policy_for_run_type",
    "read_decisions_for_artifact",
    "read_events_for_artifact",
    "GamePersistence",
    "PostgresStorageProvider",
    "StorageProvider",
    "storage_provider_from_env",
    # Shared
    "compute_hash",
    "normalize_skill_text",
    "normalize_skill_path",
    "DecisionArchiveData",
    "DecisionRecordData",
    "EvolutionRunData",
    "RoleHistoryData",
    "RoleVersionData",
    "SkillProposalData",
    "SkillVersionConfigData",
    # Battle
    "EvaluationStore",
    "DecisionReviewStore",
    "CounterfactualStore",
    "ReportStore",
    "BattleLeaderboardStore",
    # Evolution
    "RejectedProposalStore",
]
