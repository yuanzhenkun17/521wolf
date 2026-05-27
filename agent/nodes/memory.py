from __future__ import annotations

from langfuse import observe
from engine.models import Role

from agent.cognition.long_memory import long_memory_prompt_hints
from agent.cognition.memory import AgentMemory
from agent.runtime.context import AgentContext


@observe(name="memory_node")
def memory_node(ctx: AgentContext, memory: AgentMemory) -> AgentContext:
    """Update short-term memory from the current observation and build
    a memory summary for prompt injection.
    """
    ctx.memory_context = memory.build_context(ctx.request)
    ctx.memory_context["long_memory_hints"] = long_memory_prompt_hints(
        _role_from_context(ctx),
        action_type=ctx.request.action_type.value,
    )
    return ctx


def _role_from_context(ctx: AgentContext) -> Role | str:
    try:
        return Role(ctx.role)
    except ValueError:
        return ctx.role
