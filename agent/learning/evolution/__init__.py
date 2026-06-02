"""Skill evolution through self-play and versioned battles."""

from agent.learning.evolution.applier import apply_proposals
from agent.learning.evolution.batch import run_batch_evolution
from agent.learning.evolution.models import EvolutionRun, SkillConsolidation, SkillProposal
from agent.learning.evolution.pipeline import promote, reject, run_evolution
from agent.learning.evolution.store import VersionStore

__all__ = [
    "apply_proposals",
    "EvolutionRun",
    "promote",
    "reject",
    "run_batch_evolution",
    "run_evolution",
    "SkillConsolidation",
    "SkillProposal",
    "VersionStore",
]
