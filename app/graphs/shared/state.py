"""State definitions for all LangGraph subgraphs.

Each TypedDict defines the channel schema for a specific subgraph.
LangGraph merges node outputs with the current state.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """7-step decision subgraph state.

    Maps serialized action context fields into graph state.
    Each node reads/writes partial state; LangGraph merges.
    """
    # Input
    request: dict[str, Any]        # ActionRequest serialized
    player_id: int
    role: str
    model: Any
    memory: Any
    skill_dir: str | None
    game_id: str | None
    agent_fast_smoke: bool
    agent_policy_skip_llm_enabled: bool
    agent_policy_skip_llm_preset: str
    agent_policy_skip_llm_actions: list[str] | str
    agent_memory_compression_enabled: bool
    agent_prompt_max_total_chars: int
    agent_prompt_max_message_chars: int
    agent_prompt_min_message_chars: int
    agent_memory_recent_closed_segments: int
    agent_memory_max_events_per_segment: int
    agent_memory_event_max_chars: int

    # Memory (from remember_step)
    memory_context: dict[str, Any]

    # Skill selection
    selected_skills: list[str]
    skill_context: str
    strategy_advice: dict[str, Any]

    # Compression tracking
    compression_errors: list[str]
    compressed_segments_added: list[str]
    needs_more_compression: bool   # conditional edge flag

    # LLM interaction
    messages: Annotated[list[dict[str, str]], add_messages]
    prompt_budget: Any
    raw_output: str
    llm_error: str
    retry_count: int               # retry tracking for conditional edge

    # Decision
    parsed_decision: dict[str, Any]
    confidence: float
    response: dict[str, Any] | None  # ActionResponse serialized

    # Tracking
    source: str  # "llm" | "llm_error" | "policy_adjusted" | "policy_skipped" | "fallback"
    policy_adjustments: list[str]
    warnings: list[str]
    errors: list[str]
    diagnostics: list[dict[str, Any]]


class GameState(TypedDict, total=False):
    """Single game subgraph state."""
    # Configuration
    game_id: str
    seed: int
    max_days: int
    enable_sheriff: bool
    player_count: int
    runner_max_retries: int
    runner_retry_delay: float
    runner_action_timeout: float | None
    runner_game_timeout: float | None
    game_timeout: float | None
    agent_fast_smoke: bool
    agent_policy_skip_llm_enabled: bool
    agent_policy_skip_llm_preset: str
    agent_policy_skip_llm_actions: list[str] | str
    agent_memory_compression_enabled: bool
    agent_prompt_max_total_chars: int
    agent_prompt_max_message_chars: int
    agent_prompt_min_message_chars: int
    agent_memory_recent_closed_segments: int
    agent_memory_max_events_per_segment: int
    agent_memory_event_max_chars: int
    game_dir: str
    skill_dir: str
    role_skill_dirs: dict[str, str]  # role name -> skill dir (overrides skill_dir per role)
    paths: Any

    # Runtime
    roles: dict[int, str]           # player_id -> role name
    agents: dict[int, Any]          # player_id -> agent instance
    engine: Any                     # GameEngine
    logger: Any                     # GameLogger
    model: Any                      # shared LLM/model adapter
    recorder: Any                   # AgentDecisionRecorder
    trace_recorder: Any
    persistence: Any
    game_persistence: Any
    game_persistence_owner: bool
    game_run_handle: Any
    storage_provider: Any
    agent_subgraph: Any             # optional compiled agent decision subgraph
    storage_run_type: str
    source_run_id: str
    source_game_id: str
    mode: str
    model_id: str
    model_config_hash: str
    comparison_group_id: str
    comparison_type: str
    target_role: str
    target_version_id: str
    seed_set_id: str
    evaluation_set_id: str
    paired_seed: bool
    day: int
    phase: str
    alive_players: list[int]
    dead_players: list[int]
    sheriff_id: int | None

    # Output
    game_events: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    winner: str | None
    outcome: str | None
    terminal_reason: str | None
    finished: bool
    started_at: str
    finished_at: str
    error: str | None


class PlayState(TypedDict, total=False):
    """Ordinary play pipeline state."""
    run_type: str  # "play"
    config: dict[str, Any]          # GameRunConfig
    game_id: str
    seed: int
    max_days: int
    player_count: int
    model: Any
    skill_dir: str | None
    paths: Any
    storage_provider: Any
    enable_llm_judge: bool
    enable_decision_judge: bool
    review_llm_judge: bool
    review_decision_judge: bool
    judge_max_decisions: int
    review_judge_max_decisions: int
    decision_judge_max_decisions: int
    judge_concurrency: int
    review_judge_concurrency: int
    decision_judge_fn: Any
    game_dir: str
    roles: dict[int, str]
    game_events: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    winner: str | None
    finished: bool
    error: str | None
    started_at: str
    finished_at: str
    game: dict[str, Any]            # nested GameState
    review: dict[str, Any] | None
    decision_judge: dict[str, Any] | None
    result: dict[str, Any] | None


class EvalBatchState(TypedDict, total=False):
    """Evaluation batch pipeline state."""
    run_type: str  # "eval"
    batch_config: dict[str, Any]    # EvaluationBatchConfig
    batch_id: str
    game_subgraph: Any
    model: Any
    skill_dir: str
    paths: Any
    storage_provider: Any
    enable_llm_judge: bool
    enable_decision_judge: bool
    judge_max_decisions: int
    games: list[dict[str, Any]]     # EvaluationGameResult dicts
    player_scores: list[dict[str, Any]]
    score_summary: dict[str, Any] | None
    fairness: dict[str, Any] | None
    valid_game_rate: float
    rankable: bool
    rankable_reason: str
    role_version_resolution_failed: bool
    role_version_resolution_missing: dict[str, str]
    started_at: str
    finished_at: str
    result: dict[str, Any] | None
    diagnostics: list[dict[str, Any]]
    warnings: list[str]
    errors: list[str]


class EvolveState(TypedDict, total=False):
    """Evolution pipeline state for a single role."""
    run_type: str  # "evolve"
    role: str
    run_id: str
    config: dict[str, Any]
    game_subgraph: Any
    model: Any
    skill_dir: str | None
    paths: Any
    storage_provider: Any
    enable_llm_judge: bool
    enable_decision_judge: bool
    judge_max_decisions: int
    judge_concurrency: int
    training_judge_max_decisions: int
    training_judge_concurrency: int
    decision_judge_fn: Any
    training_game_count: int
    battle_game_count: int
    parent_hash: str
    baseline_config: dict[str, Any]
    baseline_skill_dir: str | None
    status: str  # "training" | "consolidating" | "applying" | "battling" | "reviewing" | "promoted" | "rejected"
    training_games: list[dict[str, Any]]
    candidate_hash: str | None
    candidate_skill_dir: str | None
    consolidation: dict[str, Any] | None
    battle_result: dict[str, Any] | None
    battle_games: list[dict[str, Any]]
    proposals: list[dict[str, Any]]
    diff: list[dict[str, Any]]
    current_stage: str
    progress: dict[str, Any]
    last_heartbeat_at: str
    started_at: str
    finished_at: str
    diagnostics: list[dict[str, Any]]
    warnings: list[str]
    errors: list[str]
    result: dict[str, Any] | None


class RootState(TypedDict, total=False):
    """Root graph dispatch state."""
    run_type: str  # "play" | "eval" | "evolve"
    config: dict[str, Any]
    batch_config: dict[str, Any]
    batch_id: str
    game_id: str
    seed: int
    max_days: int
    player_count: int
    role: str
    run_id: str
    model: Any
    skill_dir: str | None
    paths: Any
    storage_provider: Any
    enable_llm_judge: bool
    enable_decision_judge: bool
    review_llm_judge: bool
    review_decision_judge: bool
    judge_max_decisions: int
    review_judge_max_decisions: int
    decision_judge_max_decisions: int
    judge_concurrency: int
    review_judge_concurrency: int
    decision_judge_fn: Any
    game_dir: str
    game_subgraph: Any
    parent_hash: str
    candidate_hash: str | None
    roles: dict[int, str]
    game_events: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    winner: str | None
    finished: bool
    training_game_count: int
    battle_game_count: int
    games: list[dict[str, Any]]
    player_scores: list[dict[str, Any]]
    score_summary: dict[str, Any] | None
    fairness: dict[str, Any] | None
    rankable: bool
    rankable_reason: str
    started_at: str
    finished_at: str
    status: str
    training_games: list[dict[str, Any]]
    battle_games: list[dict[str, Any]]
    battle_result: dict[str, Any] | None
    proposals: list[dict[str, Any]]
    diff: list[dict[str, Any]]
    diagnostics: list[dict[str, Any]]
    warnings: list[str]
    game: dict[str, Any]
    review: dict[str, Any] | None
    decision_judge: dict[str, Any] | None
    result: dict[str, Any] | None
    error: str | None
    errors: list[str]
