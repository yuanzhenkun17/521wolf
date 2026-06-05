"""Skill evolution through self-play and versioned battles.

All internal imports reference agent.learning_v2 and
agent.learning_v2.evolution modules.
"""

from agent.learning_v2.evolution.applier import apply_proposals
from agent.learning_v2.evolution.batch import BatchEvolutionResult, promote_batch_result, run_batch_evolution
from agent.learning_v2.evolution.games import SelfPlayConfig, SelfPlayGameResult, SelfPlayResult, run_selfplay
from agent.learning_v2.evolution.leaderboard import aggregate_role_leaderboard
from agent.learning_v2.evolution.models import EvolutionRun, EvolutionStatus, SkillConsolidation, SkillDiff, SkillProposal, SkillVersionConfig
from agent.learning_v2.evolution.pipeline import BaselineChangedError, InvalidRunStateError, promote, reject, run_evolution
from agent.learning_v2.evolution.store import VersionStore

__all__ = [
    "apply_proposals",
    "BaselineChangedError",
    "BatchEvolutionResult",
    "EvolutionRun",
    "EvolutionStatus",
    "InvalidRunStateError",
    "promote",
    "promote_batch_result",
    "reject",
    "run_batch_evolution",
    "run_evolution",
    "run_selfplay",
    "SelfPlayConfig",
    "SelfPlayGameResult",
    "SelfPlayResult",
    "SkillConsolidation",
    "SkillDiff",
    "SkillProposal",
    "SkillVersionConfig",
    "aggregate_role_leaderboard",
    "VersionStore",
]