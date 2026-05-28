from __future__ import annotations

from langfuse import observe

from agent.cognition.memory import AgentMemory
from agent.runtime.context import AgentContext


@observe(name="memory_node")
def memory_node(ctx: AgentContext, memory: AgentMemory) -> AgentContext:
    """Update short-term memory from the current observation and build
    a memory summary for prompt injection.
    """
    ctx.memory_context = memory.build_context(ctx.request)
    return ctx
