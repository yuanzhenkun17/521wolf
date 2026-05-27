from __future__ import annotations

from langfuse import observe
from agent.observability.decision_log import AgentDecisionRecorder, DecisionRecord
from agent.runtime.context import AgentContext


@observe(name="log_node")
def log_node(ctx: AgentContext, recorder: AgentDecisionRecorder | None = None) -> AgentContext:
    """Build a complete DecisionRecord and store it in the context."""
    pd = ctx.parsed_decision

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
        private_reasoning=str(pd.get("private_reasoning", "")),
        confidence=ctx.confidence,
        alternatives=list(pd.get("alternatives", [])),
        rejected_reasons=[
            str(r) for r in pd.get("rejected_reasons", []) if r is not None
        ],
        selected_skill=", ".join(ctx.selected_skills),
        memory_refs=list(pd.get("memory_refs", [])),
        belief_snapshot=ctx.belief_context,
        memory_summary=ctx.memory_context.get("memory_events", [])[-6:],
        raw_output=ctx.raw_output,
        errors=list(ctx.errors),
        policy_adjustments=list(ctx.policy_adjustments),
        source=ctx.source,
    )

    if recorder is not None:
        recorder.record(decision)

    ctx.decision_record = decision
    return ctx
