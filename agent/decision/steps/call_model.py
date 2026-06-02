from __future__ import annotations

from agent.infrastructure.tracing import observe
from agent.core.context import AgentContext
from agent.infrastructure.llm import ModelAdapter


@observe(name="call_model_step")
async def call_model_step(ctx: AgentContext, model: ModelAdapter) -> AgentContext:
    """Call the LLM with the prepared messages and capture the raw output."""
    try:
        ctx.raw_output = await model.complete(ctx.messages, name=f"call_model_step/{ctx.player_id}/{ctx.request.action_type.value}")
    except Exception as exc:
        ctx.errors.append(f"LLM call failed: {exc}")
        ctx.raw_output = ""
    return ctx
