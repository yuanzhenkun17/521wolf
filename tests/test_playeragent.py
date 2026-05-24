import asyncio
import json
import os
import tempfile
import unittest

from playeragent import AgentDecisionRecorder, AgentMemory, AgentRuntime, BeliefState
from playeragent.adapters import ModelAdapter
from playeragent.strategies import strategy_for
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
            dead_players=(),
            sheriff_id=None,
            public_log=("3号发言怀疑5号", "6号投票给2号"),
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


class PlayerAgentArchitectureTests(unittest.TestCase):
    def test_runtime_records_private_reasoning_separately_from_public_text(self):
        runtime = AgentRuntime(
            player_id=9,
            role=Role.VILLAGER,
            model=FakeAdapter(
                '{"choice":"vote","target":2,"text":"我投2号，因为他的票型很差",'
                '"reasoning":"私有判断：2号可能是狼，先推动放逐",'
                '"alternatives":[3],"rejected_reasons":["3号暂时证据不足"]}'
            ),
        )

        response = run(runtime.act(request_for(ActionType.EXILE_VOTE, candidates=(2, 3))))

        self.assertEqual(response.target, 2)
        self.assertEqual(response.text, "我投2号，因为他的票型很差")
        self.assertEqual(runtime.memory.decision_history[0].private_reasoning, "私有判断：2号可能是狼，先推动放逐")
        self.assertNotIn("私有判断", response.text)
        self.assertEqual(runtime.memory.decision_history[0].source, "llm")
        self.assertEqual(runtime.memory.decision_history[0].player_id, 9)
        self.assertEqual(runtime.memory.decision_history[0].candidates, [2, 3])

    def test_runtime_creates_fallback_decision_when_model_output_is_invalid(self):
        runtime = AgentRuntime(player_id=9, role=Role.VILLAGER, model=FakeAdapter("not json"))

        response = run(runtime.act(request_for(ActionType.EXILE_VOTE, candidates=(2, 3))))

        decision = runtime.memory.decision_history[0]
        self.assertEqual(response.target, 2)
        self.assertEqual(decision.source, "fallback")
        self.assertIn("回退动作", decision.private_reasoning)
        self.assertEqual(decision.selected_target, 2)

    def test_decision_recorder_writes_jsonl(self):
        runtime = AgentRuntime(
            player_id=9,
            role=Role.VILLAGER,
            model=FakeAdapter('{"choice":"vote","target":2,"text":"投2","reasoning":"2号票型差"}'),
        )
        run(runtime.act(request_for(ActionType.EXILE_VOTE, candidates=(2, 3))))
        recorder = AgentDecisionRecorder()
        recorder.record(runtime.memory.decision_history[0])

        with tempfile.TemporaryDirectory() as temp_dir:
            path = recorder.write_jsonl(os.path.join(temp_dir, "game.agent.jsonl"))
            data = json.loads(path.read_text(encoding="utf-8").strip())

        self.assertEqual(data["player_id"], 9)
        self.assertEqual(data["action_type"], "exile_vote")
        self.assertEqual(data["private_reasoning"], "2号票型差")

    def test_belief_is_scoped_to_each_player_private_view(self):
        wolf_belief = BeliefState(player_id=7, role=Role.WEREWOLF)
        villager_belief = BeliefState(player_id=6, role=Role.VILLAGER)

        wolf_belief.update_from_request(
            request_for(
                ActionType.SPEAK,
                player_id=7,
                role=Role.WEREWOLF,
                known_roles={4: Role.WEREWOLF},
            )
        )
        villager_belief.update_from_request(request_for(ActionType.SPEAK, player_id=6, role=Role.VILLAGER))

        self.assertGreater(wolf_belief.players[4].trust, 0.8)
        self.assertEqual(villager_belief.players[4].possible_roles, {})
        self.assertEqual(villager_belief.players[4].trust, 0.5)

    def test_seer_checks_update_belief_without_global_state(self):
        belief = BeliefState(player_id=12, role=Role.SEER)

        belief.update_from_request(
            request_for(ActionType.SPEAK, player_id=12, role=Role.SEER, seer_checks={3: Team.WEREWOLVES})
        )

        self.assertEqual(belief.players[3].suspicion, 1.0)
        self.assertIn("自己的预言家查验显示狼人阵营", belief.players[3].reasons)

    def test_memory_parses_structured_public_events_and_belief_consumes_them(self):
        public_log = (
            json.dumps(
                {
                    "day": 1,
                    "phase": "day_speech",
                    "type": "speak",
                    "actor": 3,
                    "target": None,
                    "content": "我是预言家，我怀疑5号，5号像狼。",
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "day": 1,
                    "phase": "exile_vote",
                    "type": "exile_vote",
                    "actor": 6,
                    "target": 5,
                    "content": "6号投给5号",
                },
                ensure_ascii=False,
            ),
        )
        request = request_for(ActionType.SPEAK)
        request.observation.public_log = public_log
        memory = AgentMemory(player_id=9, role=Role.VILLAGER)
        belief = BeliefState(player_id=9, role=Role.VILLAGER)

        memory.build_context(request)
        belief.build_context(request, memory)

        self.assertEqual(memory.claims_seen[3], "seer")
        self.assertIn(5, memory.suspicions)
        self.assertGreater(belief.players[5].suspicion, 0.55)
        self.assertEqual(belief.players[3].possible_roles["seer"], 0.55)

    def test_role_strategy_provides_role_specific_advice(self):
        request = request_for(
            ActionType.WEREWOLF_KILL,
            player_id=7,
            role=Role.WEREWOLF,
            candidates=(4, 5, 6),
            known_roles={4: Role.WEREWOLF},
        )
        belief = BeliefState(player_id=7, role=Role.WEREWOLF)
        belief.update_from_request(request)

        advice = strategy_for(Role.WEREWOLF).advise(request, memory=None, belief=belief)

        self.assertIn(4, advice.avoid_targets)
        self.assertIn("不能选择狼队友", " ".join(advice.private_notes))


if __name__ == "__main__":
    unittest.main()
