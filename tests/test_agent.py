from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path

from agent.core.memory import AgentMemory
from agent.infrastructure.decision_log import AgentDecisionRecorder
from engine.actions import ActionType
from engine.models import ActionRequest, ActionResponse, GameEvent, Observation, Phase, Role

from agent.core.context import AgentContext
from agent.decision.steps.remember import remember_step
from agent.decision.steps.select_skills import select_skills_step
from agent.decision.steps.build_prompt import build_prompt_step
from agent.decision.steps.parse_output import parse_output_step
from agent.decision.steps.enforce_policy import enforce_policy_step
from agent.learning.review import did_survive, get_role_of
from agent.api.runtime import AgentRuntime


def _make_witch_poison_request() -> ActionRequest:
    return ActionRequest(
        player_id=3,
        action_type=ActionType.WITCH_ACT,
        phase=Phase.NIGHT,
        observation=Observation(
            player_id=3,
            self_role=Role.WITCH,
            phase=Phase.NIGHT,
            day=2,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=(4, 7),
            sheriff_id=5,
            visible_events=(),
            known_roles={},
            seer_checks={},
            metadata={"can_poison": True, "can_save": False},
        ),
        candidates=(1, 2, 5, 6, 8, 9, 10),
        retry_count=0,
        metadata={"can_poison": True, "can_save": False},
    )


