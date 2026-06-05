"""Post-game review and reporting for agent self-play (v2).

The module exposes two review levels:
- ``analyze_game``: lightweight heuristic scoring for a completed game.
- ``generate_enhanced_review``: structured reporting with mistake types,
  turning points, key decision reviews, skill analysis, and counterfactuals.

This package re-exports every public name so that
``from agent.learning_v2.review import ...`` works unchanged.
"""

from agent.learning_v2.review.scoring import (  # noqa: F401
    AgentScores,
    GameReview,
    analyze_game,
    log_entries,
    did_survive,
    get_role_of,
)
from agent.learning_v2.review.report import (  # noqa: F401
    # Constants
    MISTAKE_ILLEGAL_ACTION,
    MISTAKE_POLICY_ADJUSTED,
    MISTAKE_FALLBACK_USED,
    MISTAKE_LOW_CONFIDENCE,
    MISTAKE_WRONG_VOTE,
    MISTAKE_POISONED_GOOD,
    MISTAKE_SHOT_GOOD,
    MISTAKE_KILLED_TEAMMATE,
    MISTAKE_IGNORED_SEER,
    ATTR_BELIEF_ERROR,
    ATTR_MEMORY_ERROR,
    ATTR_POLICY_ADJUSTMENT,
    ATTR_FORMAT_ERROR,
    ATTR_STRATEGY_ERROR,
    # Data structures
    PlayerReview,
    TurningPoint,
    DecisionMistake,
    KeyDecisionReview,
    SkillReview,
    Counterfactual,
    GameReviewReport,
    # Functions
    generate_enhanced_review,
    role_weighted_score,
    # Private helpers (re-exported for backwards compatibility with tests)
    _classify_mistakes,
    _collect_mistakes,
    _enhanced_turning_points,
    _player_outcome,
    _generate_counterfactuals,
)

__all__ = [
    # scoring
    "AgentScores",
    "GameReview",
    "analyze_game",
    "log_entries",
    "did_survive",
    "get_role_of",
    # constants
    "MISTAKE_ILLEGAL_ACTION",
    "MISTAKE_POLICY_ADJUSTED",
    "MISTAKE_FALLBACK_USED",
    "MISTAKE_LOW_CONFIDENCE",
    "MISTAKE_WRONG_VOTE",
    "MISTAKE_POISONED_GOOD",
    "MISTAKE_SHOT_GOOD",
    "MISTAKE_KILLED_TEAMMATE",
    "MISTAKE_IGNORED_SEER",
    "ATTR_BELIEF_ERROR",
    "ATTR_MEMORY_ERROR",
    "ATTR_POLICY_ADJUSTMENT",
    "ATTR_FORMAT_ERROR",
    "ATTR_STRATEGY_ERROR",
    # report data structures
    "PlayerReview",
    "TurningPoint",
    "DecisionMistake",
    "KeyDecisionReview",
    "SkillReview",
    "Counterfactual",
    "GameReviewReport",
    # report functions
    "generate_enhanced_review",
    "role_weighted_score",
    # private helpers (re-exported for backwards compatibility)
    "_classify_mistakes",
    "_collect_mistakes",
    "_enhanced_turning_points",
    "_player_outcome",
    "_generate_counterfactuals",
]