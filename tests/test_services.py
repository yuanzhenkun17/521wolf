"""Tests for app/services/ — all 5 modules.

These verify that every service module imports cleanly, has the expected
public API, and where possible, core logic works correctly without LLM calls.
"""

import pytest


# ===========================================================================
# app/services/llm.py — create_llm, load_llm_client
# ===========================================================================

class TestServicesLLM:
    def test_create_llm_returns_chat_openai(self, monkeypatch):
        monkeypatch.setenv("WEREWOLF_LLM_API_KEY", "test-key")
        monkeypatch.setenv("WEREWOLF_LLM_BASE_URL", "https://test.example.com/v1")

        from app.services.llm import create_llm
        from langchain_openai import ChatOpenAI
        llm = create_llm(env_path=None, temperature=0.0, timeout=10.0, max_retries=1)
        assert isinstance(llm, ChatOpenAI)
        assert llm.temperature == 0.0

    def test_create_llm_uses_central_config_and_overrides(self, monkeypatch):
        monkeypatch.setenv("WEREWOLF_LLM_API_KEY", "test-key")
        monkeypatch.setenv("WEREWOLF_LLM_BASE_URL", "https://config.example/v1")
        monkeypatch.setenv("WEREWOLF_LLM_MODEL", "configured-model")
        monkeypatch.setenv("WEREWOLF_LLM_TEMPERATURE", "0.7")
        monkeypatch.setenv("WEREWOLF_LLM_TIMEOUT", "33")
        monkeypatch.setenv("WEREWOLF_LLM_MAX_RETRIES", "4")

        from app.services.llm import create_llm

        llm = create_llm(env_path=None, model="override-model", temperature=0.0)

        assert llm.model_name == "override-model"
        assert llm.temperature == 0.0
        assert llm.request_timeout == 33.0
        assert llm.max_retries == 4
        assert str(llm.openai_api_base).rstrip("/") == "https://config.example/v1"

    def test_create_llm_accepts_explicit_api_key_without_env(self, monkeypatch):
        monkeypatch.delenv("WEREWOLF_LLM_API_KEY", raising=False)
        monkeypatch.delenv("WEREWOLF_LLM_BASE_URL", raising=False)

        from app.services.llm import create_llm

        llm = create_llm(
            env_path=None,
            api_key="explicit-key",
            base_url="https://explicit.example/v1",
            model="explicit-model",
        )

        assert llm.model_name == "explicit-model"
        assert str(llm.openai_api_base).rstrip("/") == "https://explicit.example/v1"

    def test_load_llm_client_is_alias(self):
        from app.services.llm import create_llm, load_llm_client
        assert load_llm_client is create_llm

    def test_invoke_llm_with_policy_retries_transient_errors(self):
        import asyncio

        from app.services.llm import LLMRuntimePolicy, invoke_llm_with_policy, reset_llm_circuit

        class FlakyModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                if self.calls == 1:
                    raise TimeoutError("temporary timeout")
                return type("Result", (), {"content": "ok"})()

        async def _run():
            reset_llm_circuit()
            model = FlakyModel()
            result = await invoke_llm_with_policy(
                model,
                [{"role": "user", "content": "hello"}],
                stage="test_retry",
                circuit_key="test_retry",
                policy=LLMRuntimePolicy(
                    max_attempts=2,
                    timeout=None,
                    retry_initial_delay=0,
                    retry_max_delay=0,
                    circuit_failure_threshold=3,
                    circuit_cooldown=1,
                ),
            )
            assert result.content == "ok"
            assert model.calls == 2

        asyncio.run(_run())

    def test_invoke_llm_with_policy_does_not_retry_schema_errors(self):
        import asyncio

        import pytest

        from app.services.llm import LLMRuntimePolicy, invoke_llm_with_policy, reset_llm_circuit

        class BadSchemaModel:
            def __init__(self):
                self.calls = 0

            async def ainvoke(self, messages):
                self.calls += 1
                raise ValueError("schema failed")

        async def _run():
            reset_llm_circuit()
            model = BadSchemaModel()
            with pytest.raises(ValueError, match="schema failed"):
                await invoke_llm_with_policy(
                    model,
                    [],
                    stage="test_no_retry",
                    circuit_key="test_no_retry",
                    policy=LLMRuntimePolicy(max_attempts=3, timeout=None, retry_initial_delay=0),
                )
            assert model.calls == 1

        asyncio.run(_run())

    def test_invoke_llm_with_policy_timeout_and_circuit_breaker(self):
        import asyncio

        import pytest

        from app.services.llm import (
            LLMCircuitOpenError,
            LLMRuntimePolicy,
            invoke_llm_with_policy,
            reset_llm_circuit,
        )

        class SlowModel:
            async def ainvoke(self, messages):
                await asyncio.sleep(1)

        async def _run():
            reset_llm_circuit()
            policy = LLMRuntimePolicy(
                max_attempts=1,
                timeout=0.01,
                retry_initial_delay=0,
                circuit_failure_threshold=1,
                circuit_cooldown=5,
            )
            with pytest.raises(TimeoutError):
                await invoke_llm_with_policy(
                    SlowModel(),
                    [],
                    stage="test_timeout",
                    circuit_key="test_timeout",
                    policy=policy,
                )
            with pytest.raises(LLMCircuitOpenError):
                await invoke_llm_with_policy(
                    SlowModel(),
                    [],
                    stage="test_timeout",
                    circuit_key="test_timeout",
                    policy=policy,
                )

        asyncio.run(_run())