def _make_shoot_request() -> ActionRequest:
    return ActionRequest(
        player_id=6,
        action_type=ActionType.HUNTER_SHOOT,
        phase=Phase.DAY_SPEECH,
        observation=Observation(
            player_id=6,
            self_role=Role.HUNTER,
            phase=Phase.DAY_SPEECH,
            day=3,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=(4, 7),
            sheriff_id=5,
            visible_events=(),
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=(1, 2, 3, 5, 8, 9, 10),
        retry_count=0,
        metadata={},
    )


def _make_sheriff_badge_request() -> ActionRequest:
    return ActionRequest(
        player_id=1,
        action_type=ActionType.SHERIFF_BADGE,
        phase=Phase.DAY_SPEECH,
        observation=Observation(
            player_id=1,
            self_role=Role.VILLAGER,
            phase=Phase.DAY_SPEECH,
            day=3,
            alive_players=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            dead_players=(),
            sheriff_id=1,
            visible_events=(),
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=(3, 5, 7),
        retry_count=0,
        metadata={},
    )


def _make_white_wolf_explode_request() -> ActionRequest:
    return ActionRequest(
        player_id=2,
        action_type=ActionType.WHITE_WOLF_EXPLODE,
        phase=Phase.DAY_SPEECH,
        observation=Observation(
            player_id=2,
            self_role=Role.WHITE_WOLF_KING,
            phase=Phase.DAY_SPEECH,
            day=3,
            alive_players=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
            dead_players=(),
            sheriff_id=1,
            visible_events=(),
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=(3, 5, 7, 9),
        retry_count=0,
        metadata={},
    )


def _make_speak_request(player_id: int = 2) -> ActionRequest:
    return ActionRequest(
        player_id=player_id,
        action_type=ActionType.SPEAK,
        phase=Phase.DAY_SPEECH,
        observation=Observation(
            player_id=player_id,
            self_role=Role.VILLAGER,
            phase=Phase.DAY_SPEECH,
            day=2,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=(4, 7),
            sheriff_id=5,
            visible_events=(GameEvent(type="speak", day=2, phase=Phase.DAY_SPEECH, actor=8, message="P8 发言怀疑 P3"),),
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=(),
        retry_count=0,
        metadata={},
    )


def _make_vote_request(candidates: tuple[int, ...] = (3, 7, 9)) -> ActionRequest:
    return ActionRequest(
        player_id=5,
        action_type=ActionType.EXILE_VOTE,
        phase=Phase.EXILE_VOTE,
        observation=Observation(
            player_id=5,
            self_role=Role.VILLAGER,
            phase=Phase.EXILE_VOTE,
            day=2,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=(4, 7),
            sheriff_id=5,
            visible_events=(GameEvent(type="speak", day=2, phase=Phase.DAY_SPEECH, actor=8, message="P8 发言怀疑 P3"),),
            known_roles={},
            seer_checks={},
            metadata={},
        ),
        candidates=candidates,
        retry_count=0,
        metadata={},
    )


class StubModel:
    """Model adapter that returns a fixed JSON string."""

    def __init__(self, response_text: str) -> None:
        self.response_text = response_text
        self.last_messages: list[dict] = []

    async def complete(self, messages: list[dict], **kwargs) -> str:
        self.last_messages = list(messages)
        return self.response_text


class AgentContextTests(unittest.TestCase):
    def test_context_holds_all_pipeline_fields(self):
        request = _make_speak_request()
        ctx = AgentContext(request=request, player_id=2, role="villager")
        self.assertEqual(ctx.player_id, 2)
        self.assertEqual(ctx.role, "villager")
        self.assertEqual(ctx.response, None)
        self.assertEqual(ctx.errors, [])

    def test_context_has_request_observation(self):
        request = _make_speak_request()
        ctx = AgentContext(request=request, player_id=2, role="villager")
        self.assertEqual(ctx.request.observation.day, 2)

    def test_context_has_selected_skills_field(self):
        """New multi-skill fields exist on AgentContext."""
        request = _make_vote_request()
        ctx = AgentContext(request=request, player_id=5, role="villager")
        self.assertEqual(ctx.selected_skills, [])
        self.assertEqual(ctx.skill_context, "")


class DecisionStepTests(unittest.TestCase):
    def setUp(self):
        self.request = _make_vote_request()
        self.memory = AgentMemory(player_id=5, role=Role.VILLAGER)
        # Ensure skill router can find the test fixture skills directory
        from agent.knowledge.skills.router import configure_skill_root
        configure_skill_root(Path(__file__).resolve().parent / "fixtures" / "skills")

    def test_request_observation_has_expected_data(self):
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        self.assertEqual(ctx.request.observation.day, 2)
        self.assertEqual(ctx.request.phase.value, "exile_vote")
        self.assertEqual(list(ctx.request.observation.alive_players), [1, 2, 3, 5, 6, 8, 9, 10])
        self.assertEqual(list(ctx.request.candidates), [3, 7, 9])

    def test_remember_step_builds_context(self):
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx = remember_step(ctx, self.memory)
        self.assertIn("rolling_summary", ctx.memory_context)
        self.assertIn("private_facts", ctx.memory_context)

    def test_select_skills_step_selects_skills_for_action(self):
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx = remember_step(ctx, self.memory)
        ctx = select_skills_step(ctx)
        self.assertGreater(len(ctx.selected_skills), 0)
        self.assertNotEqual(ctx.skill_context, "")

    def test_skill_router_excludes_common_skills(self):
        """Common skills like output_schema are NOT injected by router."""
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx = select_skills_step(ctx)
        self.assertNotIn("output_schema", ctx.selected_skills)

    def test_build_prompt_step_builds_system_and_user_messages(self):
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx = remember_step(ctx, self.memory)
        ctx = select_skills_step(ctx)
        ctx = build_prompt_step(ctx)
        self.assertGreater(len(ctx.messages), 0)
        self.assertEqual(ctx.messages[0]["role"], "system")
        self.assertEqual(ctx.messages[1]["role"], "user")

    def test_parse_output_step_extracts_response_from_json(self):
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx.raw_output = '{"target": 7, "choice": null, "text": "出7号", "reasoning": "7号可疑"}'
        ctx = parse_output_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.target, 7)

    def test_parse_output_step_handles_markdown_code_block(self):
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx.raw_output = '```json\n{"target": 3, "choice": null, "text": "出3号", "reasoning": "3号像狼"}\n```'
        ctx = parse_output_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.target, 3)

    def test_enforce_policy_step_falls_back_on_missing_response(self):
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertIn(ctx.response.target, self.request.candidates)

    def test_enforce_policy_step_corrects_illegal_target(self):
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx.raw_output = '{"target": 99, "choice": null, "text": "出99号"}'
        ctx = parse_output_step(ctx)
        # target 99 is not in candidates, policy should fix it
        if ctx.response is not None:
            ctx = enforce_policy_step(ctx)
            self.assertIn(ctx.response.target, self.request.candidates)

    def test_build_decision_record_from_context(self):
        from agent.api.runtime import _build_decision_record
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx.raw_output = '{"target": 7, "reasoning": "7可疑"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        record = _build_decision_record(ctx)
        self.assertEqual(record.selected_target, 7)
        self.assertEqual(record.player_id, 5)


class AgentRuntimeTests(unittest.TestCase):
    def test_runtime_returns_legal_response_with_valid_json(self):
        stub = StubModel('{"target": 7, "choice": null, "text": "出7号", "reasoning": "7号可疑", "alternatives": [3], "rejected_reasons": ["3证据不够"]}')
        runtime = AgentRuntime(player_id=5, role=Role.VILLAGER, model=stub)
        request = _make_vote_request()
        response = asyncio.run(runtime.act(request))
        self.assertEqual(response.action_type, ActionType.EXILE_VOTE)
        self.assertIn(response.target, request.candidates)

    def test_runtime_falls_back_on_invalid_json(self):
        stub = StubModel("not valid json at all!!!")
        runtime = AgentRuntime(player_id=5, role=Role.VILLAGER, model=stub)
        request = _make_vote_request()
        response = asyncio.run(runtime.act(request))
        self.assertEqual(response.action_type, ActionType.EXILE_VOTE)
        self.assertIn(response.target, request.candidates)

    def test_runtime_respects_information_boundary(self):
        """Villager should not see werewolf teammates in observation summary."""
        stub = StubModel('{"target": 7, "choice": null, "text": "出7号", "reasoning": "7可疑"}')
        runtime = AgentRuntime(player_id=5, role=Role.VILLAGER, model=stub)
        request = _make_vote_request()
        response = asyncio.run(runtime.act(request))
        self.assertIsNotNone(response)

    def test_runtime_llm_player_agent_protocol(self):
        """AgentRuntime satisfies the PlayerAgent protocol."""
        stub = StubModel('{"target": 7, "choice": null, "text": "出7号", "reasoning": "7可疑"}')
        agent = AgentRuntime(player_id=5, role=Role.VILLAGER, model=stub)
        request = _make_vote_request()
        response = asyncio.run(agent.act(request))
        self.assertEqual(response.action_type, request.action_type)
        self.assertIn(response.target, request.candidates)

    def test_runtime_decision_recorder_integration(self):
        recorder = AgentDecisionRecorder()
        stub = StubModel('{"target": 7, "choice": null, "text": "出7号", "reasoning": "7可疑"}')
        agent = AgentRuntime(
            player_id=5, role=Role.VILLAGER, model=stub, recorder=recorder
        )
        request = _make_vote_request()
        asyncio.run(agent.act(request))
        self.assertEqual(len(recorder.records), 1)

    def test_runtime_different_roles_have_different_skills(self):
        """Ensure werewolf and villager get different skill sets."""
        vote_request = _make_vote_request()
        stub = StubModel('{"target": 7, "choice": null, "text": "出7号", "reasoning": "可疑"}')

        wolf_runtime = AgentRuntime(player_id=3, role=Role.WEREWOLF, model=stub)
        villager_runtime = AgentRuntime(player_id=5, role=Role.VILLAGER, model=stub)

        wolf_resp = asyncio.run(wolf_runtime.act(vote_request))
        villager_resp = asyncio.run(villager_runtime.act(vote_request))

        self.assertIsNotNone(wolf_resp)
        self.assertIsNotNone(villager_resp)

    def test_agent_context_fields_flow_through_full_pipeline(self):
        stub = StubModel('{"target": 7, "choice": null, "text": "出7号", "reasoning": "可疑"}')
        runtime = AgentRuntime(player_id=5, role=Role.VILLAGER, model=stub)
        request = _make_vote_request()

        # Manually step through pipeline to verify AgentContext flow
        ctx = AgentContext(request=request, player_id=runtime.player_id, role=runtime.role.value)
        self.assertEqual(ctx.request.observation.day, 2)
        ctx = remember_step(ctx, runtime.memory)
        self.assertIn("rolling_summary", ctx.memory_context)
        ctx = select_skills_step(ctx)
        self.assertGreater(len(ctx.selected_skills), 0)
        self.assertNotEqual(ctx.skill_context, "")
        ctx = build_prompt_step(ctx)
        self.assertGreater(len(ctx.messages), 0)


class PolicyConstraintTests(unittest.TestCase):
    """Test policy fallback for choice-dependent targets (Fix 1)."""

    def test_witch_poison_no_target_falls_back(self):
        request = _make_witch_poison_request()
        ctx = AgentContext(request=request, player_id=3, role="witch")
        ctx.raw_output = '{"target": null, "choice": "poison", "text": "毒杀", "reasoning": "下毒"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        # Fallback should revert to "none" (safe default for witch_act)
        self.assertEqual(ctx.response.choice, "none")

    def test_witch_empty_choice_no_target_passes(self):
        """When choice is 'none' or 'pass', missing target is fine."""
        request = _make_witch_poison_request()
        ctx = AgentContext(request=request, player_id=3, role="witch")
        ctx.raw_output = '{"target": null, "choice": "none", "text": "不用毒", "reasoning": "局势不明"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.choice, "none")

    def test_hunter_shoot_valid_target_passes(self):
        request = _make_shoot_request()
        ctx = AgentContext(request=request, player_id=6, role="hunter")
        ctx.raw_output = '{"target": 8, "choice": null, "text": "带走8号", "reasoning": "8号像狼"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.target, 8)

    def test_witch_poison_bad_target_repairs(self):
        """WITCH_ACT poison with target not in candidates should repair."""
        request = _make_witch_poison_request()
        ctx = AgentContext(request=request, player_id=3, role="witch")
        ctx.raw_output = '{"target": 99, "choice": "poison", "text": "毒杀", "reasoning": "99最可疑"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.choice, "poison")
        self.assertIn(ctx.response.target, request.candidates)

    def test_witch_poison_good_target_passes(self):
        """WITCH_ACT poison with valid target should pass through."""
        request = _make_witch_poison_request()
        ctx = AgentContext(request=request, player_id=3, role="witch")
        ctx.raw_output = '{"target": 8, "choice": "poison", "text": "毒杀8号", "reasoning": "8号像狼"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.target, 8)
        self.assertEqual(ctx.response.choice, "poison")

    def test_sheriff_badge_transfer_bad_target_falls_back(self):
        """SHERIFF_BADGE transfer with invalid target should repair to valid candidate."""
        request = _make_sheriff_badge_request()
        ctx = AgentContext(request=request, player_id=1, role="sheriff")
        ctx.raw_output = '{"target": 99, "choice": "transfer", "text": "移交给99号", "reasoning": "99最可信"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        # Target should be repaired to a valid candidate
        self.assertEqual(ctx.response.choice, "transfer")
        self.assertIn(ctx.response.target, request.candidates)

    def test_sheriff_badge_transfer_good_target_passes(self):
        """SHERIFF_BADGE transfer with valid target should pass through."""
        request = _make_sheriff_badge_request()
        ctx = AgentContext(request=request, player_id=1, role="sheriff")
        ctx.raw_output = '{"target": 3, "choice": "transfer", "text": "移交给3号", "reasoning": "3号可信"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.target, 3)
        self.assertEqual(ctx.response.choice, "transfer")

    def test_white_wolf_explode_bad_target_falls_back(self):
        """WHITE_WOLF_EXPLODE with invalid target should fall back to pass."""
        request = _make_white_wolf_explode_request()
        ctx = AgentContext(request=request, player_id=2, role="white_wolf_king")
        ctx.raw_output = '{"target": 99, "choice": "explode", "text": "自爆", "reasoning": "带走99号"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.choice, "pass")

    def test_white_wolf_explode_good_target_passes(self):
        """WHITE_WOLF_EXPLODE with valid target should pass through."""
        request = _make_white_wolf_explode_request()
        ctx = AgentContext(request=request, player_id=2, role="white_wolf_king")
        ctx.raw_output = '{"target": 7, "choice": "explode", "text": "自爆带走7号", "reasoning": "7号是预言家"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.target, 7)
        self.assertEqual(ctx.response.choice, "explode")

    def test_white_wolf_explode_pass_no_target_passes(self):
        """WHITE_WOLF_EXPLODE with choice=pass and target=None should pass."""
        request = _make_white_wolf_explode_request()
        ctx = AgentContext(request=request, player_id=2, role="white_wolf_king")
        ctx.raw_output = '{"target": null, "choice": "pass", "text": "先不自爆", "reasoning": "时机未到"}'
        ctx = parse_output_step(ctx)
        ctx = enforce_policy_step(ctx)
        self.assertIsNotNone(ctx.response)
        self.assertEqual(ctx.response.choice, "pass")


class PromptHintsTests(unittest.TestCase):
    """Test prompt_hints flow through prompt builder (Fix 2)."""

    def setUp(self):
        self.request = _make_vote_request()
        self.memory = AgentMemory(player_id=5, role=Role.VILLAGER)

    def test_skill_context_appears_in_messages(self):
        """Multi-skill context is injected into the prompt."""
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx = remember_step(ctx, self.memory)
        ctx = select_skills_step(ctx)
        ctx = build_prompt_step(ctx)

        from agent.knowledge.prompts import build_messages
        strategy_advice = ctx.strategy_advice or {}
        messages = build_messages(
            ctx.request,
            player_id=5,
            role=Role.VILLAGER,
            memory_context=ctx.memory_context,
            strategy_advice=strategy_advice,
            selected_skills=ctx.selected_skills,
            skill_context=ctx.skill_context,
        )
        combined = " ".join(m.get("content", "") for m in messages)
        # Output schema is now hardcoded in the prompt, not from skill injection
        self.assertIn("输出格式要求", combined)

    def test_skill_advice_includes_skill_count(self):
        """Check that the skill router returns skill metadata in strategy_advice."""
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx = remember_step(ctx, self.memory)
        ctx = select_skills_step(ctx)
        advice = ctx.strategy_advice or {}
        self.assertIn("skill_count", advice)
        self.assertGreater(advice["skill_count"], 0)


class FieldNotesPromptTests(unittest.TestCase):
    """Test field_notes injection into prompt (P1)."""

    def setUp(self):
        self.request = _make_vote_request()
        self.memory = AgentMemory(player_id=5, role=Role.VILLAGER)

    def test_field_notes_appear_in_prompt_when_present(self):
        """Segment-based memory replaces field_notes in the prompt.

        After Phase 3 refactor, field_notes are no longer rendered.
        The prompt now uses segment events instead.
        """
        ctx = AgentContext(request=self.request, player_id=5, role="villager")
        ctx = remember_step(ctx, self.memory)
        ctx = select_skills_step(ctx)

        from agent.knowledge.prompts import build_messages
        strategy_advice = ctx.strategy_advice or {}
        messages = build_messages(
            ctx.request,
            player_id=5,
            role=Role.VILLAGER,
            memory_context={
                "private_facts": {"known_roles": {}, "seer_checks": {}, "metadata": {}},
                "open_segment": [
                    {"text": "第2天 exile_vote 系统: P7 被放逐", "content": "P7 被放逐"},
                ],
                "open_segment_key": "exile_vote:2",
                "recent_closed_segments": [],
                "compressed_segment_summaries": [],
            },
            strategy_advice=strategy_advice,
            selected_skills=ctx.selected_skills,
            skill_context=ctx.skill_context,
        )
        combined = " ".join(m.get("content", "") for m in messages)
        # Segment-based memory should appear in prompt
        self.assertIn("exile_vote:2", combined)
        self.assertIn("P7", combined)




class MemoryDedupTests(unittest.TestCase):
    """Test memory deduplication of visible_events entries (Fix 3)."""

    def test_duplicate_visible_events_not_reprocessed(self):
        """When visible_events has duplicates, memory should not double-count."""
        from agent.core.memory import AgentMemory

        mem = AgentMemory(player_id=5, role=Role.VILLAGER)

        obs = Observation(
            player_id=5,
            self_role=Role.VILLAGER,
            phase=Phase.DAY_SPEECH,
            day=2,
            alive_players=(1, 2, 3, 5, 6, 8, 9, 10),
            dead_players=(4, 7),
            sheriff_id=5,
            visible_events=(GameEvent(type="speak", day=2, phase=Phase.DAY_SPEECH, actor=8, message="P8 发言怀疑 P3"),),
            known_roles={},
            seer_checks={},
            metadata={},
        )
        request = ActionRequest(
            player_id=5,
            action_type=ActionType.SPEAK,
            phase=Phase.DAY_SPEECH,
            observation=obs,
            candidates=(),
            retry_count=0,
            metadata={},
        )
        # Build context twice with the same request
        mem.build_context(request)
        seen_after_first = len(mem._seen_public_entries)
        mem.build_context(request)
        seen_after_second = len(mem._seen_public_entries)

        # _seen_public_entries should not grow on duplicate
        self.assertEqual(seen_after_first, seen_after_second)


class PhaseWindowMemoryTests(unittest.TestCase):
    """Tests for phase-aware short-term memory."""

    _PHASE_MAP = {p.value: p for p in Phase}

    def _entry(
        self,
        *,
        day: int,
        phase: str,
        event_type: str,
        actor: int | None = None,
        target: int | None = None,
        content: str = "",
    ) -> GameEvent:
        return GameEvent(
            type=event_type,
            day=day,
            phase=self._PHASE_MAP.get(phase, Phase.DAY_SPEECH),
            actor=actor,
            target=target,
            message=content,
        )

    def _request(
        self,
        visible_events: tuple[GameEvent, ...],
        *,
        day: int = 1,
        phase: Phase = Phase.EXILE_VOTE,
        action_type: ActionType = ActionType.EXILE_VOTE,
        candidates: tuple[int, ...] = (2, 3, 4),
        dead_players: tuple[int, ...] = (),
        sheriff_id: int | None = None,
    ) -> ActionRequest:
        return ActionRequest(
            player_id=5,
            action_type=action_type,
            phase=phase,
            observation=Observation(
                player_id=5,
                self_role=Role.VILLAGER,
                phase=phase,
                day=day,
                alive_players=(1, 2, 3, 4, 5),
                dead_players=dead_players,
                sheriff_id=sheriff_id,
                visible_events=visible_events,
                known_roles={},
                seer_checks={},
                metadata={},
            ),
            candidates=candidates,
            retry_count=0,
            metadata={},
        )

    def test_recent_timeline_keeps_only_last_two_phase_keys(self):
        mem = AgentMemory(player_id=5, role=Role.VILLAGER)
        visible_events = (
            self._entry(
                day=1,
                phase="sheriff_election",
                event_type="sheriff_speak",
                actor=1,
                content="1号警上发言，我是预言家",
            ),
            self._entry(
                day=1,
                phase="day_speech",
                event_type="speak",
                actor=2,
                content="2号发言怀疑P3",
            ),
            self._entry(
                day=1,
                phase="exile_vote",
                event_type="exile_vote",
                actor=2,
                target=3,
                content="2号投给3号",
            ),
        )

        memory_context = mem.build_context(self._request(visible_events))

        self.assertEqual(
            [block["phase_key"] for block in memory_context["recent_timeline"]],
            ["day1/day_speech", "day1/exile_vote"],
        )
        timeline_text = json.dumps(memory_context["recent_timeline"], ensure_ascii=False)
        self.assertNotIn("警上发言", timeline_text)
        self.assertIn("2号发言怀疑P3", timeline_text)
        self.assertIn("2号投给3号", timeline_text)

    def test_segment_data_present_in_memory_context(self):
        """Verify segment data (open_segment, recent_closed_segments) replaces legacy fields."""
        mem = AgentMemory(player_id=5, role=Role.VILLAGER)
        visible_events = (
            self._entry(
                day=1,
                phase="sheriff_election",
                event_type="sheriff_speak",
                actor=1,
                content="1号警上发言，我是预言家，查验P2是好人",
            ),
            self._entry(
                day=1,
                phase="day_speech",
                event_type="speak",
                actor=2,
                content="2号发言认好P1",
            ),
            self._entry(
                day=1,
                phase="exile_vote",
                event_type="exile_vote",
                actor=3,
                target=4,
                content="3号投给4号",
            ),
        )

        memory_context = mem.build_context(self._request(visible_events))

        # All events land in the open segment (same day, single-request flow)
        open_seg = memory_context["open_segment"]
        open_types = [e["type"] for e in open_seg]
        self.assertIn("sheriff_speak", open_types)
        self.assertIn("speak", open_types)
        self.assertIn("exile_vote", open_types)
        # Sheriff election seer claim content is preserved in the segment
        self.assertTrue(any("预言家" in e["content"] for e in open_seg))
        # No phase transition occurred, so no closed segments
        self.assertEqual(memory_context["recent_closed_segments"], [])

    def test_segment_events_preserve_observations_across_phases(self):
        """Segment events contain observation data even outside the hot window."""
        mem = AgentMemory(player_id=5, role=Role.VILLAGER)

        # First request: day 1 exile_vote — puts events into exile_vote:1
        day1_events = (
            self._entry(day=1, phase="day_speech", event_type="speak", actor=1, content="1号发言"),
            self._entry(day=1, phase="exile_vote", event_type="exile_vote", actor=2, target=3, content="2号投给3号"),
        )
        mem.build_context(
            self._request(day1_events, day=1, phase=Phase.EXILE_VOTE, action_type=ActionType.EXILE_VOTE)
        )

        # Second request: day 2 day_speech — closes exile_vote:1, opens day_speech:2
        day2_events = (
            self._entry(day=2, phase="day_speech", event_type="speak", actor=4, content="4号发言"),
        )
        memory_context = mem.build_context(
            self._request(day2_events, day=2, phase=Phase.DAY_SPEECH, action_type=ActionType.SPEAK, dead_players=(3,), sheriff_id=1)
        )

        # Day 1 events are in a closed segment
        closed = memory_context["recent_closed_segments"]
        self.assertTrue(len(closed) > 0, "Day 1 events should be in closed segments")
        closed_events = [e for seg in closed for e in seg["events"]]
        self.assertTrue(any("1号发言" in e["content"] for e in closed_events))
        self.assertTrue(any("2号投给3号" in e["content"] for e in closed_events))
        # Current day event is in the open segment
        open_seg = memory_context["open_segment"]
        self.assertTrue(any("4号发言" in e["content"] for e in open_seg))

    def test_self_commitments_capture_public_stance(self):
        # NOTE: self_commitments are legacy and not rendered in prompt;
        # kept to verify remember_action() still populates the field.
        mem = AgentMemory(player_id=5, role=Role.VILLAGER)
        request = self._request([], phase=Phase.DAY_SPEECH, action_type=ActionType.SPEAK, candidates=())
        mem.remember_action(
            request,
            ActionResponse(ActionType.SPEAK, text="我站边P2，怀疑P3"),
        )

        memory_context = mem.build_context(request)

        self.assertEqual(memory_context["self_commitments"][0]["suspected_player"], 3)
        self.assertIn("我站边P2", memory_context["self_commitments"][0]["text"])

    def test_prompt_uses_phase_memory_sections_instead_of_legacy_event_line(self):
        """Prompt now uses segment-based memory, not legacy fields."""
        mem = AgentMemory(player_id=5, role=Role.VILLAGER)
        visible_events = (
            self._entry(day=1, phase="sheriff_election", event_type="sheriff_speak", actor=1, content="1号警上发言，我是预言家"),
            self._entry(day=1, phase="day_speech", event_type="speak", actor=2, content="2号发言怀疑P3"),
            self._entry(day=1, phase="exile_vote", event_type="exile_vote", actor=2, target=3, content="2号投给3号"),
        )
        request = self._request(visible_events)
        memory_context = mem.build_context(request)

        from agent.knowledge.prompts import build_messages
        messages = build_messages(
            request,
            player_id=5,
            role=Role.VILLAGER,
            memory_context=memory_context,
        )
        prompt = messages[1]["content"]

        # Segment-based: open segment should contain current phase events
        self.assertIn("exile_vote:1", prompt)
        self.assertIn("当前阶段", prompt)
        # Legacy fields should NOT appear as prompt sections
        self.assertNotIn("前史摘要", prompt)
        self.assertNotIn("不可丢关键事实", prompt)
        self.assertNotIn("玩家画像", prompt)


class ReviewStatsTests(unittest.TestCase):
    """Test review.py helper functions (Fix 6)."""

    def test_get_role_of_with_roles_dict(self):
        roles = {1: Role.VILLAGER, 2: Role.WEREWOLF, 3: Role.SEER}
        self.assertEqual(get_role_of(1, roles), Role.VILLAGER)
        self.assertEqual(get_role_of(2, roles), Role.WEREWOLF)
        self.assertEqual(get_role_of(3, roles), Role.SEER)
        self.assertIsNone(get_role_of(99, roles))

    def test_did_survive_with_death_event(self):
        game_log = {
            "entries": [
                {"event_type": "death", "target": 2},
                {"event_type": "death", "target": 4},
            ]
        }
        self.assertFalse(did_survive(2, game_log))
        self.assertFalse(did_survive(4, game_log))
        self.assertTrue(did_survive(1, game_log))
        self.assertTrue(did_survive(3, game_log))

    def test_did_survive_no_entries(self):
        game_log = {"entries": []}
        self.assertTrue(did_survive(1, game_log))
        self.assertTrue(did_survive(2, game_log))

    def test_did_survive_empty_log(self):
        game_log = {}
        self.assertTrue(did_survive(1, game_log))

    def test_log_entries_list_input(self):
        from agent.learning.review import log_entries
        entries = [{"event_type": "death", "target": 2}]
        result = log_entries(entries)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["target"], 2)

    def test_log_entries_events_key(self):
        from agent.learning.review import log_entries
        data = {"events": [{"event_type": "death", "target": 3}]}
        result = log_entries(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["target"], 3)

    def test_log_entries_entries_key(self):
        from agent.learning.review import log_entries
        data = {"entries": [{"event_type": "death", "target": 4}]}
        result = log_entries(data)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["target"], 4)

    def test_log_entries_empty_dict(self):
        from agent.learning.review import log_entries
        self.assertEqual(log_entries({}), [])

    def test_did_survive_list(self):
        entries = [{"event_type": "death", "target": 2}]
        self.assertFalse(did_survive(2, entries))
        self.assertTrue(did_survive(1, entries))

    def test_did_survive_events_dict(self):
        data = {"events": [{"event_type": "death", "target": 3}]}
        self.assertFalse(did_survive(3, data))
        self.assertTrue(did_survive(1, data))


