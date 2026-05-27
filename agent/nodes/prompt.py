from __future__ import annotations

import logging

from langfuse import observe
from agent.prompts import build_messages
from agent.prompts.base import build_system_prompt, build_request_prompt
from agent.prompts.instructions import default_persona
from agent.runtime.context import AgentContext
from engine.models import Role

logger = logging.getLogger(__name__)

_GENERIC_PERSONA = "发言简洁，优先保命。谨慎观察，跟随自己的判断。"


@observe(name="prompt_node")
def prompt_node(
    ctx: AgentContext,
    *,
    persona: str | None = None,
) -> AgentContext:
    """Build LLM messages (system + user) from the current context."""
    try:
        role = Role(ctx.role)
    except ValueError:
        logger.warning(
            "Unknown role %r in context, building minimal prompt", ctx.role
        )
        ctx.messages = _build_minimal_messages(ctx, persona)
        return ctx

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


def _build_minimal_messages(
    ctx: AgentContext, persona: str | None
) -> list[dict[str, str]]:
    """Build a prompt without role-specific skills when Role resolution fails."""
    system = build_system_prompt(
        player_id=ctx.player_id,
        role=Role.VILLAGER,  # safe default for prompt text only
        persona=persona or _GENERIC_PERSONA,
    )
    user = build_request_prompt(
        ctx.request,
        ctx.memory_context,
        belief_context=ctx.belief_context or {},
        strategy_advice=ctx.strategy_advice or {},
        selected_skill=None,
        skill_context="",
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