# ===========================================================================
# app/services/memory.py — AgentMemory, Segment, CompressedSegmentSummary
# ===========================================================================

class TestServicesMemory:
    @pytest.fixture
    def memory(self):
        from app.services.memory import AgentMemory
        from engine.models import Role
        return AgentMemory(player_id=1, role=Role.VILLAGER)

    def test_agent_memory_creation(self, memory):
        assert memory.player_id == 1
        assert memory.segments == []
        assert memory.compressed_segment_summaries == {}

    def test_normalize_phase_group(self):
        from app.services.memory import normalize_phase_group
        assert normalize_phase_group("night") == "night"
        assert normalize_phase_group("sheriff_elect") == "sheriff"
        assert normalize_phase_group("day_speech") == "day_speech"
        assert normalize_phase_group("exile_vote") == "exile_vote"
        assert normalize_phase_group("last_word") == "death_resolution"
        assert normalize_phase_group("unknown_phase") == "unknown_phase"

    def test_segment_event_to_prompt_text(self):
        from app.services.memory import SegmentEvent
        evt = SegmentEvent(day=1, phase="night", event_type="kill", actor=3, target=5, content="killed")
        text = evt.to_prompt_text()
        assert "第1天" in text
        assert "P3" in text
        assert "P5" in text
        assert "kill" in text

    def test_segment_event_private(self):
        from app.services.memory import SegmentEvent
        evt = SegmentEvent(day=1, phase="night", event_type="check", actor=2, target=4, content="seen", public=False)
        text = evt.to_prompt_text()
        assert "[私密]" in text

    def test_segment_creation_and_add(self):
        from app.services.memory import Segment, SegmentEvent
        seg = Segment(segment_key="night:1", day=1, phase_group="night")
        assert not seg.closed
        evt = SegmentEvent(day=1, phase="night", event_type="kill", actor=3, target=5, content="killed")
        seg.add_event(evt)
        assert len(seg.events) == 1
        seg.closed = True
        assert seg.closed

    def test_segment_to_prompt_dicts(self):
        from app.services.memory import Segment, SegmentEvent
        seg = Segment(segment_key="night:1", day=1, phase_group="night")
        evt = SegmentEvent(day=1, phase="night", event_type="kill", actor=3, target=5, content="killed")
        seg.add_event(evt)
        dicts = seg.to_prompt_dicts()
        assert len(dicts) == 1
        assert dicts[0]["type"] == "kill"
        assert "text" in dicts[0]

    def test_compressed_segment_summary(self):
        from app.services.memory import CompressedSegmentSummary
        css = CompressedSegmentSummary(
            segment_key="night:1",
            summary="test summary",
            key_events=["killed player 5"],
            player_notes={"3": "suspicious"},
            unknowns=["who is seer?"],
        )
        d = css.to_prompt_dict()
        assert d["segment_key"] == "night:1"
        assert d["summary"] == "test summary"

    def test_memory_remember_error(self, memory):
        memory.remember_error("test error")
        assert "test error" in memory.errors

    def test_memory_reset(self, memory):
        memory.remember_error("err")
        memory.reset()
        assert memory.errors == []
        assert memory.segments == []

    def test_create_wolf_memory(self):
        from app.services.memory import create_wolf_memory
        from engine.models import Role
        mem = create_wolf_memory(player_id=3, role=Role.SEER)
        assert mem.player_id == 3


