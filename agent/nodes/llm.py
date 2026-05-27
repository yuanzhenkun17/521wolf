from __future__ import annotations

from langfuse import observe
from agent.runtime.context import AgentContext
from agent.runtime.model import ModelAdapter


@observe(name="llm_node")
async def llm_node(ctx: AgentContext, model: ModelAdapter) -> AgentContext:
    """Call the LLM with the prepared messages and capture the raw output."""
    try:
        ctx.raw_output = await model.complete(ctx.messages, name=f"llm_node/{ctx.player_id}/{ctx.request.action_type.value}")
    except Exception as exc:
        ctx.errors.append(f"LLM call failed: {exc}")
        ctx.raw_output = ""
    return ctx
