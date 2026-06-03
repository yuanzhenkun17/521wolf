"""Agent runtime and rule-layer adapter.

``AgentRuntime`` receives ``ActionRequest`` from the game engine, runs the
decision pipeline, and returns ``ActionResponse``. It implements the
rule-layer ``PlayerAgent`` protocol directly.

Key responsibilities:
- Step orchestration: each step reads from / writes to ``AgentContext``.
- Decision recording: writes ``DecisionRecord`` entries to the shared recorder.
- Trace recording: if a ``trace_recorder`` is attached, every decision context
  is archived for post-game analysis.
"""

from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path

from engine.models import ActionRequest, ActionResponse, Role

from agent.core.memory import AgentMemory
from agent.infrastructure.archive import AgentTraceRecorder
from agent.infrastructure.decision_log import AgentDecisionRecorder, DecisionRecord
from agent.infrastructure.tracing import observe, propagate_attributes
from agent.core.context import AgentContext
from agent.infrastructure.llm import ModelAdapter
from agent.decision.steps.remember import remember_step
from agent.decision.steps.select_skills import select_skills_step
from agent.decision.steps.build_prompt import build_prompt_step
from agent.decision.steps.call_model import call_model_step
from agent.decision.steps.parse_output import parse_output_step
from agent.decision.steps.enforce_policy import enforce_policy_step

_log = logging.getLogger(__name__)


class AgentRuntime:
    """Step-based runtime that chains the decision pipeline.

    Pipeline::

        ActionRequest
        -> remember_step
        -> select_skills_step
        -> build_prompt_step
        -> call_model_step
        -> parse_output_step
        -> enforce_policy_step
        -> ActionResponse
    """

    def __init__(
        self,
        *,
        player_id: int,
        role: Role,
        model: ModelAdapter,
        memory: AgentMemory | None = None,
        recorder: AgentDecisionRecorder | None = None,
        trace_recorder: AgentTraceRecorder | None = None,
        game_id: str | None = None,
        skill_dir: Path | str | None = None,
    ) -> None:
        self.player_id = player_id
        self.role = role
        self.model = model
        self.game_id = game_id
        self.memory = memory or AgentMemory(player_id=player_id, role=role)
        self.recorder = recorder
        self.trace_recorder = trace_recorder
        self.skill_dir = Path(skill_dir) if skill_dir else None

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

                # -- skill routing + prompt assembly ---------------------------------
                ctx = select_skills_step(ctx, skill_root=self.skill_dir)
                ctx = build_prompt_step(ctx)

                # -- LLM call + parse ------------------------------------------------
                ctx = await call_model_step(ctx, self.model)
                ctx = parse_output_step(ctx)
                ctx = enforce_policy_step(ctx)

                # -- decision record --------------------------------------------------
                ctx.decision_record = _build_decision_record(ctx)
                if self.recorder is not None:
                    self.recorder.record(ctx.decision_record)
                if ctx.response is not None:
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



# -- helpers -------------------------------------------------------------------

def _build_decision_record(ctx: AgentContext) -> DecisionRecord:
    """Build a DecisionRecord from the current context after pipeline steps."""
    parsed = ctx.parsed_decision
    return DecisionRecord(
        action_type=ctx.request.action_type,
        day=ctx.request.observation.day,
        phase=ctx.request.phase.value,
        player_id=ctx.player_id,
        role=ctx.role,
        candidates=list(ctx.request.candidates),
        selected_target=ctx.response.target if ctx.response else None,
        selected_choice=ctx.response.choice if ctx.response else None,
        public_text=ctx.response.text if ctx.response else "",
        private_reasoning=str(parsed.get("private_reasoning", "")),
        confidence=ctx.confidence,
        alternatives=list(parsed.get("alternatives", [])),
        rejected_reasons=[
            str(r) for r in parsed.get("rejected_reasons", []) if r is not None
        ],
        selected_skills=list(ctx.selected_skills),
        memory_summary=ctx.memory_context.get("rolling_summary", [])[-6:],
        raw_output=ctx.raw_output,
        errors=list(ctx.errors),
        policy_adjustments=list(ctx.policy_adjustments),
        source=ctx.source,
    )