# ===========================================================================
# app/services/tool.py — 17 LangChain @tools
# ===========================================================================

class TestServicesTool:

    def test_all_tools_count(self):
        from app.services.tool import ALL_TOOLS
        assert len(ALL_TOOLS) == 17
        tool_names = {t.name for t in ALL_TOOLS}
        assert "sheriff_run_tool" in tool_names
        assert "defend_tool" in tool_names
        assert "witch_" + "none_tool" not in tool_names
        assert "sher" + "riff_run_tool" not in tool_names

    def test_vote_tool(self):
        from app.services.tool import vote_tool
        result = vote_tool.invoke({"target": 7, "reasoning": "suspicious"})
        assert result["action"] == "vote"
        assert result["target"] == 7

    def test_speak_tool(self):
        from app.services.tool import speak_tool
        result = speak_tool.invoke({"text": "I am a villager", "private_reasoning": "bluff"})
        assert result["action"] == "speak"
        assert result["public_text"] == "I am a villager"

    def test_seer_check_tool(self):
        from app.services.tool import seer_check_tool
        result = seer_check_tool.invoke({"target": 3, "reasoning": "unknown"})
        assert result["action"] == "seer_check"
        assert result["target"] == 3

    def test_witch_tools(self):
        from app.services.tool import pass_tool, witch_save_tool, witch_poison_tool
        assert witch_save_tool.invoke({"target": 5})["action"] == "witch_save"
        assert witch_poison_tool.invoke({"target": 8})["action"] == "witch_poison"
        assert pass_tool.invoke({})["action"] == "pass"

    def test_hunter_shoot_tool(self):
        from app.services.tool import hunter_shoot_tool
        result = hunter_shoot_tool.invoke({"target": 6})
        assert result["action"] == "hunter_shoot"

    def test_guard_protect_tool(self):
        from app.services.tool import guard_protect_tool
        result = guard_protect_tool.invoke({"target": 2})
        assert result["action"] == "guard_protect"

    def test_werewolf_kill_tool(self):
        from app.services.tool import werewolf_kill_tool
        result = werewolf_kill_tool.invoke({"target": 9})
        assert result["action"] == "werewolf_kill"

    def test_sheriff_tools(self):
        from app.services.tool import sheriff_run_tool, sheriff_withdraw_tool, sheriff_badge_tool
        assert sheriff_run_tool.invoke({})["action"] == "sheriff_run"
        assert sheriff_withdraw_tool.invoke({"choice": "stay"})["choice"] == "stay"
        assert sheriff_badge_tool.invoke({"choice": "transfer", "target": 4})["action"] == "sheriff_badge"

    def test_speech_order_tool(self):
        from app.services.tool import speech_order_tool
        assert speech_order_tool.invoke({"choice": "reverse"})["choice"] == "reverse"

    def test_white_wolf_tool(self):
        from app.services.tool import white_wolf_explode_tool
        assert white_wolf_explode_tool.invoke({"choice": "pass"})["action"] == "white_wolf_explode"

    def test_pass_tool(self):
        from app.services.tool import pass_tool
        assert pass_tool.invoke({})["action"] == "pass"

    def test_claim_role_tool(self):
        from app.services.tool import claim_role_tool
        result = claim_role_tool.invoke({"role": "seer", "reasoning": "I checked", "public": True})
        assert result["action"] == "claim_role"

    def test_accuse_tool(self):
        from app.services.tool import accuse_tool
        result = accuse_tool.invoke({"target": 10, "evidence": "contradiction"})
        assert result["action"] == "accuse"

    def test_defend_tool(self):
        from app.services.tool import defend_tool
        result = defend_tool.invoke({"text": "P3 has consistent logic", "target": 3})
        assert result["action"] == "defend"
        assert result["target"] == 3
        assert result["public_text"] == "P3 has consistent logic"

    def test_get_tools_for_phase_night(self):
        from app.services.tool import get_tools_for_phase
        tools = get_tools_for_phase("night", "seer")
        assert len(tools) >= 2
        witch_tools = {t.name for t in get_tools_for_phase("night", "witch")}
        assert "pass_tool" in witch_tools
        assert "witch_" + "none_tool" not in witch_tools

    def test_get_tools_for_phase_day(self):
        from app.services.tool import get_tools_for_phase
        tools = get_tools_for_phase("day_speech", "villager")
        assert len(tools) >= 4
        assert "defend_tool" in {t.name for t in tools}


