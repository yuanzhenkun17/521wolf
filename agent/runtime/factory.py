from __future__ import annotations

from typing import TypeAlias

from pathlib import Path
from agent.runtime.model import ModelAdapter, load_llm_client
from agent.observability.archive import AgentTraceRecorder
from agent.observability.decision_log import AgentDecisionRecorder
from agent.runtime.agent import LLMPlayerAgent
from engine.models import Role


LLMClient: TypeAlias = ModelAdapter


def create_agents(
    roles: dict[int, Role],
    client: LLMClient | None = None,
    decision_recorder: AgentDecisionRecorder | None = None,
    trace_recorder: AgentTraceRecorder | None = None,
    game_id: str | None = None,
    skill_dir: Path | str | None = None,
    role_skill_dirs: dict[str, Path] | None = None,
) -> dict[int, LLMPlayerAgent]:
    """Create agents for each player.

    Args:
        skill_dir: Default skill directory for all agents.
        role_skill_dirs: Per-role skill directory mapping (overrides skill_dir).
            Keys are role value strings (e.g. "werewolf"), values are Paths.
    """
    shared_client = client or load_llm_client()
    result = {}
    for player_id, role in sorted(roles.items()):
        if role_skill_dirs and role.value in role_skill_dirs:
            agent_skill_dir = role_skill_dirs[role.value]
        else:
            agent_skill_dir = skill_dir
        result[player_id] = LLMPlayerAgent(
            player_id=player_id,
            role=role,
            client=shared_client,
            decision_recorder=decision_recorder,
            trace_recorder=trace_recorder,
            game_id=game_id,
            skill_dir=agent_skill_dir,
        )
    return result
