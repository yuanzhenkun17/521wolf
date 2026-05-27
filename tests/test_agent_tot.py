"""Tests for ToT (Tree-of-Thought) multi-candidate reasoning.

Covers need_tot, data structures, candidate generation, judge, node,
fallback behavior, and archive integration.
"""

from __future__ import annotations

import json
import unittest

from agent.observability.archive import AgentTraceRecorder
from agent.runtime.context import AgentContext
from agent.nodes.tot import tot_node
from agent.reasoning.tot import (
    KEY_ACTIONS,
    ToTCandidate,
    ToTResult,
    _build_tot_prompt,
    _normalize_id,
    need_tot,
    run_tot_selection,
)
from agent.observability.archive import DecisionArchive
from agent.runtime import AgentRuntime
from engine.actions import ActionType
from engine.models import ActionRequest, Observation, Phase, Role


# ── stub model ─────────────────────────────────────────────────────────────────


class StubModel:
    """Returns a fixed JSON string; records last messages."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_messages: list[dict] = []

    async def complete(self, messages: list[dict], **kwargs) -> str:
        self.last_messages = list(messages)
        return self.response_text


# ── helpers ────────────────────────────────────────────────────────────────────


def _make_request(action_type: ActionType = ActionType.EXILE_VOTE) -> ActionRequest:
    return ActionRequest(
        player_id=5,
        action_type=action_type,
        phase=Phase.EXILE_VOTE if action_type != ActionType.WITCH_ACT else Phase.NIGHT,
        observation=Observation(
            player_id=5,
            self_role=Role.VILLAGER,
            phase=Phase.EXILE_VOTE,
            day=2,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=(4, 7),
            sheriff_id=5,
            public_log=["P8 发言怀疑 P3"],
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=(3, 7, 9),
        retry_count=0,
        metadata={},
    )


def _make_ctx(
    action_type: ActionType = ActionType.EXILE_VOTE,
) -> AgentContext:
    request = _make_request(action_type)
    ctx = AgentContext(request=request, player_id=5, role="villager")
    ctx.observation_summary = {
        "day": 2,
        "phase": "exile_vote",
        "alive_players": [1, 2, 3, 5, 6, 8, 9, 10],
        "candidates": [3, 7, 9],
    }
    ctx.memory_context = {"memory_events": ["P8发言"], "private_facts": {}}
    ctx.belief_context = {"top_suspicions": [{"player_id": 7, "reason": "可疑"}]}
    ctx.selected_skills = ["game_rules", "output_schema", "villager_vote_analysis"]
    ctx.messages = [
        {"role": "system", "content": "你是 5 号玩家，身份: villager。"},
        {"role": "user", "content": "当前是第 2 天 exile_vote 阶段。"},
    ]
    ctx.raw_output = ""
    ctx.confidence = 0.8
    return ctx


# ── need_tot tests ─────────────────────────────────────────────────────────────


class NeedTotTests(unittest.TestCase):
    """Test need_tot action-type gating."""

    def test_key_actions_return_true(self):
        for action in KEY_ACTIONS:
            with self.subTest(action=action):
                self.assertTrue(need_tot(action))

    def test_speak_returns_false(self):
        self.assertFalse(need_tot("speak"))

    def test_last_word_returns_false(self):
        self.assertFalse(need_tot("last_word"))

    def test_guard_protect_not_in_key_actions(self):
        self.assertFalse(need_tot("guard_protect"))


# ── ToTCandidate tests ─────────────────────────────────────────────────────────


class ToTCandidateTests(unittest.TestCase):
    def test_construction(self):
        c = ToTCandidate(
            candidate_id="a",
            action={"choice": "vote", "target": 3},
            public_text="我怀疑3号",
            private_reasoning="3号发言矛盾",
            expected_gain="票出狼人",
            risk="可能暴露身份",
        )
        self.assertEqual(c.candidate_id, "a")
        self.assertEqual(c.action["choice"], "vote")

    def test_to_dict(self):
        c = ToTCandidate(
            candidate_id="b",
            action={"choice": "vote", "target": 7},
            public_text="出7号",
            private_reasoning="7号划水",
            expected_gain="压缩狼坑",
            risk="错票好人",
        )
        d = c.to_dict()
        self.assertEqual(d["candidate_id"], "b")
        self.assertIn("action", d)
        self.assertIn("risk", d)

    def test_to_dict_json_serializable(self):
        c = ToTCandidate(
            candidate_id="c",
            action={"choice": "pass"},
            public_text="过",
            private_reasoning="无",
            expected_gain="无",
            risk="无",
        )
        json_str = json.dumps(c.to_dict(), ensure_ascii=False)
        loaded = json.loads(json_str)
        self.assertEqual(loaded["candidate_id"], "c")


# ── ToTResult tests ────────────────────────────────────────────────────────────


class ToTResultTests(unittest.TestCase):
    def test_selected_property(self):
        candidates = [
            ToTCandidate("a", {"choice": "vote", "target": 3}, "a", "a", "a", "a"),
            ToTCandidate("b", {"choice": "vote", "target": 7}, "b", "b", "b", "b"),
        ]
        result = ToTResult(
            enabled=True,
            candidates=candidates,
            selected_id="b",
            judge_reason="7号更可疑",
            final_action={"choice": "vote", "target": 7},
        )
        self.assertIsNotNone(result.selected)
        self.assertEqual(result.selected.candidate_id, "b")

    def test_selected_none_when_not_found(self):
        result = ToTResult(enabled=True, selected_id="x")
        self.assertIsNone(result.selected)

    def test_to_dict(self):
        candidates = [ToTCandidate("a", {}, "a", "a", "a", "a")]
        result = ToTResult(
            enabled=True,
            candidates=candidates,
            selected_id="a",
            judge_reason="test",
            final_action={},
        )
        d = result.to_dict()
        self.assertTrue(d["enabled"])
        self.assertEqual(len(d["candidates"]), 1)
        self.assertEqual(d["judge_reason"], "test")


# ── prompt builder ─────────────────────────────────────────────────────────────


class BuildTotPromptTests(unittest.TestCase):
    def test_returns_messages(self):
        ctx = _make_ctx()
        msgs = _build_tot_prompt(ctx)
        self.assertGreater(len(msgs), 0)
        self.assertEqual(msgs[0]["role"], "system")
        combined = "\n".join(m["content"] for m in msgs)
        self.assertIn("候选方案", combined)

    def test_contains_action_type(self):
        ctx = _make_ctx(ActionType.WITCH_ACT)
        msgs = _build_tot_prompt(ctx)
        combined = "\n".join(m["content"] for m in msgs)
        self.assertIn("witch_act", combined)

    def test_contains_context_info(self):
        ctx = _make_ctx(ActionType.EXILE_VOTE)
        msgs = _build_tot_prompt(ctx)
        combined = "\n".join(m["content"] for m in msgs)
        self.assertIn("exile_vote", combined)
        self.assertIn("selected_id", combined)
        self.assertIn("candidates", combined)


# ── run_tot_selection tests ────────────────────────────────────────────────────


class RunTotSelectionTests(unittest.TestCase):
    def test_parses_valid_response(self):
        model = StubModel(json.dumps({
            "candidates": [
                {
                    "candidate_id": "a",
                    "action": {"choice": "vote", "target": 3},
                    "public_text": "出3号",
                    "private_reasoning": "3号可疑",
                    "expected_gain": "票出狼",
                    "risk": "低",
                },
                {
                    "candidate_id": "b",
                    "action": {"choice": "vote", "target": 7},
                    "public_text": "出7号",
                    "private_reasoning": "7号划水",
                    "expected_gain": "压缩狼坑",
                    "risk": "可能错",
                },
                {
                    "candidate_id": "c",
                    "action": {"choice": "vote", "target": 9},
                    "public_text": "出9号",
                    "private_reasoning": "9号跟票",
                    "expected_gain": "查跟票行为",
                    "risk": "信息不足",
                },
            ],
            "selected_id": "b",
            "reason": "7号更可疑",
        }))
        ctx = _make_ctx()
        result = asyncio_run(run_tot_selection(ctx, model))
        self.assertTrue(result.enabled)
        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(result.candidates[0].candidate_id, "a")
        self.assertEqual(result.candidates[1].action["target"], 7)
        self.assertEqual(result.candidates[2].public_text, "出9号")
        self.assertEqual(result.selected_id, "b")
        self.assertEqual(result.final_action, {"choice": "vote", "target": 7})
        self.assertEqual(result.judge_reason, "7号更可疑")

    def test_fails_on_empty_candidates(self):
        model = StubModel(json.dumps({"candidates": [], "selected_id": "a", "reason": ""}))
        ctx = _make_ctx()
        with self.assertRaises(RuntimeError):
            asyncio_run(run_tot_selection(ctx, model))

    def test_fails_on_too_few_candidates(self):
        model = StubModel(json.dumps({
            "candidates": [
                {"candidate_id": "a", "action": {}, "public_text": "", "private_reasoning": "", "expected_gain": "", "risk": ""},
                {"candidate_id": "b", "action": {}, "public_text": "", "private_reasoning": "", "expected_gain": "", "risk": ""},
            ],
            "selected_id": "a",
            "reason": "",
        }))
        ctx = _make_ctx()
        with self.assertRaises(RuntimeError):
            asyncio_run(run_tot_selection(ctx, model))

    def test_accepts_markdown_wrapped_json(self):
        model = StubModel("""```json
{
  "candidates": [
    {"candidate_id": "a", "action": {"choice": "vote", "target": 3}, "public_text": "出3号", "private_reasoning": "3可疑", "expected_gain": "票出狼", "risk": "低"},
    {"candidate_id": "b", "action": {"choice": "vote", "target": 7}, "public_text": "出7号", "private_reasoning": "7可疑", "expected_gain": "压缩狼坑", "risk": "中"},
    {"candidate_id": "c", "action": {"choice": "vote", "target": 9}, "public_text": "出9号", "private_reasoning": "9可疑", "expected_gain": "测试票型", "risk": "中"}
  ],
  "selected_id": "a",
  "reason": "3号最可疑"
}
```""")
        ctx = _make_ctx()
        result = asyncio_run(run_tot_selection(ctx, model))
        self.assertEqual(len(result.candidates), 3)
        self.assertEqual(result.selected_id, "a")

    def test_assigns_positional_ids(self):
        """Candidate IDs are forced by position, ignoring LLM-provided values."""
        model = StubModel(json.dumps({
            "candidates": [
                {"action": {"choice": "vote", "target": 3}, "public_text": "", "private_reasoning": "", "expected_gain": "", "risk": ""},
                {"action": {"choice": "vote", "target": 7}, "public_text": "", "private_reasoning": "", "expected_gain": "", "risk": ""},
                {"action": {"choice": "vote", "target": 9}, "public_text": "", "private_reasoning": "", "expected_gain": "", "risk": ""},
            ],
            "selected_id": "c",
            "reason": "",
        }))
        ctx = _make_ctx()
        result = asyncio_run(run_tot_selection(ctx, model))
        self.assertEqual(result.candidates[0].candidate_id, "a")
        self.assertEqual(result.candidates[1].candidate_id, "b")
        self.assertEqual(result.candidates[2].candidate_id, "c")
        self.assertEqual(result.final_action, {"choice": "vote", "target": 9})

    def test_rejects_invalid_selected_id(self):
        model = StubModel(json.dumps({
            "candidates": [
                {"candidate_id": "a", "action": {"choice": "vote", "target": 3}, "public_text": "", "private_reasoning": "", "expected_gain": "", "risk": ""},
                {"candidate_id": "b", "action": {"choice": "vote", "target": 7}, "public_text": "", "private_reasoning": "", "expected_gain": "", "risk": ""},
                {"candidate_id": "c", "action": {"choice": "vote", "target": 9}, "public_text": "", "private_reasoning": "", "expected_gain": "", "risk": ""},
            ],
            "selected_id": "z",
            "reason": "",
        }))
        ctx = _make_ctx()
        with self.assertRaises(RuntimeError):
            asyncio_run(run_tot_selection(ctx, model))


# ── _normalize_id tests ────────────────────────────────────────────────────────


class NormalizeIdTests(unittest.TestCase):
    def test_passes_through_a_b_c(self):
        self.assertEqual(_normalize_id("a"), "a")
        self.assertEqual(_normalize_id("b"), "b")
        self.assertEqual(_normalize_id("c"), "c")

    def test_handles_uppercase(self):
        self.assertEqual(_normalize_id("A"), "a")
        self.assertEqual(_normalize_id("B"), "b")

    def test_handles_numeric(self):
        self.assertEqual(_normalize_id("1"), "a")
        self.assertEqual(_normalize_id("2"), "b")
        self.assertEqual(_normalize_id("3"), "c")

    def test_extracts_from_prefixed_text(self):
        self.assertEqual(_normalize_id("候选 a"), "a")
        self.assertEqual(_normalize_id("option b"), "b")
        self.assertEqual(_normalize_id("方案a：最好"), "a")

    def test_extracts_from_messy_text(self):
        self.assertEqual(_normalize_id("  A  "), "a")
        self.assertEqual(_normalize_id("选项 B: 最优"), "b")


# ── tot_node tests ─────────────────────────────────────────────────────────────


class TotNodeTests(unittest.TestCase):
    """Test tot_node integration — both success and fallback paths."""

    def test_skips_non_key_action(self):
        ctx = _make_ctx(ActionType.SPEAK)
        result = asyncio_run(tot_node(ctx, StubModel("")))
        self.assertIs(result, ctx)
        self.assertFalse(ctx.tot_enabled)
        self.assertEqual(ctx.source, "llm")  # unchanged

    def test_sets_tot_fields_on_success(self):
        model = StubModel(json.dumps({
            "candidates": [
                {
                    "candidate_id": "a",
                    "action": {"choice": "vote", "target": 3},
                    "public_text": "出3号",
                    "private_reasoning": "3可疑",
                    "expected_gain": "票出狼",
                    "risk": "低",
                },
                {
                    "candidate_id": "b",
                    "action": {"choice": "vote", "target": 7},
                    "public_text": "出7号",
                    "private_reasoning": "7可疑",
                    "expected_gain": "压缩狼坑",
                    "risk": "中",
                },
                {
                    "candidate_id": "c",
                    "action": {"choice": "vote", "target": 9},
                    "public_text": "出9号",
                    "private_reasoning": "9可疑",
                    "expected_gain": "测试票型",
                    "risk": "中",
                },
            ],
            "selected_id": "a",
            "reason": "3号最可疑",
        }))
        ctx = _make_ctx(ActionType.EXILE_VOTE)
        result = asyncio_run(tot_node(ctx, model))
        self.assertTrue(result.tot_enabled)
        self.assertEqual(result.source, "tot")
        self.assertGreater(len(result.tot_candidates), 0)
        self.assertTrue(result.tot_judge_reason)
        # tot_node sets raw_output to JSON-parsable string for parse_node
        self.assertTrue(result.raw_output)
        loaded = json.loads(result.raw_output)
        self.assertIn("choice", loaded)
        self.assertEqual(loaded["choice"], "vote")
        self.assertEqual(loaded["target"], 3)
        self.assertEqual(loaded["public_text"], "出3号")

    def test_falls_back_on_llm_error(self):
        class FailingModel:
            async def complete(self, messages, **kwargs):
                raise RuntimeError("LLM timeout")

        ctx = _make_ctx(ActionType.EXILE_VOTE)
        result = asyncio_run(tot_node(ctx, FailingModel()))
        self.assertFalse(result.tot_enabled)
        self.assertEqual(result.source, "llm")  # unchanged
        self.assertGreater(len(result.errors), 0)
        self.assertIn("ToT failed", result.errors[0])

    def test_falls_back_on_invalid_json(self):
        ctx = _make_ctx(ActionType.EXILE_VOTE)
        result = asyncio_run(tot_node(ctx, StubModel("not json at all")))
        self.assertFalse(result.tot_enabled)
        self.assertEqual(result.source, "llm")
        self.assertGreater(len(result.errors), 0)

    def test_falls_back_on_empty_candidates(self):
        ctx = _make_ctx(ActionType.EXILE_VOTE)
        result = asyncio_run(tot_node(ctx, StubModel(json.dumps({"candidates": [], "selected_id": "a"}))))
        self.assertFalse(result.tot_enabled)
        self.assertEqual(result.source, "llm")


# ── archive integration ────────────────────────────────────────────────────────


class ToTArchiveTests(unittest.TestCase):
    def test_archive_from_context_includes_tot_fields(self):
        ctx = _make_ctx()
        ctx.tot_enabled = True
        ctx.tot_candidates = [
            {"candidate_id": "a", "action": {"choice": "vote", "target": 3}},
            {"candidate_id": "b", "action": {"choice": "vote", "target": 7}},
        ]
        ctx.tot_judge_reason = "7号更可疑"
        ctx.source = "tot"

        archive = DecisionArchive.from_context(ctx, index=0)
        self.assertEqual(len(archive.tot_candidates), 2)
        self.assertEqual(archive.tot_judge_reason, "7号更可疑")

    def test_archive_to_dict_serializes_tot_data(self):
        ctx = _make_ctx()
        ctx.tot_enabled = True
        ctx.tot_candidates = [
            {"candidate_id": "a", "action": {"choice": "vote", "target": 3}},
        ]
        ctx.tot_judge_reason = "test"
        ctx.source = "tot"

        archive = DecisionArchive.from_context(ctx)
        d = archive.to_dict()
        self.assertEqual(len(d["tot_candidates"]), 1)
        self.assertEqual(d["tot_judge_reason"], "test")

    def test_empty_tot_fields_by_default(self):
        ctx = _make_ctx()
        archive = DecisionArchive.from_context(ctx)
        self.assertEqual(archive.tot_candidates, [])
        self.assertEqual(archive.tot_judge_reason, "")

    def test_tot_fields_json_serializable(self):
        ctx = _make_ctx()
        ctx.tot_candidates = [{"candidate_id": "a", "action": {"choice": "pass"}}]
        ctx.tot_judge_reason = "reason"
        archive = DecisionArchive.from_context(ctx)
        json_str = json.dumps(archive.to_dict(), ensure_ascii=False)
        loaded = json.loads(json_str)
        self.assertEqual(len(loaded["tot_candidates"]), 1)
        self.assertEqual(loaded["tot_judge_reason"], "reason")


class ToTRuntimeIntegrationTests(unittest.TestCase):
    def test_runtime_preserves_tot_source_and_archive_fields(self):
        class SingleCallModel:
            def __init__(self):
                self.call_count = 0

            async def complete(self, messages, **kwargs):
                self.call_count += 1
                return json.dumps({
                    "candidates": [
                        {
                            "candidate_id": "a",
                            "action": {"choice": "vote", "target": 3},
                            "public_text": "出3号",
                            "private_reasoning": "3可疑",
                            "expected_gain": "票出狼",
                            "risk": "低",
                        },
                        {
                            "candidate_id": "b",
                            "action": {"choice": "vote", "target": 7},
                            "public_text": "出7号",
                            "private_reasoning": "7可疑",
                            "expected_gain": "压缩狼坑",
                            "risk": "中",
                        },
                        {
                            "candidate_id": "c",
                            "action": {"choice": "vote", "target": 9},
                            "public_text": "出9号",
                            "private_reasoning": "9可疑",
                            "expected_gain": "测试票型",
                            "risk": "中",
                        },
                    ],
                    "selected_id": "a",
                    "reason": "3号最可疑",
                })

        trace_recorder = AgentTraceRecorder()
        runtime = AgentRuntime(
            player_id=5,
            role=Role.VILLAGER,
            model=SingleCallModel(),
            trace_recorder=trace_recorder,
        )
        response = asyncio_run(runtime.act(_make_request(ActionType.EXILE_VOTE)))

        self.assertEqual(response.target, 3)
        self.assertEqual(response.choice, "vote")
        traces = trace_recorder.snapshot()
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].source, "tot")
        self.assertEqual(len(traces[0].tot_candidates), 3)
        self.assertEqual(traces[0].tot_judge_reason, "3号最可疑")


# ── async helper ───────────────────────────────────────────────────────────────


def asyncio_run(coro):
    """Run an async function synchronously for tests."""
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
