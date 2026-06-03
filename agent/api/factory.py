from __future__ import annotations

from pathlib import Path
from agent.infrastructure.llm import ModelAdapter, load_llm_client
from agent.infrastructure.archive import AgentTraceRecorder
from agent.infrastructure.decision_log import AgentDecisionRecorder
from agent.api.runtime import AgentRuntime
from engine.models import Role
from engine.players import HumanPlayer


def create_agents(
    roles: dict[int, Role],
    client: ModelAdapter | None = None,
    decision_recorder: AgentDecisionRecorder | None = None,
    trace_recorder: AgentTraceRecorder | None = None,
    game_id: str | None = None,
    skill_dir: Path | str | None = None,
    role_skill_dirs: dict[str, Path] | None = None,
    human_player_id: int | None = None,
) -> dict[int, AgentRuntime | HumanPlayer]:
    """Create agents for each player.

    Args:
        skill_dir: Default skill directory for all agents.
        role_skill_dirs: Per-role skill directory mapping (overrides skill_dir).
            Keys are role value strings (e.g. "werewolf"), values are Paths.
        human_player_id: If set, this player slot uses HumanPlayer instead of AgentRuntime.
    """
    shared_client = client or load_llm_client()
    result = {}
    for player_id, role in sorted(roles.items()):
        if player_id == human_player_id:
            result[player_id] = HumanPlayer(player_id=player_id)
            continue
        if role_skill_dirs and role.value in role_skill_dirs:
            agent_skill_dir = role_skill_dirs[role.value]
        else:
            agent_skill_dir = skill_dir
        result[player_id] = AgentRuntime(
            player_id=player_id,
            role=role,
            model=shared_client,
            recorder=decision_recorder,
            trace_recorder=trace_recorder,
            game_id=game_id,
            skill_dir=agent_skill_dir,
        )
    return result
