import asyncio
import unittest

from werewolf.agent_runtime import AgentMemory, AgentRuntime
from werewolf.agent_runtime.adapters import ModelAdapter
from werewolf.models import ActionRequest, ActionType, Observation, Phase, Role, Team


def run(coro):
    return asyncio.run(coro)


def request_for(
    action_type,
    *,
    player_id=9,
    role=Role.VILLAGER,
    candidates=(),
    known_roles=None,
    seer_checks=None,
    metadata=None,
):
    return ActionRequest(
        player_id=player_id,
        action_type=action_type,
        phase=Phase.DAY_SPEECH,
        observation=Observation(
            player_id=player_id,
            self_role=role,
            phase=Phase.DAY_SPEECH,
            day=1,
            alive_players=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12),
            dead_players=(6,),
            sheriff_id=2,
            public_log=("Player 6 died by werewolf.",),
            known_roles=known_roles or {},
            seer_checks=seer_checks or {},
            metadata=metadata or {},
        ),
        candidates=tuple(candidates),
        metadata=metadata or {},
    )


class FakeAdapter(ModelAdapter):
    def __init__(self, content):
        self.content = content
        self.calls = []

    async def complete(self, messages):
        self.calls.append(messages)
        return self.content


class AgentRuntimeTests(unittest.TestCase):
    def test_runtime_parses_model_json_into_action_response(self):
        adapter = FakeAdapter('{"choice":"run","target":null,"text":"我要竞选","reasoning":"争警徽"}')
        runtime = AgentRuntime(player_id=9, role=Role.SEER, model=adapter)

        response = run(runtime.act(request_for(ActionType.SHERIFF_RUN, role=Role.SEER)))

        self.assertEqual(response.action_type, ActionType.SHERIFF_RUN)
        self.assertEqual(response.choice, "run")
        self.assertEqual(response.text, "我要竞选")
        self.assertIn("必须只输出 JSON", adapter.calls[0][-1]["content"])

    def test_runtime_falls_back_when_model_output_is_not_json(self):
        runtime = AgentRuntime(player_id=9, role=Role.VILLAGER, model=FakeAdapter("not json"))

        response = run(runtime.act(request_for(ActionType.EXILE_VOTE, candidates=(2, 3))))

        self.assertEqual(response.action_type, ActionType.EXILE_VOTE)
        self.assertEqual(response.target, 2)

    def test_runtime_keeps_last_sheriff_runner_on_stage(self):
        runtime = AgentRuntime(
            player_id=9,
            role=Role.SEER,
            model=FakeAdapter('{"choice":"withdraw","target":null,"text":"我退水"}'),
        )

        response = run(
            runtime.act(
                request_for(
                    ActionType.SHERIFF_WITHDRAW,
                    role=Role.SEER,
                    candidates=(9,),
                    metadata={"runners": [9], "remaining_runners": [9], "initial_runners": [2, 9]},
                )
            )
        )

        self.assertEqual(response.choice, "stay")

    def test_memory_context_keeps_private_info_view_scoped(self):
        wolf_memory = AgentMemory(player_id=7, role=Role.WEREWOLF)
        villager_memory = AgentMemory(player_id=6, role=Role.VILLAGER)
        wolf_request = request_for(
            ActionType.SPEAK,
            player_id=7,
            role=Role.WEREWOLF,
            known_roles={4: Role.WEREWOLF, 5: Role.WEREWOLF},
        )
        villager_request = request_for(ActionType.SPEAK, player_id=6, role=Role.VILLAGER)

        wolf_context = wolf_memory.build_context(wolf_request)
        villager_context = villager_memory.build_context(villager_request)

        self.assertEqual(wolf_context["private_facts"]["known_roles"], {4: "werewolf", 5: "werewolf"})
        self.assertEqual(villager_context["private_facts"]["known_roles"], {})

    def test_memory_context_records_seer_checks_as_private_facts(self):
        memory = AgentMemory(player_id=9, role=Role.SEER)

        context = memory.build_context(
            request_for(ActionType.SPEAK, role=Role.SEER, seer_checks={5: Team.WEREWOLVES})
        )

        self.assertEqual(context["private_facts"]["seer_checks"], {5: "werewolves"})


if __name__ == "__main__":
    unittest.main()
