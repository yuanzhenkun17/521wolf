"""Evidence-first learning pipeline v2 — the active learning subsystem.

This package replaces the original ``agent.learning`` (v1) pipeline.  The key
difference is that v2 follows an *evidence-first* approach:

- **v1 pipeline** (``agent.learning``): produces heuristic review scores and
  LLM-generated mid-term memory analysis, then feeds those into a skill
  evolution cycle via self-play battles.

- **v2 pipeline** (``agent.learning_v2``): first extracts structured
  *decision evidence* from each game (normalizing agent decisions, selecting
  key decisions, then judging them with a rubric-driven LLM), producing
  ``EvidenceRunResult`` objects that contain decision evidence, game evidence,
  and experience candidates.  This evidence layer is more granular and
  auditable than v1's aggregate scores.

Relationship to v1:

- ``agent.learning_v2`` is the recommended module for all new learning
  features.
- ``agent.learning.evolution.games`` already imports
  ``learning_v2.pipeline.run_evidence_pipeline``, showing that partial
  migration is underway — the self-play runner uses the v2 evidence pipeline
  internally.
- ``agent.learning_v2.stats`` (metric aggregation, confidence intervals,
  calibration) has been migrated from v1; it is now the canonical location
  for these helpers.
- ``agent.learning_v2.review`` (post-game heuristic review, enhanced
  review reports, mistake/attribution constants) has been migrated from
  ``agent.learning.review``.
- ``agent.learning_v2.game_analysis`` (mid-term memory LLM analysis)
  has been migrated from ``agent.learning.game_analysis``.

Do not add new features to ``agent.learning``; extend this package instead.
See ``agent/learning/MIGRATION.md`` for the full migration plan.
"""

from agent.learning_v2.leaderboard import (
    LeaderboardEntry,
    aggregate_summaries,
    build_leaderboard,
    leaderboard_to_markdown,
    leaderboard_detail_markdown,
    write_leaderboard,
    load_summaries_from_runs,
)
from agent.learning_v2.pipeline import run_evidence_pipeline
from agent.learning_v2.stats import (
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
from agent.learning_v2.game_analysis import (
    GameAnalysis,
    TurningPointAnalysis,
    DecisionReview,
    CounterfactualAnalysis,
    analyze_game,
    write_game_analysis,
    load_game_analysis,
    filter_mid_memory_for_role,
)
from agent.learning_v2.evolution import (
    apply_proposals,
    EvolutionRun,
    promote,
    reject,
    run_batch_evolution,
    run_evolution,
    run_selfplay,
    SelfPlayConfig,
    SelfPlayGameResult,
    SelfPlayResult,
    SkillConsolidation,
    SkillProposal,
    VersionStore,
)
from agent.learning_v2.review import (
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
