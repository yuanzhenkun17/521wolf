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
) -> dict[int, LLMPlayerAgent]:
    shared_client = client or load_llm_client()
    return {
        player_id: LLMPlayerAgent(
            player_id=player_id,
            role=role,
            client=shared_client,
            decision_recorder=decision_recorder,
            trace_recorder=trace_recorder,
            game_id=game_id,
            skill_dir=skill_dir,
        )
        for player_id, role in sorted(roles.items())
    }
