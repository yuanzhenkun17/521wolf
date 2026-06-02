from __future__ import annotations

from agent.infrastructure.tracing import observe
from agent.core.belief import BeliefState
from agent.core.memory import AgentMemory
from agent.core.context import AgentContext


@observe(name="update_belief_step")
def update_belief_step(ctx: AgentContext, belief: BeliefState, memory: AgentMemory) -> AgentContext:
    """Update belief state from observation + memory, then produce a belief
    summary for the prompt.
    """
    ctx.belief_context = belief.build_context(ctx.request, memory)
    return ctx
