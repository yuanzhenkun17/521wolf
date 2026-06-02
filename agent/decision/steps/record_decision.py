from __future__ import annotations

import logging

from agent.infrastructure.tracing import observe

from agent.infrastructure.decision_log import AgentDecisionRecorder, DecisionRecord
from agent.core.context import AgentContext

_log = logging.getLogger(__name__)


@observe(name="record_decision_step")
def record_decision_step(ctx: AgentContext, recorder: AgentDecisionRecorder | None = None) -> AgentContext:
    """Create and optionally persist the decision record for one action."""
    parsed = ctx.parsed_decision

    decision = DecisionRecord(
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
            str(reason) for reason in parsed.get("rejected_reasons", []) if reason is not None
        ],
        selected_skills=list(ctx.selected_skills),
        memory_refs=list(parsed.get("memory_refs", [])),
        belief_snapshot=ctx.belief_context,
        memory_summary=ctx.memory_context.get("memory_events", [])[-6:],
        raw_output=ctx.raw_output,
        errors=list(ctx.errors),
        policy_adjustments=list(ctx.policy_adjustments),
        source=ctx.source,
    )

    ctx.decision_record = decision

    if recorder is not None:
        try:
            recorder.record(decision)
        except Exception:
            _log.warning("decision recorder failed", exc_info=True)

    return ctx
