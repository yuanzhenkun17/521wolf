from __future__ import annotations

from langfuse import observe
from agent.prompts import build_messages
from agent.prompts.instructions import default_persona
from agent.runtime.context import AgentContext
from engine.models import Role


@observe(name="prompt_node")
def prompt_node(
    ctx: AgentContext,
    *,
    persona: str | None = None,
) -> AgentContext:
    """Build LLM messages (system + user) from the current context."""
    role = Role(ctx.role)
    player_persona = persona or default_persona(ctx.player_id, role)

    ctx.messages = build_messages(
        ctx.request,
        player_id=ctx.player_id,
        role=role,
        persona=player_persona,
        memory_context=ctx.memory_context,
        belief_context=ctx.belief_context,
        strategy_advice=ctx.strategy_advice,
        selected_skill=ctx.selected_skill,
        skill_context=ctx.skill_context,
    )
    return ctx
