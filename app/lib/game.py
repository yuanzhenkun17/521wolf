"""Game factory functions — agents + engine creation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from engine import Role, HumanPlayer

from app.services.llm import create_llm


def create_agent_runtime(
    *,
    player_id: int,
    role: Role,
    model: Any = None,
    game_id: str | None = None,
    skill_dir: Path | str | None = None,
    recorder: Any = None,
    trace_recorder: Any = None,
    paths: Any = None,
) -> Any:
    """Create an AgentRuntime adapter backed by the app/ LangGraph runtime."""
    shared_model = model or create_llm()

    from app.graphs.subgraphs.agent.builder import build_agent_subgraph
    from app.graphs.subgraphs.agent.nodes import AgentRuntimeAdapter
    from app.services.memory import AgentMemory

    graph = build_agent_subgraph()
    return AgentRuntimeAdapter(
        graph=graph,
        player_id=player_id,
        role=role,
        model=shared_model,
        memory=AgentMemory(player_id=player_id, role=role),
        recorder=recorder,
        trace_recorder=trace_recorder,
        game_id=game_id,
        skill_dir=skill_dir,
        paths=paths,
    )


def create_agents(
    roles: dict[int, Role],
    client: Any = None,
    decision_recorder: Any = None,
    trace_recorder: Any = None,
    game_id: str | None = None,
    skill_dir: Path | str | None = None,
    role_skill_dirs: dict[str, Path] | None = None,
    human_player_id: int | None = None,
    paths=None,
) -> dict[int, Any]:
    """Create agents for each player."""
    shared_client = client or create_llm()
    result = {}
    for player_id, role in sorted(roles.items()):
        if player_id == human_player_id:
            result[player_id] = HumanPlayer(player_id=player_id)
            continue
        agent_skill_dir = (
            role_skill_dirs[role.value]
            if role_skill_dirs and role.value in role_skill_dirs
            else skill_dir
        )
        result[player_id] = create_agent_runtime(
            player_id=player_id,
            role=role,
            model=shared_client,
            game_id=game_id,
            skill_dir=agent_skill_dir,
            recorder=decision_recorder,
            trace_recorder=trace_recorder,
            paths=paths,
        )
    return result


def create_engine(
    roles: dict[int, Role],
    agents: dict[int, Any],
    *,
    seed: int = 0,
    max_days: int = 20,
    enable_sheriff: bool = True,
    logger: Any = None,
) -> Any:
    """Create a game engine configured with the given roles and agents.

    Uses engine.GameEngine directly (engine/ is a black box).
    """
    from engine import STANDARD_12, GameEngine, GameLogger

    config = replace(STANDARD_12, max_days=max_days, enable_sheriff=enable_sheriff)
    engine = GameEngine(
        roles=roles,
        agents=agents,
        config=config,
        logger=logger or GameLogger(),
    )
    return engine
