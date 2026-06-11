"""Game run.py — single entry point for app-layer orchestration."""

from __future__ import annotations

import hashlib
from typing import Any

from app.lib.judge_policy import apply_judge_policy


_AGENT_RUNTIME_CONFIG_KEYS: tuple[str, ...] = (
    "agent_fast_smoke",
    "agent_policy_skip_llm_enabled",
    "agent_policy_skip_llm_preset",
    "agent_policy_skip_llm_actions",
    "agent_memory_compression_enabled",
    "agent_prompt_max_total_chars",
    "agent_prompt_max_message_chars",
    "agent_prompt_min_message_chars",
    "agent_memory_recent_closed_segments",
    "agent_memory_max_events_per_segment",
    "agent_memory_event_max_chars",
)

LANGFUSE_EVAL_CONFIG_KEYS: tuple[str, ...] = (
    "langfuse_dataset_name",
    "langfuse_experiment_name",
    "langfuse_run_name",
)


async def run_game(
    *,
    mode: str = "dev",
    player_count: int = 12,
    max_days: int = 20,
    skill_dir: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Run a single ordinary game.

    Args:
        mode: "dev" or "prod"
        player_count: Number of players (default 12)
        max_days: Maximum game days
        skill_dir: Optional skill directory path

    Returns:
        dict with game_id, winner, player_roles, events, decisions
    """
    import uuid

    from app.graphs.main.builder import build_root_graph

    game_id = kwargs.get("game_id") or f"game_{uuid.uuid4().hex[:12]}"
    seed = kwargs.get("seed")
    if seed is None:
        seed = _stable_seed(game_id)

    config: dict[str, Any] = {
        "mode": mode,
        "player_count": player_count,
        "max_days": max_days,
        "game_id": game_id,
        "seed": seed,
    }
    if skill_dir is not None:
        config["skill_dir"] = skill_dir
    for key in (
        "game_dir",
        "enable_sheriff",
        "model_config_hash",
        "enable_llm_judge",
        "enable_decision_judge",
        "review_llm_judge",
        "review_decision_judge",
        "judge_max_decisions",
        "review_judge_max_decisions",
        "decision_judge_max_decisions",
        "judge_concurrency",
        "review_judge_concurrency",
        "judge_timeout_seconds",
        "review_judge_timeout_seconds",
    ) + _AGENT_RUNTIME_CONFIG_KEYS:
        if key in kwargs and kwargs[key] is not None:
            config[key] = kwargs[key]
    if "game_dir" not in config and kwargs.get("paths") is not None:
        paths = kwargs["paths"]
        runs_dir = getattr(paths, "runs_dir", None)
        if runs_dir is not None:
            from pathlib import Path

            config["game_dir"] = str(Path(runs_dir) / "games" / game_id)
    config = apply_judge_policy("play", config)

    state: dict[str, Any] = {
        "run_type": "play",
        "config": config,
    }
    _copy_optional(state, kwargs, "model", "paths", "storage_provider", "decision_judge_fn")
    _ensure_model(state)

    graph = build_root_graph(use_checkpointer=bool(kwargs.get("use_checkpointer", False)))
    final_state = await graph.ainvoke(state)
    result = final_state.get("result")
    return result if isinstance(result, dict) else dict(final_state)


async def run_evaluation(
    *,
    batch_config: dict[str, Any],
    langfuse_dataset_name: str | None = None,
    langfuse_experiment_name: str | None = None,
    langfuse_run_name: str | None = None,
    **kwargs,
) -> dict[str, Any]:
    """Run an evaluation batch.

    Args:
        batch_config: EvaluationBatchConfig as dict

    Returns:
        EvaluationBatchResult as dict
    """
    from app.graphs.main.builder import build_root_graph

    config = dict(batch_config)
    for key, value in (
        ("langfuse_dataset_name", langfuse_dataset_name),
        ("langfuse_experiment_name", langfuse_experiment_name),
        ("langfuse_run_name", langfuse_run_name),
    ):
        if value is not None:
            config.setdefault(key, value)
    for key in (
        "game_count",
        "max_days",
        "mode",
        "seed_start",
        "paired_seed",
        "skill_dir",
        "enable_llm_judge",
        "enable_decision_judge",
        "eval_llm_judge",
        "eval_decision_judge",
        "review_llm_judge",
        "review_decision_judge",
        "judge_max_decisions",
        "eval_judge_max_decisions",
        "review_judge_max_decisions",
        "decision_judge_max_decisions",
        "judge_concurrency",
        "eval_judge_concurrency",
        "review_judge_concurrency",
        "judge_timeout_seconds",
        "eval_judge_timeout_seconds",
        "review_judge_timeout_seconds",
    ) + _AGENT_RUNTIME_CONFIG_KEYS + LANGFUSE_EVAL_CONFIG_KEYS:
        if key in kwargs and kwargs[key] is not None:
            config.setdefault(key, kwargs[key])
    config = apply_judge_policy("eval", config)

    state: dict[str, Any] = {
        "run_type": "eval",
        "batch_config": config,
    }
    _copy_config_keys(state, config, *LANGFUSE_EVAL_CONFIG_KEYS)
    _copy_optional(
        state,
        kwargs,
        "model",
        "decision_judge_model",
        "skill_dir",
        "paths",
        "storage_provider",
        "decision_judge_fn",
    )
    _ensure_model(state)

    graph = build_root_graph(use_checkpointer=bool(kwargs.get("use_checkpointer", False)))
    final_state = await graph.ainvoke(state)
    result = final_state.get("result")
    return result if isinstance(result, dict) else dict(final_state)


async def run_evolution(
    *,
    role: str,
    training_games: int = 5,
    battle_games: int = 4,
    **kwargs,
) -> dict[str, Any]:
    """Run evolution pipeline for a single role.

    Args:
        role: Target role to evolve
        training_games: Number of self-play training games
        battle_games: Number of baseline vs candidate battle games

    Returns:
        EvolutionRun result as dict
    """
    from app.graphs.main.builder import build_root_graph

    config = dict(kwargs.get("config") or {})
    config.setdefault("role", role)
    config.setdefault("training_games", training_games)
    config.setdefault("battle_games", battle_games)
    for key in (
        "max_days",
        "seed_start",
        "battle_seed_start",
        "skill_dir",
        "auto_promote",
        "max_proposals",
        "game_concurrency",
        "parent_hash",
        "promote_win_rate_margin",
        "battle_error_rate_ceiling",
        "battle_min_completed_games",
        "battle_confidence_z",
        "promotion_min_completed_games",
        "promotion_min_valid_game_rate",
        "promotion_max_decision_issue_rate",
        "promotion_min_proposal_quality",
        "enable_llm_judge",
        "enable_decision_judge",
        "evolve_llm_judge",
        "evolve_decision_judge",
        "training_llm_judge",
        "training_decision_judge",
        "review_llm_judge",
        "review_decision_judge",
        "judge_max_decisions",
        "evolve_judge_max_decisions",
        "training_judge_max_decisions",
        "review_judge_max_decisions",
        "decision_judge_max_decisions",
        "judge_concurrency",
        "evolve_judge_concurrency",
        "training_judge_concurrency",
        "review_judge_concurrency",
        "judge_timeout_seconds",
        "evolve_judge_timeout_seconds",
        "training_judge_timeout_seconds",
        "review_judge_timeout_seconds",
    ) + _AGENT_RUNTIME_CONFIG_KEYS:
        if key in kwargs and kwargs[key] is not None:
            config.setdefault(key, kwargs[key])
    config = apply_judge_policy("evolve", config)

    state: dict[str, Any] = {
        "run_type": "evolve",
        "role": role,
        "config": config,
    }
    _copy_optional(
        state,
        kwargs,
        "model",
        "skill_dir",
        "paths",
        "run_id",
        "parent_hash",
        "progress_sink",
        "cancel_check",
        "storage_provider",
        "decision_judge_fn",
    )
    _ensure_model(state)

    graph = build_root_graph(use_checkpointer=bool(kwargs.get("use_checkpointer", False)))
    final_state = await graph.ainvoke(state)
    result = final_state.get("result")
    return result if isinstance(result, dict) else dict(final_state)


def _copy_optional(target: dict[str, Any], source: dict[str, Any], *keys: str) -> None:
    """Copy explicitly provided runtime dependencies into graph input state."""
    for key in keys:
        if key in source and source[key] is not None:
            target[key] = source[key]


def _copy_config_keys(target: dict[str, Any], source: dict[str, Any], *keys: str) -> None:
    """Expose selected config values at the graph input state top level."""
    for key in keys:
        if source.get(key) is not None:
            target[key] = source[key]


def _ensure_model(state: dict[str, Any]) -> None:
    """Inject the default LLM client before entering graph orchestration."""
    if state.get("model") is None:
        from app.services.llm import create_llm

        state["model"] = create_llm()


def _stable_seed(value: str) -> int:
    """Derive a stable engine seed from an external game id."""
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 10000
