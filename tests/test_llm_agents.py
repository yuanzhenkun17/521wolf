import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

from playeragent import AgentDecisionRecorder
from werewolf.llm_agents import (
    ChatCompletionClient,
    LLMPlayerAgent,
    create_llm_demo_agents,
    load_llm_client,
    load_llm_client_from_env,
)
from werewolf.models import ActionRequest, ActionType, Observation, Phase, Role
from werewolf.roles import standard_roles


def run(coro):
    return asyncio.run(coro)


def request_for(action_type, candidates=(), role=Role.VILLAGER, metadata=None):
    return ActionRequest(
        player_id=9,
        action_type=action_type,
        phase=Phase.DAY_SPEECH,
        observation=Observation(
            player_id=9,
            self_role=role,
            phase=Phase.DAY_SPEECH,
            day=1,
            alive_players=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12),
            dead_players=(),
            sheriff_id=None,
            public_log=("6号死亡",),
            known_roles={1: Role.WHITE_WOLF_KING} if role is Role.WEREWOLF else {},
            seer_checks={1: Role.WHITE_WOLF_KING.team} if role is Role.SEER else {},
        ),
        candidates=tuple(candidates),
        metadata=metadata or {},
    )


class FakeClient:
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.content


class LLMAgentTests(unittest.TestCase):
    def test_llm_agent_builds_prompt_and_parses_json_response(self):
        client = FakeClient('{"choice":"run","target":null,"text":"我要上警争取警徽","reasoning":"好人需要警徽"}')
        agent = LLMPlayerAgent(player_id=9, role=Role.SEER, client=client)

        response = run(agent.act(request_for(ActionType.SHERIFF_RUN, role=Role.SEER)))
        prompt = client.calls[0][-1]["content"]

        self.assertEqual(response.action_type, ActionType.SHERIFF_RUN)
        self.assertEqual(response.choice, "run")
        self.assertEqual(response.text, "我要上警争取警徽")
        self.assertIn("你是 9 号玩家", prompt)
        self.assertIn("身份: seer", prompt)
        self.assertIn("必须只输出 JSON", prompt)

    def test_llm_agent_keeps_last_sheriff_runner_on_stage(self):
        client = FakeClient('{"choice":"withdraw","target":null,"text":"我退水","reasoning":"信息不足"}')
        agent = LLMPlayerAgent(player_id=9, role=Role.SEER, client=client)

        response = run(
            agent.act(
                request_for(
                    ActionType.SHERIFF_WITHDRAW,
                    candidates=(9,),
                    role=Role.SEER,
                    metadata={"runners": [9], "remaining_runners": [9], "initial_runners": [2, 9]},
                )
            )
        )
        prompt = client.calls[0][-1]["content"]

        self.assertEqual(response.action_type, ActionType.SHERIFF_WITHDRAW)
        self.assertEqual(response.choice, "stay")
        self.assertIn("remaining_runners", prompt)
        self.assertIn("最后一名", prompt)

    def test_llm_agent_falls_back_to_legal_response_when_model_output_is_invalid(self):
        agent = LLMPlayerAgent(player_id=9, role=Role.VILLAGER, client=FakeClient("not json"))

        response = run(agent.act(request_for(ActionType.EXILE_VOTE, candidates=(2, 3))))

        self.assertEqual(response.action_type, ActionType.EXILE_VOTE)
        self.assertEqual(response.target, 2)

    def test_create_llm_demo_agents_creates_one_agent_per_player(self):
        agents = create_llm_demo_agents(standard_roles(), client=FakeClient('{"choice":"pass"}'))

        self.assertEqual(set(agents), set(range(1, 13)))
        self.assertIsInstance(agents[1], LLMPlayerAgent)
        self.assertEqual(agents[1].role, Role.WHITE_WOLF_KING)

    def test_llm_agents_can_record_decisions_to_shared_recorder(self):
        recorder = AgentDecisionRecorder()
        agents = create_llm_demo_agents(
            {9: Role.VILLAGER},
            client=FakeClient('{"choice":"vote","target":2,"text":"投2","reasoning":"2号发言差"}'),
            decision_recorder=recorder,
        )

        response = run(agents[9].act(request_for(ActionType.EXILE_VOTE, candidates=(2, 3))))

        self.assertEqual(response.target, 2)
        self.assertEqual(len(recorder.records), 1)
        self.assertEqual(recorder.records[0].private_reasoning, "2号发言差")

    def test_load_llm_client_from_env_uses_openai_compatible_defaults(self):
        old_env = dict(os.environ)
        try:
            os.environ["WEREWOLF_LLM_API_KEY"] = "test-key"
            os.environ.pop("WEREWOLF_LLM_BASE_URL", None)
            os.environ.pop("WEREWOLF_LLM_MODEL", None)

            client = load_llm_client_from_env()

            self.assertIsInstance(client, ChatCompletionClient)
            self.assertEqual(client.base_url, "https://router.shengsuanyun.com/api/v1")
            self.assertEqual(client.model, "ali/qwen3.5-flash")
            self.assertEqual(client.api_key, "test-key")
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_load_llm_client_reads_local_config_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "llm.local.json"
            config_path.write_text(
                json.dumps(
                    {
                        "api_key": "config-key",
                        "base_url": "https://example.test/api/v1",
                        "model": "demo/model",
                        "timeout": 12,
                    }
                ),
                encoding="utf-8",
            )

            client = load_llm_client(config_path=config_path)

        self.assertEqual(client.api_key, "config-key")
        self.assertEqual(client.base_url, "https://example.test/api/v1")
        self.assertEqual(client.model, "demo/model")
        self.assertEqual(client.timeout, 12)

    def test_env_values_override_config_file(self):
        old_env = dict(os.environ)
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                config_path = Path(temp_dir) / "llm.local.json"
                config_path.write_text(
                    json.dumps({"api_key": "config-key", "model": "config/model"}),
                    encoding="utf-8",
                )
                os.environ["WEREWOLF_LLM_API_KEY"] = "env-key"
                os.environ["WEREWOLF_LLM_MODEL"] = "env/model"

                client = load_llm_client(config_path=config_path)

            self.assertEqual(client.api_key, "env-key")
            self.assertEqual(client.model, "env/model")
        finally:
            os.environ.clear()
            os.environ.update(old_env)


if __name__ == "__main__":
    unittest.main()
