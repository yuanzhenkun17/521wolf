from __future__ import annotations

from agent.infrastructure.tracing import observe
from agent.core.context import AgentContext
from agent.infrastructure.llm import ModelAdapter


@observe(name="call_model_step")
async def call_model_step(ctx: AgentContext, model: ModelAdapter) -> AgentContext:
    """Call the LLM with the prepared messages and capture the raw output."""
    try:
        ctx.raw_output = await model.complete(ctx.messages)
    except Exception as exc:
        ctx.errors.append(f"LLM call failed: {exc}")
        ctx.llm_error = str(exc)
        ctx.source = "llm_error"
        ctx.raw_output = ""
    return ctx
