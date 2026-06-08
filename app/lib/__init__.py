"""Business logic — zero direct LLM calls (uses app/services/chain.py instead)."""

from app.lib.review import AgentScores, GameReview, analyze_game, did_survive, get_role_of, log_entries
from app.lib.score import (
    BatchScoreSummary,
    FairnessResult,
    PlayerScore,
    aggregate_batch_scores,
    compute_decision_quality_metrics,
    compute_model_leaderboard_entry,
    compute_rankable,
    compute_role_score,
    compute_role_version_leaderboard_entry,
    persist_leaderboard_entry,
)
from app.lib.game import create_agents, create_engine
from app.lib.store import AgentDecisionRecorder, DecisionRecord, GameRunConfig, GameRunHandle, GameRunService
from app.lib.evidence import (
    DecisionEvidence,
    DecisionEvidenceInput,
    EvidenceRunResult,
    ExperienceCandidate,
    GameEvidence,
    GameEvidenceBundle,
    KeyDecision,
    get_action_focus,
    get_role_rubric,
    normalize_decisions,
    select_key_decisions,
)
from app.lib.decision_judge import (
    DecisionJudgment,
    GameJudgmentReport,
    attach_judgments_to_evidence_summary,
    build_decision_judge_messages,
    judge_key_decisions,
    parse_decision_judgment,
    summarize_judgments,
)
from app.lib.judge_policy import JudgePolicy, apply_judge_policy, resolve_judge_policy
from app.lib.evolve import (
    EvolutionConfig,
    EvolutionRun,
    EvolutionStateManager,
    KnowledgeDiff,
    SkillConsolidation,
    SkillDiff,
    SkillProposal,
    deduplicate_proposals,
)
from app.lib.version import (
    SkillVersionConfig,
    VersionRegistry,
    VersionSummary,
    build_baseline_config,
    build_composite_skill_dir,
    promote_version,
    reject_version,
)

__all__ = [
    # review
    "AgentScores",
    "GameReview",
    "analyze_game",
    "did_survive",
    "get_role_of",
    "log_entries",
    # score
    "BatchScoreSummary",
    "FairnessResult",
    "PlayerScore",
    "aggregate_batch_scores",
    "compute_decision_quality_metrics",
    "compute_model_leaderboard_entry",
    "compute_rankable",
    "compute_role_score",
    "compute_role_version_leaderboard_entry",
    "persist_leaderboard_entry",
    # game
    "create_agents",
    "create_engine",
    # store
    "AgentDecisionRecorder",
    "DecisionRecord",
    "GameRunConfig",
    "GameRunHandle",
    "GameRunService",
    # evidence
    "DecisionEvidence",
    "DecisionEvidenceInput",
    "EvidenceRunResult",
    "ExperienceCandidate",
    "GameEvidence",
    "GameEvidenceBundle",
    "KeyDecision",
    "get_action_focus",
    "get_role_rubric",
    "normalize_decisions",
    "select_key_decisions",
    # decision judge
    "DecisionJudgment",
    "GameJudgmentReport",
    "attach_judgments_to_evidence_summary",
    "build_decision_judge_messages",
    "judge_key_decisions",
    "parse_decision_judgment",
    "summarize_judgments",
    "JudgePolicy",
    "apply_judge_policy",
    "resolve_judge_policy",
    # evolve
    "EvolutionConfig",
    "EvolutionRun",
    "EvolutionStateManager",
    "KnowledgeDiff",
    "SkillConsolidation",
    "SkillDiff",
    "SkillProposal",
    "deduplicate_proposals",
    # version
    "SkillVersionConfig",
    "VersionRegistry",
    "VersionSummary",
    "build_baseline_config",
    "build_composite_skill_dir",
    "promote_version",
    "reject_version",
]
