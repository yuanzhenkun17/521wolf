"""Shared runner utilities for battle and evolution game runners."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

_log = logging.getLogger(__name__)


def create_engine(
    roles: dict[int, Any],
    agents: dict[int, Any],
    *,
    seed: int | None = None,
    max_days: int = 20,
    enable_sheriff: bool = True,
    logger: Any = None,
) -> Any:
    """Create a GameEngine from config parameters.

    Args:
        roles: Mapping of player_id -> Role.
        agents: Mapping of player_id -> agent (AgentRuntime or HumanPlayer).
        seed: Unused here (seed is consumed by role assignment), kept for API symmetry.
        max_days: Maximum number of in-game days before draw.
        enable_sheriff: Whether to run the sheriff election phase.
        logger: Optional GameLogger instance. If None a default one is created.
    """
    from engine.config import GameConfig, STANDARD_12
    from engine.engine import GameEngine
    from engine.logging import GameLogger

    config = GameConfig(
        name=STANDARD_12.name,
        role_counts=STANDARD_12.role_counts,
        enable_sheriff=enable_sheriff,
        max_days=max_days,
        sheriff_vote_weight=STANDARD_12.sheriff_vote_weight,
        night_order=STANDARD_12.night_order,
    )
    game_logger = logger if logger is not None else GameLogger()
    return GameEngine(roles, agents, config, logger=game_logger)


def create_agents_for_game(
    roles: dict[int, Any],
    *,
    model: Any = None,
    skill_dir: Path | str | None = None,
    role_skill_dirs: dict[str, Path] | None = None,
    human_player_id: int | None = None,
    game_id: str = "",
    recorder: Any = None,
    trace_recorder: Any = None,
    paths: Any = None,
) -> dict[int, Any]:
    """Create agents for a game, delegating to the factory.

    Args:
        roles: Mapping of player_id -> Role.
        model: LLM ModelAdapter. If None the factory loads a default client.
        skill_dir: Default skill directory for all agents.
        role_skill_dirs: Per-role skill directory overrides.
        human_player_id: If set, this player uses a HumanPlayer.
        game_id: Identifier for trace recording.
        recorder: AgentDecisionRecorder for lightweight decision logging.
        trace_recorder: AgentTraceRecorder for heavy per-player traces.
    """
    from agent.api.factory import create_agents

    return create_agents(
        roles,
        client=model,
        decision_recorder=recorder,
        trace_recorder=trace_recorder,
        game_id=game_id,
        skill_dir=skill_dir,
        role_skill_dirs=role_skill_dirs,
        human_player_id=human_player_id,
        paths=paths,
    )


def count_roles(roles: dict[int, Any]) -> dict:
    """Count role occurrences for GameConfig construction."""
    from engine.models import Role

    counts: dict[Role, int] = {}
    for role in roles.values():
        r = role if isinstance(role, Role) else Role(role)
        counts[r] = counts.get(r, 0) + 1
    return counts
