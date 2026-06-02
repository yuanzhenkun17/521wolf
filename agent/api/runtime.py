"""Agent runtime and rule-layer adapter.

``AgentRuntime`` receives ``ActionRequest`` from the game engine, runs the
decision pipeline, and returns ``ActionResponse``. ``LLMPlayerAgent`` wraps the
runtime behind the rule-layer player protocol.

Key responsibilities:
- Step orchestration: each step reads from / writes to ``AgentContext``.
- ToT integration: for key actions, the reasoning step generates multiple
  candidates and a judge selects the best one, bypassing the normal LLM call.
- GoT integration: for high-conflict key actions, the reasoning step builds
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

from engine.models import ActionRequest, ActionResponse, Role

from agent.core.belief import BeliefState
from agent.core.memory import AgentMemory
from agent.infrastructure.archive import AgentTraceRecorder
from agent.infrastructure.decision_log import AgentDecisionRecorder
from agent.infrastructure.tracing import observe, propagate_attributes
from agent.core.context import AgentContext
from agent.infrastructure.llm import ModelAdapter
from agent.decision.steps.remember import remember_step
from agent.decision.steps.update_belief import update_belief_step
from agent.decision.steps.select_skills import select_skills_step
from agent.decision.steps.build_prompt import build_prompt_step
from agent.decision.steps.call_model import call_model_step
from agent.decision.steps.parse_output import parse_output_step
from agent.decision.steps.enforce_policy import enforce_policy_step
from agent.decision.steps.record_decision import record_decision_step
from agent.decision.steps.reason_with_graph import reason_with_graph_step
from agent.decision.steps.reason_with_tree import reason_with_tree_step

_log = logging.getLogger(__name__)


class AgentRuntime:
    """Graph-like runtime that chains decision steps.

    Pipeline::

        ActionRequest
        -> remember_step
        -> update_belief_step
        -> select_skills_step
        -> build_prompt_step
        -> reason_with_graph_step (async, optional)
        -> reason_with_tree_step  (async, optional)
        -> call_model_step        (async, skipped when GoT/ToT succeeds)
        -> parse_output_step
        -> enforce_policy_step
        -> record_decision_step
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
                # -- synchronous steps -------------------------------------------------
                ctx = remember_step(ctx, self.memory)
                ctx = update_belief_step(ctx, self.belief, self.memory)

                # -- skill routing + prompt assembly ---------------------------------
                ctx = select_skills_step(ctx, skill_root=self.skill_dir)
                ctx = build_prompt_step(ctx)

                # -- GoT/ToT reasoning for key actions --------------------------------
                if self.got_enabled:
                    ctx = await reason_with_graph_step(ctx, self.model, threshold=self.got_trigger_threshold)
                if self.tot_enabled and ctx.source != "got":
                    ctx = await reason_with_tree_step(ctx, self.model)

                # -- async LLM call (skipped when GoT/ToT succeeded) ------------------
                if ctx.source in {"got", "tot"}:
                    ctx = parse_output_step(ctx)
                else:
                    ctx = await call_model_step(ctx, self.model)
                    ctx = parse_output_step(ctx)
                ctx = enforce_policy_step(ctx)
                ctx = record_decision_step(ctx, self.recorder)
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
    """Werewolf player agent backed by the step-based runtime.

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
