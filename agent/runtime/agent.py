"""Agent — ``AgentRuntime`` (decision pipeline) and ``LLMPlayerAgent`` (rule-layer adapter).

Receives ``ActionRequest`` from the game engine, chains nodes
(observe -> memory -> belief -> skill_router -> prompt -> llm -> parse -> policy -> log),
and returns ``ActionResponse``.

Key responsibilities:
- Node orchestration: each node reads from / writes to ``AgentContext``.
- ToT integration: for key actions, the reasoning node generates multiple
  candidates and a judge selects the best one, bypassing the normal LLM call.
- GoT integration: for high-conflict key actions, the reasoning node builds
  an evidence/hypothesis graph before selecting the final action.
- Decision recording: writes ``DecisionRecord`` entries to the shared recorder.
- Trace recording: if a ``trace_recorder`` is attached, every decision context
  is archived for post-game analysis.

``LLMPlayerAgent`` wraps the runtime as a rule-layer ``PlayerAgent`` so it
drops into any existing game without rule-layer changes.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path

from langfuse import observe, propagate_attributes
from engine.models import ActionRequest, ActionResponse, Role

from agent.cognition.belief import BeliefState
from agent.cognition.memory import AgentMemory
from agent.observability.archive import AgentTraceRecorder
from agent.observability.decision_log import AgentDecisionRecorder
from agent.runtime.context import AgentContext
from agent.runtime.model import ModelAdapter
from agent.nodes.memory import memory_node
from agent.nodes.belief import belief_node
from agent.nodes.skill_router import skill_router_node
from agent.nodes.prompt import prompt_node
from agent.nodes.llm import llm_node
from agent.nodes.parse import parse_node
from agent.nodes.policy import policy_node
from agent.nodes.log import log_node
from agent.nodes.got import got_node
from agent.nodes.tot import tot_node

_log = logging.getLogger(__name__)


class AgentRuntime:
    """Graph-like runtime that chains decision nodes.

    Pipeline::

        ActionRequest
        -> memory_node
        -> belief_node
        -> skill_router_node
        -> prompt_node
        -> llm_node        (async)
        -> parse_node
        -> policy_node
        -> log_node
        -> ActionResponse
    """

    def __init__(
        self,
        *,
        player_id: int,
        role: Role,
        model: ModelAdapter,
        memory: AgentMemory | None = None,
        belief: BeliefState | None = None,
        recorder: AgentDecisionRecorder | None = None,
        trace_recorder: AgentTraceRecorder | None = None,
        game_id: str | None = None,
        skill_dir: Path | str | None = None,
        tot_enabled: bool = True,
        got_enabled: bool = True,
        got_trigger_threshold: float = 0.3,
    ) -> None:
        self.player_id = player_id
        self.role = role
        self.model = model
        self.game_id = game_id
        self.memory = memory or AgentMemory(player_id=player_id, role=role)
        self.belief = belief or BeliefState(player_id=player_id, role=role)
        self.recorder = recorder
        self.trace_recorder = trace_recorder
        self.skill_dir = Path(skill_dir) if skill_dir else None
        self.tot_enabled = tot_enabled
        self.got_enabled = got_enabled
        self.got_trigger_threshold = got_trigger_threshold

    @observe(name="act")
    async def act(self, request: ActionRequest) -> ActionResponse:
        ctx = AgentContext(
            request=request,
            player_id=self.player_id,
            role=self.role.value,
        )

        with propagate_attributes(session_id=self.game_id) if self.game_id else nullcontext():
            try:
                # -- synchronous nodes -------------------------------------------------
                ctx = memory_node(ctx, self.memory)
                ctx = belief_node(ctx, self.belief, self.memory)

                # -- skill routing + prompt assembly ---------------------------------
                ctx = skill_router_node(ctx, skill_root=self.skill_dir)
                ctx = prompt_node(ctx)

                # -- GoT/ToT reasoning for key actions --------------------------------
                if self.got_enabled:
                    ctx = await got_node(ctx, self.model, threshold=self.got_trigger_threshold)
                if self.tot_enabled and ctx.source != "got":
                    ctx = await tot_node(ctx, self.model)

                # -- async LLM call (skipped when GoT/ToT succeeded) ------------------
                if ctx.source in {"got", "tot"}:
                    ctx = parse_node(ctx)
                else:
                    ctx = await llm_node(ctx, self.model)
                    ctx = parse_node(ctx)
                ctx = policy_node(ctx)
                ctx = log_node(ctx, self.recorder)
                if ctx.response is not None and ctx.decision_record is not None:
                    ctx.response.decision_id = ctx.decision_record.decision_id
            finally:
                # -- optional trace recording for archive ------------------------------
                try:
                    if self.trace_recorder:
                        self.trace_recorder.record(ctx)
                except Exception:
                    _log.warning("trace_recorder.record failed", exc_info=True)

                # -- write decision record back to memory ------------------------------
                try:
                    if ctx.response is not None:
                        self.memory.remember_action(request, ctx.response, ctx.decision_record)
                except Exception:
                    _log.warning("remember_action failed in finally", exc_info=True)

        if ctx.response is None:
            raise RuntimeError("Pipeline produced no response")
        return ctx.response


class LLMPlayerAgent:
    """Werewolf player agent backed by the node-based runtime.

    Implements the rule-layer ``PlayerAgent`` protocol.
    """

    def __init__(
        self,
        *,
        player_id: int,
        role: Role,
        client: ModelAdapter,
        decision_recorder: AgentDecisionRecorder | None = None,
        trace_recorder: AgentTraceRecorder | None = None,
        game_id: str | None = None,
        skill_dir: Path | str | None = None,
        tot_enabled: bool = True,
        got_enabled: bool = True,
        got_trigger_threshold: float = 0.3,
    ) -> None:
        self.player_id = player_id
        self.role = role
        self.runtime = AgentRuntime(
            player_id=player_id,
            role=role,
            model=client,
            recorder=decision_recorder,
            trace_recorder=trace_recorder,
            game_id=game_id,
            skill_dir=skill_dir,
            tot_enabled=tot_enabled,
            got_enabled=got_enabled,
            got_trigger_threshold=got_trigger_threshold,
        )

    @property
    def memory(self) -> AgentMemory:
        return self.runtime.memory

    @property
    def belief(self) -> BeliefState:
        return self.runtime.belief

    async def act(self, request: ActionRequest) -> ActionResponse:
        return await self.runtime.act(request)