# ===========================================================================
# app/services/prompt.py
# ===========================================================================

class TestServicesPrompt:

    def test_build_decision_prompt_template(self):
        from app.services.prompt import build_decision_prompt_template
        tmpl = build_decision_prompt_template()
        rendered = tmpl.invoke({
            "player_id": 3, "role": "seer", "phase": "night",
            "day": 1, "action_type": "seer_check", "candidates": "[2,3]",
            "alive_players": "[1,2,3]", "dead_players": "[]",
            "sheriff_id": "None", "known_roles": "{}", "seer_checks": "{}",
            "metadata": "{}", "skill_context": "", "hints_block": "",
            "action_instruction": "查验", "memory": [],
        })
        assert len(rendered.messages) == 2  # system + user
        system_text = rendered.messages[0].content
        user_text = rendered.messages[1].content
        assert "你是 3 号玩家，身份: seer。" in system_text
        assert "当前阶段: night" in user_text
        assert "本次行动: seer_check" in user_text
        assert "{player_id}" not in system_text
        assert "{phase}" not in user_text

    def test_action_instruction(self):
        from app.services.prompt import action_instruction
        from engine.models import ActionType
        instruction = action_instruction(ActionType.SEER_CHECK)
        assert "查验" in instruction

    def test_extract_json_valid(self):
        from app.util.text import extract_json
        data = extract_json('{"key": "value"}')
        assert data == {"key": "value"}

    def test_extract_json_with_markdown(self):
        from app.util.text import extract_json
        raw = 'Some text\n```json\n{"a": 1}\n```'
        data = extract_json(raw)
        assert data == {"a": 1}

    def test_extract_json_invalid(self):
        from app.util.text import extract_json
        with pytest.raises(ValueError):
            extract_json("no json here")

    def test_select_skills_returns_list(self):
        from app.services.prompt import select_skills
        from engine.models import Role

        class _Ctx:
            request = type("_Req", (), {"action_type": "seer_check", "metadata": {}})

        result = select_skills(_Ctx(), Role.SEER, skill_root=None)
        assert isinstance(result, list)
        # Without a real skill root, returns empty list
        assert len(result) == 0

    def test_load_markdown_skill_report_records_diagnostics(self, tmp_path):
        from app.services.prompt import load_markdown_skill_report

        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        (skill_dir / "valid.md").write_text(
            """---
name: valid_seer
role: seer
applicable_actions:
  - seer_check
---

# Valid

## Strategy

Check the most suspicious player.
""",
            encoding="utf-8",
        )
        (skill_dir / "broken.md").write_text("# Missing front matter\n", encoding="utf-8")
        (skill_dir / "loose.md").write_text(
            """---
name: loose
role: seer
applicable_actions:
  - unknown_action
requires: bad
status: archived
---

# Loose
""",
            encoding="utf-8",
        )

        report = load_markdown_skill_report(skill_dir)

        assert [skill.name for skill in report.skills] == ["loose", "valid_seer"]
        messages = [diagnostic.format() for diagnostic in report.diagnostics]
        assert any("broken.md" in msg and "missing YAML front matter" in msg for msg in messages)
        assert any("loose.md" in msg and "unknown action 'unknown_action'" in msg for msg in messages)
        assert any("loose.md" in msg and "requires must be a mapping" in msg for msg in messages)
        assert any("loose.md" in msg and "unknown status 'archived'" in msg for msg in messages)

    def test_load_markdown_skills_expands_vote_action_alias(self, tmp_path):
        from app.services.prompt import load_markdown_skill_report
        from engine.models import ActionType

        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        (skill_dir / "vote.md").write_text(
            """---
name: vote_alias
role: seer
applicable_actions:
  - vote
---

# Vote alias
""",
            encoding="utf-8",
        )

        report = load_markdown_skill_report(skill_dir)

        assert report.diagnostics == []
        assert report.skills[0].applicable_actions == {
            ActionType.SHERIFF_VOTE,
            ActionType.EXILE_VOTE,
            ActionType.PK_VOTE,
        }

    def test_select_skills_refreshes_when_skill_file_changes(self, tmp_path):
        from app.services.prompt import configure_skill_root, select_skills
        from engine.models import ActionType, Role

        class _Ctx:
            request = type("_Req", (), {"action_type": ActionType.SEER_CHECK, "metadata": {}})

        skill_dir = tmp_path / "skills"
        skill_dir.mkdir()
        skill_path = skill_dir / "seer.md"
        skill_path.write_text(
            """---
name: first_name
role: seer
applicable_actions:
  - seer_check
---

# First

## Strategy

Check one player.
""",
            encoding="utf-8",
        )
        configure_skill_root(None)
        assert [skill.name for skill in select_skills(_Ctx(), Role.SEER, skill_root=skill_dir)] == ["first_name"]

        skill_path.write_text(
            """---
name: second_name
role: seer
applicable_actions:
  - seer_check
---

# Second

## Strategy

Check one suspicious player immediately.
""",
            encoding="utf-8",
        )

        assert [skill.name for skill in select_skills(_Ctx(), Role.SEER, skill_root=skill_dir)] == ["second_name"]

    def test_format_skill_context_empty(self):
        from app.services.prompt import format_skill_context
        from engine.models import ActionType
        result = format_skill_context([], ActionType.SPEAK)
        assert result == ""

    def test_skill_index_dataclass(self):
        from app.services.prompt import SkillIndex
        si = SkillIndex(by_role={})
        assert si.by_role == {}

    def test_configure_skill_root(self):
        from app.services.prompt import configure_skill_root
        configure_skill_root(None)  # should not raise

    def test_prepare_llm_messages_adds_schema_version_instruction(self):
        from app.services.prompt import prepare_llm_messages

        messages = prepare_llm_messages(
            [{"role": "user", "content": "请输出判断"}],
            stage="consolidate",
        )

        assert messages[0] == {"role": "user", "content": "请输出判断"}
        assert any("schema_version" in getattr(message, "content", "") for message in messages)

    def test_prepare_llm_messages_applies_prompt_budget(self):
        from app.services.prompt import PromptBudget, prepare_llm_messages

        messages = prepare_llm_messages(
            [{"role": "user", "content": "a" * 200}],
            stage="raw_message",
            budget=PromptBudget(max_total_chars=80, max_message_chars=60, min_message_chars=0),
        )

        assert len(messages) == 1
        assert len(messages[0]["content"]) <= 80
        assert "prompt truncated" in messages[0]["content"]


