from __future__ import annotations

from agent.infrastructure.tracing import observe

from agent.core.memory import AgentMemory
from agent.core.context import AgentContext


@observe(name="remember_step")
def remember_step(ctx: AgentContext, memory: AgentMemory) -> AgentContext:
    """Update short-term memory from the current observation and build
    a memory summary for prompt injection.
    """
    ctx.memory_context = memory.build_context(ctx.request)
    return ctx
