"""Skill evolution through self-play and versioned battles.

The v2 evolution package — migrated from agent.learning.evolution.
All internal imports reference agent.learning_v2 and
agent.learning_v2.evolution modules.
"""

from agent.learning_v2.evolution.applier import apply_proposals
from agent.learning_v2.evolution.batch import run_batch_evolution
from agent.learning_v2.evolution.games import SelfPlayConfig, SelfPlayGameResult, SelfPlayResult, run_selfplay
from agent.learning_v2.evolution.models import EvolutionRun, SkillConsolidation, SkillProposal
from agent.learning_v2.evolution.pipeline import promote, reject, run_evolution
from agent.learning_v2.evolution.store import VersionStore

__all__ = [
    "apply_proposals",
    "EvolutionRun",
    "promote",
    "reject",
    "run_batch_evolution",
    "run_evolution",
    "run_selfplay",
    "SelfPlayConfig",
    "SelfPlayGameResult",
    "SelfPlayResult",
    "SkillConsolidation",
    "SkillProposal",
    "VersionStore",
]