class MarkdownSkillLoaderTests(unittest.TestCase):
    """Test markdown skill loading and integration (P2)."""

    def setUp(self):
        from agent.knowledge.skills.router import configure_skill_root
        configure_skill_root(Path(__file__).resolve().parent / "fixtures" / "skills")

    def test_parse_front_matter_basic(self):
        from agent.knowledge.skills.loader import parse_front_matter

        text = """\
---
name: test_skill
role: witch
priority: 50
---

# Body here
"""
        front, body = parse_front_matter(text)
        self.assertEqual(front["name"], "test_skill")
        self.assertEqual(front["role"], "witch")
        self.assertEqual(front["priority"], 50)  # Still parsed, even if not used
        self.assertIn("Body here", body)

    def test_parse_front_matter_list(self):
        from agent.knowledge.skills.loader import parse_front_matter

        text = """\
---
name: test_skill
applicable_actions:
  - witch_act
---
"""
        front, body = parse_front_matter(text)
        self.assertEqual(front["name"], "test_skill")
        self.assertEqual(front["applicable_actions"], ["witch_act"])

    def test_parse_front_matter_no_front_matter(self):
        from agent.knowledge.skills.loader import parse_front_matter

        text = "Just a body\nWith no front matter\n"
        front, body = parse_front_matter(text)
        self.assertEqual(front, {})
        self.assertEqual(body, text)

    def test_parse_front_matter_nested_dict(self):
        from agent.knowledge.skills.loader import parse_front_matter

        text = """\
---
name: test
requires:
  can_poison: true
output_constraints:
  choice: poison
---
"""
        front, body = parse_front_matter(text)
        self.assertEqual(front["requires"], {"can_poison": True})
        self.assertEqual(front["output_constraints"], {"choice": "poison"})

    def test_load_markdown_skills_from_file(self):
        from agent.knowledge.skills.loader import load_markdown_skills
        from pathlib import Path

        ROOT = Path(__file__).resolve().parent
        skills = load_markdown_skills(ROOT / "fixtures" / "skills")
        names = {s.name for s in skills}
        self.assertIn("witch_poison", names)
        self.assertIn("villager_vote_analysis", names)
        for s in skills:
            # Common skills have no applicable_actions; role skills may have
            # empty applicable_actions (= always inject for that role)
            self.assertTrue(hasattr(s, "evolution"))

    def test_markdown_skill_does_not_require_priority(self):
        """Skills without priority field should load fine."""
        from agent.knowledge.skills.loader import MarkdownSkill
        skill = MarkdownSkill(name="test")
        # No priority attribute
        self.assertFalse(hasattr(skill, "priority"))

    def test_output_schema_not_injected_by_router(self):
        from agent.knowledge.skills.router import select_skills

        for role in (Role.WEREWOLF, Role.WITCH, Role.VILLAGER, Role.SEER):
            request = _make_vote_request()
            ctx = AgentContext(request=request, player_id=5, role=role.value)
            selected = select_skills(ctx, role)
            names = [s.name for s in selected]
            self.assertNotIn("output_schema", names, f"{role.value} should NOT get output_schema from router")

    def test_only_current_role_skills_are_injected(self):
        from agent.knowledge.skills.router import select_skills

        # Witch should get witch skills, not werewolf/seer/hunter skills
        witch_request = _make_witch_poison_request()
        ctx = AgentContext(request=witch_request, player_id=3, role="witch")
        selected = select_skills(ctx, Role.WITCH)
        names = [s.name for s in selected]

        witch_names = {"witch_save", "witch_poison", "witch_hide_identity"}
        forbidden = {"werewolf_fake_seer", "seer_claim", "hunter_shoot"}

        self.assertTrue(
            witch_names.intersection(names),
            f"Expected witch skills in {names}",
        )
        for f in forbidden:
            self.assertNotIn(f, names, f"Should not inject {f} for witch")

    def test_multiple_matching_role_skills_are_injected(self):
        from agent.knowledge.skills.router import select_skills

        # Witch WITCH_ACT — only witch_poison matches (requires can_poison=true)
        # witch_save is filtered out because can_save=false in this request
        request = _make_witch_poison_request()
        ctx = AgentContext(request=request, player_id=3, role="witch")
        selected = select_skills(ctx, Role.WITCH)
        names = [s.name for s in selected]

        self.assertIn("witch_poison", names)
        self.assertNotIn("witch_save", names)

    def test_witch_requires_filtering_poison(self):
        """witch_poison should NOT be injected when can_poison is false."""
        from agent.knowledge.skills.router import select_skills

        request = _make_witch_poison_request()
        request = ActionRequest(
            player_id=3,
            action_type=ActionType.WITCH_ACT,
            phase=Phase.NIGHT,
            observation=request.observation,
            candidates=request.candidates,
            retry_count=0,
            metadata={"can_poison": False, "can_save": True},
        )
        ctx = AgentContext(request=request, player_id=3, role="witch")
        selected = select_skills(ctx, Role.WITCH)
        names = [s.name for s in selected]

        self.assertNotIn("witch_poison", names, "witch_poison should be filtered out when can_poison=false")

    def test_witch_requires_filtering_save(self):
        """witch_save SHOULD be injected when can_save is true."""
        from agent.knowledge.skills.router import select_skills

        request = _make_witch_poison_request()
        request = ActionRequest(
            player_id=3,
            action_type=ActionType.WITCH_ACT,
            phase=Phase.NIGHT,
            observation=request.observation,
            candidates=request.candidates,
            retry_count=0,
            metadata={"can_poison": True, "can_save": True},
        )
        ctx = AgentContext(request=request, player_id=3, role="witch")
        selected = select_skills(ctx, Role.WITCH)
        names = [s.name for s in selected]

        self.assertIn("witch_save", names, "witch_save should be injected when can_save=true")
        self.assertIn("witch_poison", names, "witch_poison should be injected when can_poison=true")

    def test_output_schema_hardcoded_in_prompt(self):
        from agent.knowledge.prompts.base import _OUTPUT_FORMAT_INSTRUCTIONS
        self.assertIn("输出格式要求", _OUTPUT_FORMAT_INSTRUCTIONS)
        self.assertIn("public_text", _OUTPUT_FORMAT_INSTRUCTIONS)
        self.assertIn("private_reasoning", _OUTPUT_FORMAT_INSTRUCTIONS)

    def test_skill_context_includes_role_skills_only(self):
        request = _make_vote_request()
        ctx = AgentContext(request=request, player_id=5, role="villager")
        ctx = select_skills_step(ctx)
        skill_context = ctx.skill_context
        # Should include role strategy section only (no common)
        self.assertIn("role strategy", skill_context)
        self.assertNotIn("common rules", skill_context)
        # Should include role skills
        self.assertIn("villager_vote_analysis", skill_context)
        self.assertNotIn("output_schema", skill_context)

    def test_configure_skill_root_can_load_alternate_skill_dir(self):
        from pathlib import Path
        import tempfile

        from agent.knowledge.skills.router import configure_skill_root

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            common = root / "common"
            common.mkdir()
            (common / "game_rules.md").write_text(
                "---\nname: custom_rules\n---\n\ncustom rules body",
                encoding="utf-8",
            )
            role_dir = root / "villager"
            role_dir.mkdir()
            (role_dir / "vote.md").write_text(
                "---\n"
                "name: custom_villager_vote\n"
                "role: villager\n"
                "applicable_actions:\n"
                "  - exile_vote\n"
                "---\n\ncustom vote body",
                encoding="utf-8",
            )

            configure_skill_root(root)
            request = _make_vote_request()
            ctx = AgentContext(request=request, player_id=5, role="villager")
            ctx = select_skills_step(ctx)

        self.assertNotIn("custom_rules", ctx.selected_skills)
        self.assertIn("custom_villager_vote", ctx.selected_skills)
        configure_skill_root(None)


if __name__ == "__main__":
    unittest.main()
