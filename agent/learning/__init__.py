"""Post-game learning, evaluation, self-play, and skill evolution."""

from agent.learning.leaderboard import aggregate_summaries, build_leaderboard
from agent.learning.metrics import finalize_role_metrics, new_role_accum
from agent.learning.review import analyze_game, generate_enhanced_review
from agent.learning.selfplay import SelfPlayConfig, SelfPlayResult, run_selfplay

__all__ = [
    "aggregate_summaries",
    "analyze_game",
    "build_leaderboard",
    "finalize_role_metrics",
    "generate_enhanced_review",
    "new_role_accum",
    "run_selfplay",
    "SelfPlayConfig",
    "SelfPlayResult",
]
