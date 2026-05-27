"""Tests for GoT (Graph-of-Thought) high-conflict reasoning."""

from __future__ import annotations

import asyncio
import json
import unittest

from agent.nodes.got import got_node
from agent.observability.archive import AgentTraceRecorder, DecisionArchive
from agent.reasoning.got import (
    GOT_ACTIONS,
    GoTEvidenceNode,
    GoTHypothesis,
    GoTResult,
    build_got_prompt,
    need_got,
    run_got_selection,
)
from agent.runtime import AgentRuntime
from agent.runtime.context import AgentContext
from engine.actions import ActionType
from engine.models import ActionRequest, Observation, Phase, Role


class StubModel:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.call_count = 0
        self.last_messages: list[dict] = []

    async def complete(self, messages: list[dict], **kwargs) -> str:
        self.call_count += 1
        self.last_messages = list(messages)
        return self.response_text


def _make_request(
    action_type: ActionType = ActionType.EXILE_VOTE,
    *,
    metadata: dict | None = None,
    candidates: tuple[int, ...] = (3, 7, 9),
) -> ActionRequest:
    return ActionRequest(
        player_id=5,
        action_type=action_type,
        phase=Phase.EXILE_VOTE if action_type != ActionType.WITCH_ACT else Phase.NIGHT,
        observation=Observation(
            player_id=5,
            self_role=Role.VILLAGER,
            phase=Phase.EXILE_VOTE,
            day=3,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=(4, 7),
            sheriff_id=5,
            public_log=("P8 发言怀疑 P3", "P9 跟票 P3"),
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=candidates,
        retry_count=0,
        metadata=metadata or {},
    )


def _make_ctx(
    action_type: ActionType = ActionType.EXILE_VOTE,
    *,
    metadata: dict | None = None,
) -> AgentContext:
    request = _make_request(action_type, metadata=metadata)
    ctx = AgentContext(request=request, player_id=5, role="villager")
    ctx.observation_summary = {
        "day": 3,
        "phase": "exile_vote",
        "alive_players": [1, 2, 3, 5, 6, 8, 9, 10],
        "candidates": [3, 7, 9],
    }
    ctx.memory_context = {
        "memory_events": ["P8 怀疑 P3", "P9 跟票 P3"],
        "private_facts": {},
    }
    ctx.belief_context = {
        "top_suspicions": [
            {"player_id": 3, "wolf_prob": 0.61, "evidence": ["被多人踩"]},
            {"player_id": 7, "wolf_prob": 0.55, "evidence": ["发言回避"]},
            {"player_id": 9, "wolf_prob": 0.49, "evidence": ["跟票"]},
        ],
    }
    ctx.selected_skills = ["game_rules", "output_schema", "villager_vote_analysis"]
    ctx.skill_context = "## 通用规则 Skill\n### game_rules\n只能使用可见信息。"
    ctx.messages = [
        {"role": "system", "content": "你是 5 号玩家，身份: villager。"},
        {"role": "user", "content": "当前是第 3 天 exile_vote 阶段。"},
    ]
    return ctx


def _got_response() -> str:
    return json.dumps({
        "evidence_nodes": [
            {
                "node_id": "e1",
                "kind": "speech",
                "summary": "P8 怀疑 P3",
                "source": "public_log",
                "reliability": 0.6,
            },
            {
                "node_id": "e2",
                "kind": "vote",
                "summary": "P9 跟票 P3",
                "source": "memory",
                "reliability": 0.5,
            },
        ],
        "hypotheses": [
            {
                "hypothesis_id": "h1",
                "claim": "P3 是狼，P9 可能跟狼队节奏",
                "supporting_evidence": ["e1", "e2"],
                "conflicting_evidence": [],
                "expected_action": {"choice": "vote", "target": 3},
                "confidence": 0.66,
            },
            {
                "hypothesis_id": "h2",
                "claim": "P3 是被抗推好人，P9 可能是带票狼",
                "supporting_evidence": ["e2"],
                "conflicting_evidence": ["e1"],
                "expected_action": {"choice": "vote", "target": 9},
                "confidence": 0.48,
            },
        ],
        "selected_hypothesis_id": "h1",
        "final_action": {"choice": "vote", "target": 3},
        "public_text": "我更倾向先出3号。",
        "private_reasoning": "证据图中 P3 在主假设下收益最高。",
        "judge_reason": "h1 支持证据更多且反证较少。",
        "confidence": 0.72,
    })


class NeedGotTests(unittest.TestCase):
    def test_got_actions_are_known(self):
        self.assertIn("exile_vote", GOT_ACTIONS)
        self.assertIn("witch_act", GOT_ACTIONS)

    def test_non_key_action_returns_false(self):
        ctx = _make_ctx(ActionType.SPEAK, metadata={"enable_got": True})
        self.assertFalse(need_got(ctx))

    def test_explicit_metadata_enables_got(self):
        ctx = _make_ctx(metadata={"enable_got": True})
        self.assertTrue(need_got(ctx))

    def test_reasoning_mode_enables_got(self):
        ctx = _make_ctx(metadata={"reasoning_mode": "got"})
        self.assertTrue(need_got(ctx))

    def test_belief_conflict_can_enable_got(self):
        ctx = _make_ctx()
        self.assertTrue(need_got(ctx))

    def test_low_conflict_skips_got(self):
        ctx = _make_ctx()
        ctx.belief_context = {"top_suspicions": [{"player_id": 3, "wolf_prob": 0.9}]}
        self.assertFalse(need_got(ctx))


class GoTDataTests(unittest.TestCase):
    def test_evidence_node_to_dict(self):
        node = GoTEvidenceNode("e1", "speech", "P3 发言矛盾", "public_log", 0.7)
        data = node.to_dict()
        self.assertEqual(data["node_id"], "e1")
        self.assertEqual(data["reliability"], 0.7)

    def test_hypothesis_to_dict(self):
        hyp = GoTHypothesis(
            "h1",
            "P3 是狼",
            supporting_evidence=["e1"],
            conflicting_evidence=["e2"],
            expected_action={"choice": "vote", "target": 3},
            confidence=0.65,
        )
        data = hyp.to_dict()
        self.assertEqual(data["hypothesis_id"], "h1")
        self.assertEqual(data["expected_action"]["target"], 3)

    def test_result_selected_property(self):
        result = GoTResult(
            enabled=True,
            hypotheses=[
                GoTHypothesis("h1", "A"),
                GoTHypothesis("h2", "B"),
            ],
            selected_hypothesis_id="h2",
        )
        self.assertEqual(result.selected.hypothesis_id, "h2")


class BuildGotPromptTests(unittest.TestCase):
    def test_prompt_contains_graph_requirements(self):
        ctx = _make_ctx(metadata={"enable_got": True})
        messages = build_got_prompt(ctx)
        combined = "\n".join(msg["content"] for msg in messages)
        self.assertIn("Graph-of-Thought", combined)
        self.assertIn("evidence_nodes", combined)
        self.assertIn("hypotheses", combined)
        self.assertIn("villager_vote_analysis", combined)


class RunGotSelectionTests(unittest.TestCase):
    def test_parses_valid_response(self):
        ctx = _make_ctx(metadata={"enable_got": True})
        result = asyncio.run(run_got_selection(ctx, StubModel(_got_response())))
        self.assertTrue(result.enabled)
        self.assertEqual(len(result.evidence_nodes), 2)
        self.assertEqual(len(result.hypotheses), 2)
        self.assertEqual(result.selected_hypothesis_id, "h1")
        self.assertEqual(result.final_action, {"choice": "vote", "target": 3})
        self.assertEqual(result.public_text, "我更倾向先出3号。")

    def test_uses_selected_expected_action_when_final_action_missing(self):
        data = json.loads(_got_response())
        data.pop("final_action")
        ctx = _make_ctx(metadata={"enable_got": True})
        result = asyncio.run(run_got_selection(ctx, StubModel(json.dumps(data))))
        self.assertEqual(result.final_action, {"choice": "vote", "target": 3})

    def test_fails_on_too_few_hypotheses(self):
        data = json.loads(_got_response())
        data["hypotheses"] = data["hypotheses"][:1]
        ctx = _make_ctx(metadata={"enable_got": True})
        with self.assertRaises(RuntimeError):
            asyncio.run(run_got_selection(ctx, StubModel(json.dumps(data))))

    def test_fails_on_missing_selected_hypothesis(self):
        data = json.loads(_got_response())
        data["selected_hypothesis_id"] = "missing"
        ctx = _make_ctx(metadata={"enable_got": True})
        with self.assertRaises(RuntimeError):
            asyncio.run(run_got_selection(ctx, StubModel(json.dumps(data))))


class GotNodeTests(unittest.TestCase):
    def test_skips_when_not_needed(self):
        ctx = _make_ctx()
        ctx.belief_context = {"top_suspicions": [{"player_id": 3, "wolf_prob": 0.9}]}
        result = asyncio.run(got_node(ctx, StubModel(_got_response())))
        self.assertIs(result, ctx)
        self.assertFalse(result.got_enabled)
        self.assertEqual(result.source, "llm")

    def test_sets_got_fields_on_success(self):
        ctx = _make_ctx(metadata={"enable_got": True})
        result = asyncio.run(got_node(ctx, StubModel(_got_response())))
        self.assertTrue(result.got_enabled)
        self.assertEqual(result.source, "got")
        self.assertEqual(len(result.got_hypotheses), 2)
        self.assertEqual(len(result.got_evidence_nodes), 2)
        self.assertEqual(result.got_judge_reason, "h1 支持证据更多且反证较少。")
        loaded = json.loads(result.raw_output)
        self.assertEqual(loaded["target"], 3)
        self.assertEqual(loaded["public_text"], "我更倾向先出3号。")

    def test_falls_back_on_invalid_json(self):
        ctx = _make_ctx(metadata={"enable_got": True})
        result = asyncio.run(got_node(ctx, StubModel("not json")))
        self.assertFalse(result.got_enabled)
        self.assertEqual(result.source, "llm")
        self.assertIn("GoT failed", result.errors[0])


class GotArchiveTests(unittest.TestCase):
    def test_archive_from_context_includes_got_fields(self):
        ctx = _make_ctx(metadata={"enable_got": True})
        ctx.got_enabled = True
        ctx.got_evidence_nodes = [{"node_id": "e1"}]
        ctx.got_hypotheses = [{"hypothesis_id": "h1"}]
        ctx.got_judge_reason = "选择 h1"
        ctx.source = "got"

        archive = DecisionArchive.from_context(ctx)
        data = archive.to_dict()
        self.assertEqual(data["got_evidence_nodes"], [{"node_id": "e1"}])
        self.assertEqual(data["got_hypotheses"], [{"hypothesis_id": "h1"}])
        self.assertEqual(data["got_judge_reason"], "选择 h1")


class GotRuntimeIntegrationTests(unittest.TestCase):
    def test_runtime_uses_got_and_skips_tot(self):
        model = StubModel(_got_response())
        trace_recorder = AgentTraceRecorder()
        runtime = AgentRuntime(
            player_id=5,
            role=Role.VILLAGER,
            model=model,
            trace_recorder=trace_recorder,
        )
        response = asyncio.run(runtime.act(_make_request(metadata={"enable_got": True})))

        self.assertEqual(model.call_count, 2)  # skill_select + got
        self.assertEqual(response.target, 3)
        self.assertEqual(response.choice, "vote")
        traces = trace_recorder.snapshot()
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].source, "got")
        self.assertEqual(len(traces[0].got_hypotheses), 2)
        self.assertEqual(traces[0].got_judge_reason, "h1 支持证据更多且反证较少。")


if __name__ == "__main__":
    unittest.main()
