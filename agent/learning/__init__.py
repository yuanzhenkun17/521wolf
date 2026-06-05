"""Evidence-first learning pipeline v2 — the active learning subsystem.

This package follows an *evidence-first* approach:

- **v2 pipeline** (``agent.learning``): first extracts structured
  *decision evidence* from each game (normalizing agent decisions, selecting
  key decisions, then judging them with a rubric-driven LLM), producing
  ``EvidenceRunResult`` objects that contain decision evidence, game evidence,
  and experience candidates.  This evidence layer is more granular and
  auditable than heuristic aggregate scores.

Package structure:

- ``learning.pipeline``: run_evidence_pipeline — the main entry point.
- ``learning.leaderboard``: aggregate leaderboard summaries and rankings.
- ``learning.stats``: metric aggregation, confidence intervals, calibration.
- ``learning.game_analysis``: mid-term memory LLM analysis per game.
- ``learning.review``: post-game heuristic review, enhanced review reports.
- ``learning.evolution``: skill evolution through self-play and versioned battles.
"""

from agent.learning.models import EvidenceRunResult
from agent.learning.leaderboard import (
    LeaderboardEntry,
    aggregate_summaries,
    build_leaderboard,
    leaderboard_to_markdown,
    leaderboard_detail_markdown,
    write_leaderboard,
    load_summaries_from_runs,
)
from agent.learning.pipeline import run_evidence_pipeline
from agent.learning.stats import (
    new_role_accum,
    finalize_role_metrics,
    mean_ci95,
    wilson_ci95,
    calibrate_decisions,
    calibrate_decisions_by_group,
    merge_calibration_reports,
    summarize_bucket_totals,
    decision_correctness,
    CALIBRATION_BUCKETS,
    CHECKABLE_ACTIONS,
)
from agent.learning.game_analysis import (
    GameAnalysis,
    TurningPointAnalysis,
    DecisionReview,
    CounterfactualAnalysis,
    analyze_game,
    write_game_analysis,
    load_game_analysis,
    filter_mid_memory_for_role,
)
from agent.learning.evolution import (
    apply_proposals,
    BatchEvolutionResult,
    BaselineChangedError,
    EvolutionRun,
    EvolutionStatus,
    InvalidRunStateError,
    promote,
    promote_batch_result,
    reject,
    run_batch_evolution,
    run_evolution,
    run_selfplay,
    SelfPlayConfig,
    SelfPlayGameResult,
    SelfPlayResult,
    SkillConsolidation,
    SkillDiff,
    SkillProposal,
    SkillVersionConfig,
    aggregate_role_leaderboard,
)
from agent.learning.review import (
    # scoring
    AgentScores,
    GameReview,
    analyze_game as review_analyze_game,
    log_entries,
    did_survive,
    get_role_of,
    # constants
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
    # report data structures
    PlayerReview,
    TurningPoint,
    DecisionMistake,
    KeyDecisionReview,
    SkillReview,
    Counterfactual,
    GameReviewReport,
    # report functions
    generate_enhanced_review,
    role_weighted_score,
)

__all__ = [
    "run_evidence_pipeline",
    "LeaderboardEntry",
    "aggregate_summaries",
    "build_leaderboard",
    "leaderboard_to_markdown",
    "leaderboard_detail_markdown",
    "write_leaderboard",
    "load_summaries_from_runs",
    # Stats — metric aggregation, confidence intervals, calibration
    "new_role_accum",
    "finalize_role_metrics",
    "mean_ci95",
    "wilson_ci95",
    "calibrate_decisions",
    "calibrate_decisions_by_group",
    "merge_calibration_reports",
    "summarize_bucket_totals",
    "decision_correctness",
    "CALIBRATION_BUCKETS",
    "CHECKABLE_ACTIONS",
    # Game analysis — per-game LLM analysis (mid-term memory)
    "GameAnalysis",
    "TurningPointAnalysis",
    "DecisionReview",
    "CounterfactualAnalysis",
    "analyze_game",
    "write_game_analysis",
    "load_game_analysis",
    "filter_mid_memory_for_role",
    # Review — post-game heuristic scoring and enhanced review reports
    "AgentScores",
    "GameReview",
    "review_analyze_game",
    "log_entries",
    "did_survive",
    "get_role_of",
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
    "PlayerReview",
    "TurningPoint",
    "DecisionMistake",
    "KeyDecisionReview",
    "SkillReview",
    "Counterfactual",
    "GameReviewReport",
    "generate_enhanced_review",
    "role_weighted_score",
    # Evolution — skill evolution through self-play and versioned battles
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
    # Models — evidence layer data classes
    "EvidenceRunResult",
]
