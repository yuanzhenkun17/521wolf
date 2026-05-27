from __future__ import annotations

from langfuse import observe
from agent.cognition.belief import BeliefState
from agent.cognition.memory import AgentMemory
from agent.runtime.context import AgentContext


@observe(name="belief_node")
def belief_node(ctx: AgentContext, belief: BeliefState, memory: AgentMemory) -> AgentContext:
    """Update belief state from observation + memory, then produce a belief
    summary for the prompt.
    """
    ctx.belief_context = belief.build_context(ctx.request, memory)
    return ctx
