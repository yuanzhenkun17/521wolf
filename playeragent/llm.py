from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TypeAlias

from playeragent.adapters import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    ChatCompletionClient,
    ModelAdapter,
)
from playeragent.decision_log import AgentDecisionRecorder
from playeragent.runtime import AgentRuntime
from werewolf.models import ActionRequest, ActionResponse, Role


DEFAULT_CONFIG_PATH = Path("config/llm.local.json")
LLMClient: TypeAlias = ModelAdapter


class LLMPlayerAgent:
    """Werewolf player agent backed by an OpenAI-compatible chat model."""

    def __init__(
        self,
        *,
        player_id: int,
        role: Role,
        client: LLMClient,
        persona: str | None = None,
        decision_recorder: AgentDecisionRecorder | None = None,
    ) -> None:
        self.player_id = player_id
        self.role = role
        self.client = client
        self.runtime = AgentRuntime(player_id=player_id, role=role, model=client, persona=persona)
        self.decision_recorder = decision_recorder

    @property
    def persona(self) -> str:
        return self.runtime.persona

    @property
    def memory(self):
        return self.runtime.memory

    @property
    def belief(self):
        return self.runtime.belief

    async def act(self, request: ActionRequest) -> ActionResponse:
        before = len(self.runtime.memory.decision_history)
        response = await self.runtime.act(request)
        if self.decision_recorder is not None:
            for decision in self.runtime.memory.decision_history[before:]:
                self.decision_recorder.record(decision)
        return response


def load_llm_client(config_path: str | Path = DEFAULT_CONFIG_PATH) -> ChatCompletionClient:
    config = _load_llm_config(Path(config_path))
    api_key = os.environ.get("WEREWOLF_LLM_API_KEY") or config.get("api_key")
    if not api_key:
        raise RuntimeError(
            "Missing LLM API key. Set WEREWOLF_LLM_API_KEY or add api_key to config/llm.local.json."
        )
    return ChatCompletionClient(
        api_key=api_key,
        base_url=os.environ.get("WEREWOLF_LLM_BASE_URL") or config.get("base_url", DEFAULT_BASE_URL),
        model=os.environ.get("WEREWOLF_LLM_MODEL") or config.get("model", DEFAULT_MODEL),
        timeout=float(os.environ.get("WEREWOLF_LLM_TIMEOUT") or config.get("timeout", 45.0)),
    )


def load_llm_client_from_env() -> ChatCompletionClient:
    return load_llm_client(config_path=Path("__env_only_config_does_not_exist__.json"))


def create_llm_demo_agents(
    roles: dict[int, Role],
    client: LLMClient | None = None,
    decision_recorder: AgentDecisionRecorder | None = None,
) -> dict[int, LLMPlayerAgent]:
    shared_client = client or load_llm_client()
    return {
        player_id: LLMPlayerAgent(
            player_id=player_id,
            role=role,
            client=shared_client,
            decision_recorder=decision_recorder,
        )
        for player_id, role in sorted(roles.items())
    }


def _load_llm_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"LLM config must be a JSON object: {path}")
    return data