# ===========================================================================
# app/services/chain.py — 5 chains (LLM-only, test structure not invocation)
# ===========================================================================

class TestServicesChain:

    def test_run_chain_functions_exist(self):
        from app.services.chain import (
            build_apply_chain,
            build_compress_chain,
            build_consolidate_chain,
            run_compress_chain,
            run_consolidate_chain,
            run_apply_chain,
            run_evidence_chain,
            build_decision_chain,
            build_evidence_chain,
            build_raw_message_chain,
            create_apply_chain,
            create_consolidate_chain,
            create_decision_chain,
            create_evidence_chain,
        )
        assert callable(build_apply_chain)
        assert callable(build_compress_chain)
        assert callable(build_consolidate_chain)
        assert callable(run_compress_chain)
        assert callable(run_consolidate_chain)
        assert callable(run_apply_chain)
        assert callable(run_evidence_chain)
        assert callable(build_decision_chain)
        assert callable(build_evidence_chain)
        assert callable(build_raw_message_chain)
        assert callable(create_apply_chain)
        assert callable(create_consolidate_chain)
        assert callable(create_decision_chain)
        assert callable(create_evidence_chain)

    def test_decision_chain_runs_with_fake_model(self):
        import asyncio

        from app.services.chain import build_decision_chain, create_decision_chain

        class FakeModel:
            async def ainvoke(self, messages):
                assert isinstance(messages, list)
                assert any("schema_version" in getattr(message, "content", "") for message in messages)
                return type(
                    "Result",
                    (),
                    {
                        "content": (
                            '{"schema_version":"1.0","choice":null,"target":null,"public_text":"ok",'
                            '"private_reasoning":"private","confidence":0.9,'
                            '"alternatives":[],"rejected_reasons":[],"selected_skills":[]}'
                        )
                    },
                )()

        inputs = {
            "player_id": 3,
            "role": "villager",
            "phase": "day_speech",
            "day": 1,
            "action_type": "speak",
            "candidates": "[]",
            "alive_players": "[1,2,3]",
            "dead_players": "[]",
            "sheriff_id": "None",
            "known_roles": "{}",
            "seer_checks": "{}",
            "metadata": "{}",
            "skill_context": "",
            "hints_block": "",
            "action_instruction": "speak",
            "memory": [],
        }

        async def _run():
            model = FakeModel()
            assert (await build_decision_chain(model).ainvoke(inputs))["public_text"] == "ok"
            assert (await create_decision_chain(model).ainvoke(inputs))["confidence"] == 0.9

        asyncio.run(_run())

    def test_raw_message_chains_run_with_fake_model(self):
        import asyncio

        from app.services.chain import (
            build_apply_chain,
            build_consolidate_chain,
            build_evidence_chain,
            build_raw_message_chain,
            run_apply_chain,
            run_consolidate_chain,
            run_decision_chain,
            run_evidence_chain,
        )

        class FakeModel:
            async def ainvoke(self, messages):
                assert messages[0]["role"] == "user"
                return type("Result", (), {"content": '{"schema_version":"1.0","ok":true}'})()

        async def _run():
            messages = [{"role": "user", "content": "judge"}]
            model = FakeModel()
            assert await build_raw_message_chain(model).ainvoke(messages) == '{"schema_version":"1.0","ok":true}'
            assert await build_consolidate_chain(model).ainvoke(messages) == '{"schema_version":"1.0","ok":true}'
            assert await build_apply_chain(model).ainvoke(messages) == '{"schema_version":"1.0","ok":true}'
            assert await build_evidence_chain(model).ainvoke(messages) == '{"schema_version":"1.0","ok":true}'
            assert await run_decision_chain(model, messages=messages) == '{"schema_version":"1.0","ok":true}'
            assert await run_consolidate_chain(model, messages=messages) == '{"schema_version":"1.0","ok":true}'
            assert await run_apply_chain(model, messages=messages) == '{"schema_version":"1.0","ok":true}'
            assert await run_evidence_chain(model, messages=messages) == '{"schema_version":"1.0","ok":true}'

        asyncio.run(_run())

    def test_versioned_raw_message_chains_add_schema_instruction(self):
        import asyncio

        from app.services.chain import (
            build_apply_chain,
            build_consolidate_chain,
            build_evidence_chain,
            run_decision_chain,
        )

        class FakeModel:
            async def ainvoke(self, messages):
                assert any("schema_version" in getattr(message, "content", "") for message in messages)
                return type("Result", (), {"content": '{"schema_version":"1.0","ok":true}'})()

        async def _run():
            messages = [{"role": "user", "content": "judge"}]
            model = FakeModel()
            assert await build_consolidate_chain(model).ainvoke(messages) == '{"schema_version":"1.0","ok":true}'
            assert await build_apply_chain(model).ainvoke(messages) == '{"schema_version":"1.0","ok":true}'
            assert await build_evidence_chain(model).ainvoke(messages) == '{"schema_version":"1.0","ok":true}'
            assert await run_decision_chain(model, messages=messages) == '{"schema_version":"1.0","ok":true}'

        asyncio.run(_run())

    def test_raw_message_chain_success_records_schema_version_diagnostic(self):
        import asyncio

        from app.services.chain import run_apply_chain

        class FakeModel:
            async def ainvoke(self, messages):
                return type("Result", (), {"content": '{"schema_version":"1.0","files":{}}'})()

        async def _run():
            raw = await run_apply_chain(FakeModel(), messages=[{"role": "user", "content": "apply"}])
            assert raw == '{"schema_version":"1.0","files":{}}'
            assert raw.diagnostic["observed_schema_version"] == "1.0"
            assert raw.diagnostic["expected_schema_version"] == "1.0"

        asyncio.run(_run())

    def test_raw_message_chain_failures_include_llm_diagnostics(self):
        import asyncio

        import pytest

        from app.services.chain import (
            LLMCallError,
            run_apply_chain,
            run_consolidate_chain,
            run_decision_chain,
            run_evidence_chain,
        )

        class FakeModel:
            model_name = "fake-diagnostic-model"

            async def ainvoke(self, messages):
                raise TimeoutError("backend timed out token=secret-token")

        async def _run():
            messages = [{"role": "user", "content": "judge"}]
            model = FakeModel()

            for expected_stage, runner in [
                ("decision", run_decision_chain),
                ("consolidate", run_consolidate_chain),
                ("apply", run_apply_chain),
                ("evidence", run_evidence_chain),
            ]:
                with pytest.raises(LLMCallError) as caught:
                    await runner(model, messages=messages)

                error = caught.value
                assert error.stage == expected_stage
                assert error.model == "fake-diagnostic-model"
                assert error.elapsed_ms >= 0
                assert error.exception_type == "TimeoutError"
                assert error.diagnostic["stage"] == expected_stage
                assert error.diagnostic["model"] == "fake-diagnostic-model"
                assert error.diagnostic["elapsed_ms"] == error.elapsed_ms
                assert error.diagnostic["exception_type"] == "TimeoutError"
                assert error.diagnostic["message"] == "backend timed out token=[REDACTED]"
                assert error.diagnostic["attempts"] == 1
                assert error.diagnostic["expected_schema_version"] == "1.0"
                assert error.diagnostic["observed_schema_version"] is None
                assert error.diagnostic["messages"].startswith("[REDACTED length=")
                text = str(error)
                assert f"stage={expected_stage}" in text
                assert "model=fake-diagnostic-model" in text
                assert "elapsed_ms=" in text
                assert "exception_type=TimeoutError" in text
                assert "secret-token" not in text

        asyncio.run(_run())

    def test_decision_chain_failure_includes_llm_diagnostics(self):
        import asyncio

        import pytest

        from app.services.chain import LLMCallError, build_decision_chain

        class FakeModel:
            model = "decision-model"

            async def ainvoke(self, messages):
                assert isinstance(messages, list)
                raise ValueError("invalid request")

        inputs = {
            "player_id": 3,
            "role": "villager",
            "phase": "day_speech",
            "day": 1,
            "action_type": "speak",
            "candidates": "[]",
            "alive_players": "[1,2,3]",
            "dead_players": "[]",
            "sheriff_id": "None",
            "known_roles": "{}",
            "seer_checks": "{}",
            "metadata": "{}",
            "skill_context": "",
            "hints_block": "",
            "action_instruction": "speak",
            "memory": [],
        }

        async def _run():
            with pytest.raises(LLMCallError) as caught:
                await build_decision_chain(FakeModel()).ainvoke(inputs)

            error = caught.value
            assert error.stage == "decision"
            assert error.model == "decision-model"
            assert error.elapsed_ms >= 0
            assert error.exception_type == "ValueError"
            assert "stage=decision" in str(error)
            assert "model=decision-model" in str(error)
            assert "exception_type=ValueError" in str(error)

        asyncio.run(_run())

    def test_compress_chain_runs_with_fake_model(self):
        import asyncio

        from app.services.chain import build_compress_chain, run_compress_chain
        from app.services.memory import AgentMemory, Segment, SegmentEvent
        from engine.models import Role

        class FakeModel:
            async def ainvoke(self, messages):
                assert messages[0]["role"] == "system"
                return type(
                    "Result",
                    (),
                    {
                        "content": (
                            '{"segment_key":"night:1","summary":"ok",'
                            '"key_events":["event"],"player_notes":{"2":"note"},'
                            '"unknowns":["unknown"]}'
                        )
                    },
                )()

        async def _run():
            memory = AgentMemory(player_id=1, role=Role.VILLAGER)
            segment = Segment(segment_key="night:1", day=1, phase_group="night")
            segment.add_event(SegmentEvent(day=1, phase="night", event_type="speech", actor=2, target=None, content="hello"))
            model = FakeModel()
            data = await build_compress_chain(model).ainvoke({
                "game_id": "g1",
                "player_id": memory.player_id,
                "role": "villager",
                "segment_key": segment.segment_key,
                "events_text": "P2 hello",
            })
            assert data["summary"] == "ok"
            summary = await run_compress_chain(model, segment, memory, game_id="g1")
            assert summary is not None
            assert summary.summary == "ok"

        asyncio.run(_run())

    def test_compress_prompt_template(self):
        from app.services.chain import _COMPRESS_PROMPT, _COMPRESS_SYSTEM
        assert "segment_key" in _COMPRESS_PROMPT
        assert "events_text" in _COMPRESS_PROMPT
        assert isinstance(_COMPRESS_SYSTEM, str)
