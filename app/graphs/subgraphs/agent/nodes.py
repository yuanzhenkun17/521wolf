"""Agent decision subgraph — 7-step decision pipeline."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from engine import ActionRequest, ActionResponse, ActionType, Phase, Role

from app.services.memory import AgentMemory
from app.services.prompt import (
    PromptBudget,
    build_decision_prompt_template,
    format_memory_messages,
    format_skill_context,
    load_markdown_skill_diagnostics,
    select_skills,
)
from app.services.chain import run_compress_chain, run_decision_chain
from app.util.text import extract_json
from app.util.targets import first_candidate_target, target_in_candidates, target_required_for_action

_log = logging.getLogger(__name__)


_SMOKE_FAST_POLICY_SKIP_ACTIONS: frozenset[str] = frozenset({
    ActionType.SHERIFF_RUN.value,
    ActionType.SHERIFF_WITHDRAW.value,
    ActionType.SHERIFF_SPEAK.value,
    ActionType.SPEECH_ORDER.value,
    ActionType.SHERIFF_BADGE.value,
    ActionType.SPEAK.value,
    ActionType.WHITE_WOLF_EXPLODE.value,
    ActionType.LAST_WORD.value,
    ActionType.PK_SPEAK.value,
})

_POLICY_SKIP_PROTECTED_ACTIONS: frozenset[str] = frozenset({
    ActionType.GUARD_PROTECT.value,
    ActionType.WEREWOLF_KILL.value,
    ActionType.SEER_CHECK.value,
    ActionType.WITCH_ACT.value,
    ActionType.EXILE_VOTE.value,
    ActionType.PK_VOTE.value,
    ActionType.SHERIFF_VOTE.value,
    ActionType.HUNTER_SHOOT.value,
})


def _issue_message(prefix: str, exc: BaseException) -> str:
    return f"{prefix}: {type(exc).__name__}: {exc}"


def _diagnostic_record(
    *,
    kind: str,
    stage: str,
    message: str,
    exc: BaseException | None = None,
    level: str = "error",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "kind": kind,
        "stage": stage,
        "level": level,
        "message": message,
    }
    if extra:
        record.update(extra)
    if exc is not None:
        diagnostic = getattr(exc, "diagnostic", None)
        if isinstance(diagnostic, dict):
            record["exception_type"] = str(diagnostic.get("exception_type") or type(exc).__name__)
            record["exception_message"] = str(diagnostic.get("message") or exc)
            record["diagnostic"] = dict(diagnostic)
        else:
            record["exception_type"] = type(exc).__name__
            record["exception_message"] = str(exc)
    return record


def _record_diagnostic(
    state: dict,
    *,
    kind: str,
    stage: str,
    message: str,
    exc: BaseException | None = None,
    level: str = "error",
    extra: dict[str, Any] | None = None,
) -> None:
    state.setdefault("diagnostics", []).append(
        _diagnostic_record(
            kind=kind,
            stage=stage,
            message=message,
            exc=exc,
            level=level,
            extra=extra,
        )
    )


def _append_error(
    state: dict,
    message: str,
    *,
    kind: str | None = None,
    stage: str | None = None,
    exc: BaseException | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    state.setdefault("errors", []).append(message)
    if kind is not None:
        _record_diagnostic(
            state,
            kind=kind,
            stage=stage or "unknown",
            message=message,
            exc=exc,
            extra=extra,
        )


def _append_warning(
    state: dict,
    message: str,
    *,
    kind: str | None = None,
    stage: str | None = None,
    exc: BaseException | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    state.setdefault("warnings", []).append(message)
    if kind is not None:
        _record_diagnostic(
            state,
            kind=kind,
            stage=stage or "unknown",
            message=message,
            exc=exc,
            level="warning",
            extra=extra,
        )


# ---------------------------------------------------------------------------
# Node-level helpers (mirroring agent/decision/steps/*.py but using dict state)
# ---------------------------------------------------------------------------

def _remember_node(state: dict, memory: AgentMemory) -> dict:
    """Remember step: update memory from observation, populate memory_context."""
    request = _request_from_state(state)
    if request.observation is None:
        state["memory_context"] = _empty_memory_context(request, state.get("role", ""))
        return state
    try:
        state["memory_context"] = memory.build_context(request)
    except Exception as exc:
        message = _issue_message("memory build_context failed", exc)
        _append_error(
            state,
            message,
            kind="memory_error",
            stage="memory.build_context",
            exc=exc,
        )
        try:
            memory.remember_error(message)
        except Exception as remember_exc:
            _append_error(
                state,
                _issue_message("memory remember_error failed", remember_exc),
                kind="memory_error",
                stage="memory.remember_error",
                exc=remember_exc,
            )
        state["memory_context"] = _empty_memory_context(request, state.get("role", ""))
        state["memory_context"]["errors"] = list(state.get("errors", []))[-3:]
    _trim_memory_context_for_agent_config(state)
    return state


async def _compress_node(state: dict, memory: AgentMemory, model: Any) -> dict:
    """Compress old memory segments if needed."""
    if _as_bool(state.get("agent_memory_compression_enabled"), default=True) is False:
        return state
    closed = [s for s in memory.segments if s.closed]
    if len(closed) <= 4:
        return state
    compressed_keys = set(memory.compressed_segment_summaries.keys())
    for seg in closed:
        if seg.segment_key in compressed_keys or seg.compression_failed:
            continue
        summary = await run_compress_chain(model, seg, memory, game_id=memory.game_id or "unknown")
        if summary is not None:
            memory.compressed_segment_summaries[seg.segment_key] = summary
            state.setdefault("compressed_segments_added", []).append(seg.segment_key)
        else:
            seg.compression_retry_count += 1
            if seg.compression_retry_count >= 2:
                seg.compression_failed = True
        break
    return state


def _select_skills_node(state: dict, *, skill_root: Path | str | None = None) -> dict:
    """Select role skills and format context."""
    try:
        role = Role(state.get("role", "villager"))
    except (ValueError, KeyError) as exc:
        _append_error(
            state,
            _issue_message(f"skill selection skipped for invalid role {state.get('role')!r}", exc),
            kind="state_error",
            stage="skill.role",
            exc=exc,
        )
        state["selected_skills"] = []
        state["skill_context"] = ""
        state["strategy_advice"] = {"skill_count": 0}
        return state

    request = _request_from_state(state)
    skill_root_path = Path(skill_root) if skill_root else None
    skill_warnings: list[str] = []
    if skill_root_path is not None:
        try:
            diagnostics = load_markdown_skill_diagnostics(skill_root_path)
        except Exception as exc:
            _append_error(
                state,
                _issue_message("skill diagnostics failed", exc),
                kind="skill_error",
                stage="skill.diagnostics",
                exc=exc,
            )
            diagnostics = []
        for diagnostic in diagnostics:
            message = f"skill {diagnostic.severity}: {diagnostic.path}: {diagnostic.message}"
            skill_warnings.append(message)
            _append_warning(
                state,
                message,
                kind="skill_error",
                stage="skill.diagnostics",
            )
    try:
        selected = select_skills(
            SimpleNamespace(request=request),
            role,
            skill_root=skill_root_path,
        )
    except Exception as exc:
        _append_error(
            state,
            _issue_message("skill selection failed", exc),
            kind="skill_error",
            stage="skill.select",
            exc=exc,
        )
        selected = []
    state["selected_skills"] = [s.name for s in selected]
    at = request.action_type
    try:
        state["skill_context"] = format_skill_context(selected, at)
    except Exception as exc:
        _append_error(
            state,
            _issue_message("skill context formatting failed", exc),
            kind="skill_error",
            stage="skill.format_context",
            exc=exc,
        )
        state["skill_context"] = ""
    state["strategy_advice"] = {"skill_count": len(selected)}
    if skill_warnings:
        state["strategy_advice"]["warnings"] = skill_warnings
    return state


def _build_prompt_node(state: dict) -> dict:
    """Build LLM messages via ChatPromptTemplate + format_memory_messages."""
    try:
        role = Role(state.get("role", "villager"))
    except (ValueError, KeyError) as exc:
        _append_warning(
            state,
            _issue_message(f"prompt role fallback for invalid role {state.get('role')!r}", exc),
            kind="state_error",
            stage="prompt.role",
            exc=exc,
        )
        role = Role.VILLAGER

    request = _request_from_state(state)
    at = request.action_type

    memory_msgs = format_memory_messages(state.get("memory_context", {}))
    current = state.get("memory_context", {}).get("current_visible_state", {})
    private = state.get("memory_context", {}).get("private_facts", {})
    skill_ctx = state.get("skill_context", "")
    hints = state.get("strategy_advice", {}).get("prompt_hints", [])
    hints_block = ""
    if hints:
        hints_block = "技能提示:\n" + "\n".join(f"- {h}" for h in hints) + "\n\n"
    skill_context_block = ""
    if skill_ctx:
        skill_context_block = f"已注入策略 Skill:\n{skill_ctx}\n\n"

    from app.services.prompt import action_instruction
    template = build_decision_prompt_template()
    rendered = template.invoke({
        "player_id": state["player_id"],
        "role": role.value,
        "phase": current.get("phase", request.phase.value),
        "day": current.get("day", 0),
        "action_type": at.value,
        "candidates": str(current.get("candidates", list(request.candidates))),
        "alive_players": str(current.get("alive_players", [])),
        "dead_players": str(current.get("dead_players", [])),
        "sheriff_id": str(current.get("sheriff_id")),
        "known_roles": json.dumps(private.get("known_roles", {}), ensure_ascii=False),
        "seer_checks": json.dumps(private.get("seer_checks", {}), ensure_ascii=False),
        "metadata": json.dumps(private.get("metadata", dict(request.metadata)), ensure_ascii=False),
        "skill_context": skill_context_block,
        "hints_block": hints_block,
        "action_instruction": action_instruction(at),
        "memory": memory_msgs,
    })
    # Convert to OpenAI-style messages
    state["messages"] = [
        {"role": getattr(m, "type", "user"), "content": m.content}
        for m in rendered.messages
    ]
    return state


async def _call_model_node(state: dict, model: Any) -> dict:
    """Call the LLM and capture raw output."""
    request = _request_from_state(state)
    started = time.perf_counter()
    try:
        state["raw_output"] = await run_decision_chain(
            model,
            messages=state.get("messages", []),
            prompt_budget=state.get("prompt_budget") or _prompt_budget_from_config(state),
            metadata=_decision_langfuse_metadata(state, request),
        )
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        state["source"] = "llm"
        _record_diagnostic(
            state,
            kind="model_call",
            stage="model.decision_chain",
            level="info",
            message="LLM decision call completed.",
            extra=_model_call_extra(request, elapsed_ms=elapsed_ms),
        )
    except Exception as exc:
        elapsed_ms = int(round((time.perf_counter() - started) * 1000))
        _append_error(
            state,
            f"LLM call failed: {exc}",
            kind="model_error",
            stage="model.decision_chain",
            exc=exc,
            extra=_model_call_extra(request, elapsed_ms=elapsed_ms),
        )
        state["llm_error"] = str(exc)
        state["source"] = "llm_error"
        state["raw_output"] = ""
    return state


def _parse_node(state: dict) -> dict:
    """Parse raw LLM output into a structured decision."""
    raw = state.get("raw_output", "")
    if not raw:
        state["parsed_decision"] = {}
        return state
    try:
        parsed = extract_json(raw)
    except (ValueError, json.JSONDecodeError) as exc:
        _append_error(
            state,
            f"JSON parse error: {exc}",
            kind="parse_error",
            stage="parse.extract_json",
            exc=exc,
        )
        state["parsed_decision"] = {}
        return state

    if not isinstance(parsed, dict):
        message = f"JSON parse error: expected object, got {type(parsed).__name__}"
        _append_error(
            state,
            message,
            kind="parse_error",
            stage="parse.extract_json",
            exc=ValueError(message),
        )
        state["parsed_decision"] = {}
        return state

    state["parsed_decision"] = parsed
    try:
        state["confidence"] = float(parsed.get("confidence", 0.5) or 0.5)
    except (TypeError, ValueError) as exc:
        message = _issue_message("confidence parse failed", exc)
        _append_error(
            state,
            message,
            kind="parse_error",
            stage="parse.confidence",
            exc=exc,
        )
        state["confidence"] = 0.5
    return state


def _enforce_policy_node(state: dict) -> dict:
    """Validate and repair the parsed decision."""
    request = _request_from_state(state)
    pd = state.get("parsed_decision", {})
    if not pd:
        state["response"] = _response_to_dict(_fallback_response(request))
        if state.get("source") != "llm_error":
            state["source"] = "fallback"
        state.setdefault("policy_adjustments", []).append("No parsed response available; used fallback.")
        return state

    response = ActionResponse(
        request.action_type,
        text=str(pd.get("public_text") or pd.get("text") or ""),
        target=_coerce_target(pd.get("target")),
        choice=pd.get("choice"),
    )
    response = _repair_public_text_placeholders(request, response, state)
    response = _repair_or_fallback(request, response, state)
    state["response"] = _response_to_dict(response)
    return state


# ---------------------------------------------------------------------------
# AgentRuntimeAdapter — PlayerAgent protocol wrapper
# ---------------------------------------------------------------------------

def _build_initial_state(
    request: ActionRequest,
    player_id: int,
    role: str,
    **runtime: Any,
) -> dict:
    state = {
        "request": {
            "player_id": request.player_id,
            "action_type": request.action_type.value,
            "phase": request.phase.value,
            "observation": request.observation,
            "candidates": list(request.candidates),
            "retry_count": request.retry_count,
            "metadata": dict(request.metadata),
        },
        "player_id": player_id,
        "role": role,
        "memory_context": {},
        "selected_skills": [],
        "skill_context": "",
        "strategy_advice": {},
        "compressed_segments_added": [],
        "compression_errors": [],
        "messages": [],
        "raw_output": "",
        "llm_error": "",
        "retry_count": 0,
        "parsed_decision": {},
        "confidence": 0.0,
        "response": None,
        "source": "llm",
        "policy_adjustments": [],
        "warnings": [],
        "errors": [],
        "diagnostics": [],
    }
    state.update({k: v for k, v in runtime.items() if v is not None})
    return state


class AgentRuntimeAdapter:
    """Wraps the agent subgraph as a PlayerAgent protocol.

    Two invocation modes:
    1. Sequential (no graph): runs the 7 steps directly on a dict state
    2. Graph (compiled LangGraph): delegates to graph.ainvoke()
    """

    def __init__(
        self,
        *,
        graph: Any = None,
        player_id: int,
        role: Role,
        model: Any,
        memory: AgentMemory | None = None,
        recorder: Any = None,
        trace_recorder: Any = None,
        game_id: str | None = None,
        skill_dir: Path | str | None = None,
        paths: Any = None,
        agent_runtime_config: dict[str, Any] | None = None,
    ) -> None:
        self.player_id = player_id
        self.role = role
        self.model = model
        self.memory = memory or AgentMemory(player_id=player_id, role=role)
        self.recorder = recorder
        self.trace_recorder = trace_recorder
        self.game_id = game_id
        self.skill_dir = Path(skill_dir) if skill_dir else None
        self.paths = paths
        self.agent_runtime_config = _normalize_agent_runtime_config(agent_runtime_config or {})
        self._graph = graph

    async def act(self, request: ActionRequest) -> ActionResponse:
        if _should_policy_skip_llm(request, self.agent_runtime_config):
            state = _build_initial_state(
                request,
                self.player_id,
                self.role.value,
                **self.agent_runtime_config,
            )
            state = _remember_node(state, self.memory)
            _trim_memory_context_for_agent_config(state)
            state["source"] = "policy_skipped"
            state["response"] = _response_to_dict(_fallback_response(request))
            _record_diagnostic(
                state,
                kind="policy_skip",
                stage="agent.policy_skip_llm",
                level="info",
                message=f"Skipped LLM for {request.action_type.value} via agent policy skip.",
                extra={
                    "player_id": request.player_id,
                    "action_type": request.action_type.value,
                    "preset": self.agent_runtime_config.get("agent_policy_skip_llm_preset") or "",
                },
            )
            return self._finalize_decision(request, state)

        graph_diagnostics: list[dict[str, str]] = []
        if self._graph is not None:
            try:
                graph_state = await self._act_with_graph(request)
                if graph_state is not None and graph_state.get("response") is not None:
                    return self._finalize_decision(request, graph_state)
                graph_diagnostics.append(
                    _diagnostic_record(
                        kind="state_error",
                        stage="graph.response",
                        level="warning",
                        message="Agent graph produced no response; used sequential pipeline.",
                    )
                )
            except Exception as exc:
                _log.warning("agent graph failed; falling back to sequential pipeline", exc_info=True)
                graph_diagnostics.append(
                    _diagnostic_record(
                        kind="state_error",
                        stage="graph.invoke",
                        message=f"Agent graph failed: {exc}",
                        exc=exc,
                    )
                )

        state = _build_initial_state(
            request,
            self.player_id,
            self.role.value,
            **self.agent_runtime_config,
        )
        for diagnostic in graph_diagnostics:
            state["errors"].append(diagnostic["message"])
            state["diagnostics"].append(diagnostic)
        state = _remember_node(state, self.memory)
        _trim_memory_context_for_agent_config(state)
        state = await _compress_node(state, self.memory, self.model)
        state = _select_skills_node(state, skill_root=self.skill_dir)
        state = _build_prompt_node(state)
        state = await _call_model_node(state, self.model)
        state = _parse_node(state)
        state = _enforce_policy_node(state)

        response = state.get("response")
        if response is None:
            raise RuntimeError("Pipeline produced no response")
        return self._finalize_decision(request, state)

    async def _act_with_graph(self, request: ActionRequest) -> dict | None:
        result = await self._graph.ainvoke(
            _build_initial_state(
                request,
                self.player_id,
                self.role.value,
                model=self.model,
                memory=self.memory,
                skill_dir=str(self.skill_dir) if self.skill_dir else None,
                game_id=self.game_id,
                **self.agent_runtime_config,
            )
        )
        return result if isinstance(result, dict) else None

    def _finalize_decision(self, request: ActionRequest, state: dict) -> ActionResponse:
        response = _state_response(request, state)
        if response is None:
            raise RuntimeError("Pipeline produced no response")

        decision_record = _build_decision_record(request, response, state, self.role.value)
        state["decision_record"] = decision_record
        response.decision_id = decision_record.decision_id
        if request.defer_decision_recording:
            self._record_decision_trace(request, response, state, decision_record)
            response.on_accepted = lambda accepted_response: self._record_accepted_decision(
                request,
                accepted_response,
                state,
                decision_record,
            )
            return response

        self._record_accepted_decision(request, response, state, decision_record, record_trace=True)
        return response

    def _record_accepted_decision(
        self,
        request: ActionRequest,
        response: ActionResponse,
        state: dict,
        decision_record: Any,
        *,
        record_trace: bool = False,
    ) -> None:
        decision_record.selected_target = response.target
        decision_record.selected_choice = response.choice
        decision_record.public_text = response.text
        try:
            self.memory.remember_action(request, response, decision_record)
        except Exception as exc:
            message = _issue_message("remember_action failed", exc)
            _log.error("remember_action failed", exc_info=True)
            _append_error(
                state,
                message,
                kind="memory_error",
                stage="memory.remember_action",
                exc=exc,
            )
            decision_record.errors.append(message)

        if self.recorder is not None:
            try:
                self.recorder.record(decision_record)
            except Exception as exc:
                _log.warning("recorder.record failed", exc_info=True)
                message = _issue_message("recorder.record failed", exc)
                _append_error(
                    state,
                    message,
                    kind="record_error",
                    stage="decision.record",
                    exc=exc,
                )
                decision_record.errors.append(message)

        if record_trace:
            self._record_decision_trace(request, response, state, decision_record)

    def _record_decision_trace(
        self,
        request: ActionRequest,
        response: ActionResponse,
        state: dict,
        decision_record: Any,
    ) -> None:
        if self.trace_recorder is not None:
            try:
                self.trace_recorder.record(_trace_context(request, response, state, decision_record, self.role.value))
            except Exception as exc:
                _log.warning("trace_recorder.record failed", exc_info=True)
                message = _issue_message("trace_recorder.record failed", exc)
                _append_error(
                    state,
                    message,
                    kind="trace_error",
                    stage="trace.record",
                    exc=exc,
                )
                decision_record.errors.append(message)


# ---------------------------------------------------------------------------
# Runtime helpers
# ---------------------------------------------------------------------------

def _request_from_state(state: dict) -> ActionRequest:
    raw = state.get("request", {})
    action_type = raw.get("action_type", ActionType.SPEAK)
    phase = raw.get("phase", Phase.DAY_SPEECH)
    return ActionRequest(
        player_id=int(raw.get("player_id", state.get("player_id", 0))),
        action_type=action_type if isinstance(action_type, ActionType) else ActionType(action_type),
        phase=phase if isinstance(phase, Phase) else Phase(phase),
        observation=raw.get("observation"),
        candidates=tuple(raw.get("candidates", ())),
        retry_count=int(raw.get("retry_count", 0) or 0),
        metadata=dict(raw.get("metadata", {}) or {}),
    )


def _normalize_agent_runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    """Normalize opt-in fast-smoke agent controls.

    Defaults keep normal games unchanged. ``agent_fast_smoke`` enables a
    conservative preset that reduces LLM calls and prompt size for connectivity
    smoke tests only.
    """
    raw = dict(config or {})
    fast_smoke = _config_bool(
        raw,
        "agent_fast_smoke",
        env_name="WEREWOLF_AGENT_FAST_SMOKE",
        default=False,
    )
    normalized: dict[str, Any] = {"agent_fast_smoke": fast_smoke}

    skip_enabled = _config_bool(
        raw,
        "agent_policy_skip_llm_enabled",
        env_name="WEREWOLF_AGENT_POLICY_SKIP_LLM_ENABLED",
        default=fast_smoke,
    )
    preset = str(
        raw.get("agent_policy_skip_llm_preset")
        or os.environ.get("WEREWOLF_AGENT_POLICY_SKIP_LLM_PRESET")
        or ("smoke_fast" if fast_smoke else "")
    ).strip()
    skip_actions = _action_set(
        raw.get("agent_policy_skip_llm_actions")
        or os.environ.get("WEREWOLF_AGENT_POLICY_SKIP_LLM_ACTIONS")
    )
    if not skip_actions and (preset == "smoke_fast" or fast_smoke):
        skip_actions = set(_SMOKE_FAST_POLICY_SKIP_ACTIONS)
    normalized.update({
        "agent_policy_skip_llm_enabled": skip_enabled,
        "agent_policy_skip_llm_preset": preset,
        "agent_policy_skip_llm_actions": sorted(skip_actions),
    })

    compression_default = False if fast_smoke else True
    normalized["agent_memory_compression_enabled"] = _config_bool(
        raw,
        "agent_memory_compression_enabled",
        env_name="WEREWOLF_AGENT_MEMORY_COMPRESSION_ENABLED",
        default=compression_default,
    )

    prompt_max_total = _config_int(
        raw,
        "agent_prompt_max_total_chars",
        env_name="WEREWOLF_AGENT_PROMPT_MAX_TOTAL_CHARS",
        default=9000 if fast_smoke else None,
    )
    prompt_max_message = _config_int(
        raw,
        "agent_prompt_max_message_chars",
        env_name="WEREWOLF_AGENT_PROMPT_MAX_MESSAGE_CHARS",
        default=3500 if fast_smoke else None,
    )
    prompt_min_message = _config_int(
        raw,
        "agent_prompt_min_message_chars",
        env_name="WEREWOLF_AGENT_PROMPT_MIN_MESSAGE_CHARS",
        default=300 if fast_smoke else None,
    )
    if prompt_max_total is not None:
        normalized["agent_prompt_max_total_chars"] = prompt_max_total
    if prompt_max_message is not None:
        normalized["agent_prompt_max_message_chars"] = prompt_max_message
    if prompt_min_message is not None:
        normalized["agent_prompt_min_message_chars"] = prompt_min_message
    memory_recent = _config_int(
        raw,
        "agent_memory_recent_closed_segments",
        env_name="WEREWOLF_AGENT_MEMORY_RECENT_CLOSED_SEGMENTS",
        default=1 if fast_smoke else None,
    )
    memory_max_events = _config_int(
        raw,
        "agent_memory_max_events_per_segment",
        env_name="WEREWOLF_AGENT_MEMORY_MAX_EVENTS_PER_SEGMENT",
        default=12 if fast_smoke else None,
    )
    memory_event_chars = _config_int(
        raw,
        "agent_memory_event_max_chars",
        env_name="WEREWOLF_AGENT_MEMORY_EVENT_MAX_CHARS",
        default=180 if fast_smoke else None,
    )
    if memory_recent is not None:
        normalized["agent_memory_recent_closed_segments"] = memory_recent
    if memory_max_events is not None:
        normalized["agent_memory_max_events_per_segment"] = memory_max_events
    if memory_event_chars is not None:
        normalized["agent_memory_event_max_chars"] = memory_event_chars
    return normalized


def _should_policy_skip_llm(request: ActionRequest, config: dict[str, Any]) -> bool:
    if not _as_bool(config.get("agent_policy_skip_llm_enabled"), default=False):
        return False
    if request.action_type.value in _POLICY_SKIP_PROTECTED_ACTIONS:
        return False
    actions = _action_set(config.get("agent_policy_skip_llm_actions"))
    return request.action_type.value in actions


def _trim_memory_context_for_agent_config(state: dict) -> None:
    context = state.get("memory_context")
    if not isinstance(context, dict):
        return
    recent_limit = _positive_int_or_none(state.get("agent_memory_recent_closed_segments"))
    event_limit = _positive_int_or_none(state.get("agent_memory_max_events_per_segment"))
    event_chars = _positive_int_or_none(state.get("agent_memory_event_max_chars"))
    if recent_limit is None and event_limit is None and event_chars is None:
        return

    recent = context.get("recent_closed_segments")
    if isinstance(recent, list):
        trimmed_recent = recent[-recent_limit:] if recent_limit is not None else list(recent)
        context["recent_closed_segments"] = [
            _trim_segment_prompt_dict(segment, event_limit=event_limit, event_chars=event_chars)
            for segment in trimmed_recent
        ]

    open_segment = context.get("open_segment")
    if isinstance(open_segment, list):
        context["open_segment"] = _trim_event_list(
            open_segment,
            event_limit=event_limit,
            event_chars=event_chars,
        )


def _trim_segment_prompt_dict(
    segment: Any,
    *,
    event_limit: int | None,
    event_chars: int | None,
) -> Any:
    if not isinstance(segment, dict):
        return segment
    row = dict(segment)
    events = row.get("events")
    if isinstance(events, list):
        row["events"] = _trim_event_list(events, event_limit=event_limit, event_chars=event_chars)
    return row


def _trim_event_list(
    events: list[Any],
    *,
    event_limit: int | None,
    event_chars: int | None,
) -> list[Any]:
    selected = events[-event_limit:] if event_limit is not None else list(events)
    if event_chars is None:
        return selected
    return [_trim_event_prompt_dict(event, event_chars=event_chars) for event in selected]


def _trim_event_prompt_dict(event: Any, *, event_chars: int) -> Any:
    if not isinstance(event, dict):
        text = str(event)
        return text if len(text) <= event_chars else text[:event_chars] + "..."
    row = dict(event)
    for key in ("text", "content", "message"):
        value = row.get(key)
        if isinstance(value, str) and len(value) > event_chars:
            row[key] = value[:event_chars] + "..."
    return row


def _prompt_budget_from_config(config: dict[str, Any]) -> PromptBudget | None:
    total = _positive_int_or_none(config.get("agent_prompt_max_total_chars"))
    message = _positive_int_or_none(config.get("agent_prompt_max_message_chars"))
    minimum = _positive_int_or_none(config.get("agent_prompt_min_message_chars"))
    if total is None and message is None and minimum is None:
        return None
    return PromptBudget(
        max_total_chars=total if total is not None else 24000,
        max_message_chars=message if message is not None else 8000,
        min_message_chars=minimum if minimum is not None else 400,
    )


def _model_call_extra(request: ActionRequest, *, elapsed_ms: int) -> dict[str, Any]:
    return {
        "player_id": request.player_id,
        "action_type": request.action_type.value,
        "phase": request.phase.value,
        "retry_count": request.retry_count,
        "candidate_count": len(request.candidates),
        "elapsed_ms": elapsed_ms,
    }


def _decision_langfuse_metadata(state: dict, request: ActionRequest) -> dict[str, Any]:
    """Business dimensions for per-decision Langfuse generation observations."""
    current = state.get("memory_context", {}).get("current_visible_state", {})
    day = getattr(request.observation, "day", None)
    if day is None and isinstance(current, dict):
        day = current.get("day")

    selected_skills = [str(skill) for skill in state.get("selected_skills", []) if skill is not None]
    metadata: dict[str, Any] = {
        "game_id": state.get("game_id"),
        "source_run_id": state.get("source_run_id"),
        "player_id": request.player_id,
        "role": state.get("role"),
        "action_type": request.action_type.value,
        "phase": request.phase.value,
        "day": _int_or_default(day, 0),
        "candidate_count": len(request.candidates),
        "retry_count": request.retry_count,
        "selected_skills": selected_skills,
        "skill_count": len(selected_skills),
        "source": state.get("source") or "llm",
    }
    return {key: value for key, value in metadata.items() if value is not None}


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _config_bool(
    config: dict[str, Any],
    key: str,
    *,
    env_name: str,
    default: bool,
) -> bool:
    value = config.get(key)
    if value is None:
        value = os.environ.get(env_name)
    return _as_bool(value, default=default)


def _config_int(
    config: dict[str, Any],
    key: str,
    *,
    env_name: str,
    default: int | None,
) -> int | None:
    value = config.get(key)
    if value is None:
        value = os.environ.get(env_name)
    if value is None:
        return default
    parsed = _positive_int_or_none(value)
    return parsed if parsed is not None else default


def _as_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on", "enabled"}:
        return True
    if text in {"0", "false", "no", "n", "off", "disabled"}:
        return False
    return default


def _positive_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _action_set(value: Any) -> set[str]:
    if value is None or value == "":
        return set()
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",")]
    elif isinstance(value, (list, tuple, set, frozenset)):
        raw_items = [str(item).strip() for item in value]
    else:
        raw_items = [str(value).strip()]
    return {item for item in raw_items if item}


def _empty_memory_context(request: ActionRequest, role: str) -> dict[str, Any]:
    return {
        "current_visible_state": {
            "player_id": request.player_id,
            "role": role,
            "day": 0,
            "phase": request.phase.value,
            "alive_players": [],
            "dead_players": [],
            "sheriff_id": None,
            "candidates": list(request.candidates),
        },
        "private_facts": {
            "known_roles": {},
            "seer_checks": {},
            "metadata": dict(request.metadata),
        },
        "open_segment": [],
        "open_segment_key": None,
        "recent_closed_segments": [],
        "compressed_segment_summaries": [],
        "compression_state": {"failed_segments": [], "retry_counts": {}},
        "errors": [],
    }


_SPEECH_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.SPEAK,
    ActionType.SHERIFF_SPEAK,
    ActionType.PK_SPEAK,
    ActionType.LAST_WORD,
})

_TARGET_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.SHERIFF_VOTE,
    ActionType.GUARD_PROTECT,
    ActionType.WEREWOLF_KILL,
    ActionType.SEER_CHECK,
    ActionType.EXILE_VOTE,
    ActionType.PK_VOTE,
    ActionType.HUNTER_SHOOT,
})

_REQUIRED_TARGET_ACTIONS: frozenset[ActionType] = frozenset(
    action_type for action_type in _TARGET_ACTIONS if target_required_for_action(action_type)
)

_VALID_CHOICES: dict[ActionType, set[str | None]] = {
    ActionType.SHERIFF_RUN: {"run", "pass"},
    ActionType.SHERIFF_WITHDRAW: {"stay", "withdraw"},
    ActionType.SHERIFF_BADGE: {"transfer", "destroy"},
    ActionType.SPEECH_ORDER: {"forward", "reverse"},
    ActionType.WITCH_ACT: {"save", "poison", "none"},
    ActionType.WHITE_WOLF_EXPLODE: {"pass", "explode"},
}


def _coerce_target(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _default_choice(action_type: ActionType) -> str | None:
    return {
        ActionType.SHERIFF_RUN: "pass",
        ActionType.SHERIFF_WITHDRAW: "stay",
        ActionType.SHERIFF_BADGE: "destroy",
        ActionType.SPEECH_ORDER: "forward",
        ActionType.WITCH_ACT: "none",
        ActionType.WHITE_WOLF_EXPLODE: "pass",
    }.get(action_type)


def _fallback_response(request: ActionRequest) -> ActionResponse:
    if request.action_type in _SPEECH_ACTIONS:
        return ActionResponse(
            request.action_type,
            text=f"{request.player_id}号玩家发言：先过。",
        )
    if request.action_type == ActionType.SHERIFF_RUN:
        return ActionResponse(request.action_type, choice="pass")
    if request.action_type == ActionType.SHERIFF_WITHDRAW:
        return ActionResponse(request.action_type, choice="stay")
    if request.action_type == ActionType.SHERIFF_BADGE:
        return ActionResponse(request.action_type, choice="destroy")
    if request.action_type == ActionType.SPEECH_ORDER:
        return ActionResponse(request.action_type, choice="forward")
    if request.action_type == ActionType.WITCH_ACT:
        return ActionResponse(request.action_type, choice="none")
    if request.action_type == ActionType.WHITE_WOLF_EXPLODE:
        return ActionResponse(request.action_type, choice="pass")
    if request.action_type in _REQUIRED_TARGET_ACTIONS:
        return ActionResponse(request.action_type, target=first_candidate_target(list(request.candidates)))
    if request.action_type in _TARGET_ACTIONS:
        return ActionResponse(request.action_type)
    return ActionResponse(request.action_type)


_RESPONSE_UNSET = object()


def _replace_response(
    response: ActionResponse,
    *,
    target: Any = _RESPONSE_UNSET,
    choice: Any = _RESPONSE_UNSET,
    text: Any = _RESPONSE_UNSET,
) -> ActionResponse:
    return ActionResponse(
        response.action_type,
        target=response.target if target is _RESPONSE_UNSET else target,
        choice=response.choice if choice is _RESPONSE_UNSET else choice,
        text=response.text if text is _RESPONSE_UNSET else text,
        decision_id=response.decision_id,
        on_accepted=response.on_accepted,
    )


_PLAYER_ID_PLACEHOLDER_RE = re.compile(r"\{\s*player_id\s*\}")


def _repair_public_text_placeholders(
    request: ActionRequest,
    response: ActionResponse,
    state: dict,
) -> ActionResponse:
    if not response.text or "player_id" not in response.text:
        return response

    repaired_text = _PLAYER_ID_PLACEHOLDER_RE.sub(str(request.player_id), response.text)
    if repaired_text == response.text:
        return response

    state["source"] = "policy_adjusted"
    state.setdefault("policy_adjustments", []).append(
        "Repaired unresolved player_id placeholder in public text."
    )
    return ActionResponse(
        request.action_type,
        target=response.target,
        choice=response.choice,
        text=repaired_text,
        decision_id=response.decision_id,
    )


def _repair_or_fallback(request: ActionRequest, response: ActionResponse, state: dict) -> ActionResponse:
    adjustments: list[str] = []

    valid_choices = _VALID_CHOICES.get(request.action_type)
    if valid_choices is not None and response.choice not in valid_choices:
        old_choice = response.choice
        response = _replace_response(response, choice=_default_choice(request.action_type))
        adjustments.append(
            f"Invalid choice {old_choice!r} for {request.action_type.value}; "
            f"repaired to {response.choice!r}."
        )

    if request.action_type == ActionType.WITCH_ACT:
        response = _repair_witch_response(request, response, adjustments)
    elif request.action_type == ActionType.SHERIFF_BADGE:
        response = _repair_sheriff_badge_response(request, response, adjustments)
    elif request.action_type == ActionType.WHITE_WOLF_EXPLODE:
        response = _repair_white_wolf_explode_response(request, response, adjustments)
    elif request.action_type == ActionType.SHERIFF_WITHDRAW:
        response = _repair_sheriff_withdraw_response(request, response, adjustments)
    else:
        response = _repair_target_response(request, response, adjustments)

    if adjustments:
        state["source"] = "policy_adjusted"
        state.setdefault("policy_adjustments", []).extend(adjustments)
    return response


def _repair_witch_response(
    request: ActionRequest,
    response: ActionResponse,
    adjustments: list[str],
) -> ActionResponse:
    if response.choice == "save":
        if not request.metadata.get("can_save", False):
            adjustments.append("save not available this round; falling back.")
            return _fallback_response(request)
        if response.target is not None:
            adjustments.append("save does not accept an explicit target; cleared target.")
            return _replace_response(response, target=None)
        return response

    if response.choice == "poison":
        if not request.metadata.get("can_poison", False):
            adjustments.append("poison unavailable; falling back.")
            return _fallback_response(request)
        if not target_in_candidates(response.target, request.candidates):
            if response.target is None:
                adjustments.append("poison requires a valid target; falling back.")
            else:
                adjustments.append(f"poison target {response.target} not in candidates; falling back.")
            return _fallback_response(request)
        return response

    if response.target is not None:
        adjustments.append("witch non-poison choice cannot include a target; cleared target.")
        return _replace_response(response, target=None)
    return response


def _repair_sheriff_badge_response(
    request: ActionRequest,
    response: ActionResponse,
    adjustments: list[str],
) -> ActionResponse:
    if response.choice == "transfer":
        if target_in_candidates(response.target, request.candidates):
            return response
        if response.target is None:
            adjustments.append("transfer requires a valid target; repaired to destroy.")
        else:
            adjustments.append(f"transfer target {response.target} not in candidates; repaired to destroy.")
        return _replace_response(response, target=None, choice="destroy")

    if response.target is not None:
        adjustments.append("destroy cannot include a transfer target; cleared target.")
        return _replace_response(response, target=None)
    return response


def _repair_white_wolf_explode_response(
    request: ActionRequest,
    response: ActionResponse,
    adjustments: list[str],
) -> ActionResponse:
    if response.choice == "explode":
        if target_in_candidates(response.target, request.candidates):
            return response
        if response.target is None:
            adjustments.append("explode requires a valid target; repaired to pass.")
        else:
            adjustments.append(f"explode target {response.target} not in candidates; repaired to pass.")
        return _replace_response(response, target=None, choice="pass")

    if response.target is not None:
        adjustments.append("pass cannot include an explode target; cleared target.")
        return _replace_response(response, target=None, choice="pass")
    return response


def _repair_sheriff_withdraw_response(
    request: ActionRequest,
    response: ActionResponse,
    adjustments: list[str],
) -> ActionResponse:
    if response.target is not None:
        response = _replace_response(response, target=None)
        adjustments.append("sheriff withdraw does not accept a target; cleared target.")

    if response.choice == "withdraw":
        remaining = request.metadata.get("remaining_runners") or request.metadata.get("runners")
        if remaining is None:
            remaining = list(request.candidates)
        if remaining == [request.player_id]:
            response = _replace_response(response, choice="stay")
            adjustments.append("Last sheriff runner attempted to withdraw; forced stay.")
    return response


def _repair_target_response(
    request: ActionRequest,
    response: ActionResponse,
    adjustments: list[str],
) -> ActionResponse:
    if request.action_type in _REQUIRED_TARGET_ACTIONS and not target_in_candidates(response.target, request.candidates):
        repair_target = first_candidate_target(list(request.candidates))
        if repair_target is not None:
            old_target = response.target
            response = _replace_response(response, target=repair_target)
            if old_target is None:
                adjustments.append(f"required target missing; repaired to candidate {repair_target}.")
            else:
                adjustments.append(
                    f"target not in candidates; repaired invalid target {old_target} "
                    f"to candidate {repair_target}."
                )
            return response
        if response.target is not None:
            old_target = response.target
            response = _replace_response(response, target=None)
            adjustments.append(
                f"required target {old_target} invalid but no legal candidate available; "
                "cleared target for engine safety net."
            )
        return response

    if response.target is not None and not target_in_candidates(response.target, request.candidates):
        old_target = response.target
        response = _replace_response(response, target=None)
        adjustments.append(f"target not in candidates; cleared invalid target {old_target}.")
    return response


def _response_to_dict(response: ActionResponse) -> dict[str, Any]:
    return {
        "action_type": response.action_type.value,
        "text": response.text,
        "target": response.target,
        "choice": response.choice,
        "decision_id": response.decision_id,
    }


def _state_response(request: ActionRequest, state: dict) -> ActionResponse | None:
    response = state.get("response")
    if response is None:
        return None
    if isinstance(response, ActionResponse):
        return response
    return ActionResponse(
        request.action_type,
        text=str(response.get("text", "")),
        target=_coerce_target(response.get("target")),
        choice=response.get("choice"),
        decision_id=response.get("decision_id"),
    )


def _build_decision_record(
    request: ActionRequest,
    response: ActionResponse,
    state: dict,
    role: str,
) -> Any:
    from app.lib.store import DecisionRecord

    parsed = state.get("parsed_decision") or {}
    memory_context = state.get("memory_context") or {}
    memory_summary = [
        str(item.get("summary", ""))
        for item in memory_context.get("compressed_segment_summaries", [])
        if isinstance(item, dict) and item.get("summary")
    ]
    observation = request.observation
    return DecisionRecord(
        action_type=request.action_type,
        day=getattr(observation, "day", 0),
        phase=request.phase.value,
        player_id=request.player_id,
        role=role,
        candidates=list(request.candidates),
        selected_target=response.target,
        selected_choice=response.choice,
        public_text=response.text,
        private_reasoning=str(parsed.get("private_reasoning", "")),
        confidence=float(state.get("confidence", 0.0) or 0.0),
        alternatives=list(parsed.get("alternatives", [])),
        rejected_reasons=[str(r) for r in parsed.get("rejected_reasons", []) if r is not None],
        selected_skills=list(state.get("selected_skills", [])),
        memory_summary=memory_summary,
        raw_output=str(state.get("raw_output", "")),
        errors=list(state.get("errors", [])),
        policy_adjustments=list(state.get("policy_adjustments", [])),
        source=state.get("source", "llm"),
    )


def _trace_context(
    request: ActionRequest,
    response: ActionResponse,
    state: dict,
    decision_record: Any,
    role: str,
) -> SimpleNamespace:
    return SimpleNamespace(
        request=request,
        player_id=request.player_id,
        role=role,
        memory_context=state.get("memory_context", {}),
        selected_skills=list(state.get("selected_skills", [])),
        messages=list(state.get("messages", [])),
        raw_output=state.get("raw_output", ""),
        parsed_decision=state.get("parsed_decision", {}),
        confidence=state.get("confidence", 0.0),
        response=response,
        decision_record=decision_record,
        source=state.get("source", "llm"),
        llm_error=state.get("llm_error", ""),
        policy_adjustments=list(state.get("policy_adjustments", [])),
        errors=list(state.get("errors", [])),
        diagnostics=list(state.get("diagnostics", [])),
    )
