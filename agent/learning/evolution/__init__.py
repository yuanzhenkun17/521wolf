"""Skill evolution through self-play and versioned battles.

All internal imports reference agent.learning and
agent.learning.evolution modules.
"""

from agent.learning.evolution.applier import apply_proposals
from agent.learning.evolution.batch import BatchEvolutionResult, promote_batch_result, run_batch_evolution
from agent.learning.evolution.games import SelfPlayConfig, SelfPlayGameResult, SelfPlayResult, run_selfplay
from agent.learning.evolution.leaderboard import aggregate_role_leaderboard
from agent.learning.evolution.models import EvolutionRun, EvolutionStatus, SkillConsolidation, SkillDiff, SkillProposal, SkillVersionConfig
from agent.learning.evolution.pipeline import BaselineChangedError, InvalidRunStateError, promote, reject, run_evolution

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
]
