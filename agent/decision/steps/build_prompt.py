from __future__ import annotations

import logging

from agent.infrastructure.tracing import observe
from agent.knowledge.prompts import build_messages
from agent.knowledge.prompts.base import build_system_prompt, build_request_prompt
from agent.core.context import AgentContext
from engine.models import Role

_log = logging.getLogger(__name__)


@observe(name="build_prompt_step")
def build_prompt_step(ctx: AgentContext) -> AgentContext:
    """Build LLM messages (system + user) from the current context."""
    try:
        role = Role(ctx.role)
    except ValueError:
        _log.warning(
            "Unknown role %r in context, building minimal prompt", ctx.role
        )
        ctx.messages = _build_minimal_messages(ctx)
        return ctx

    ctx.messages = build_messages(
        ctx.request,
        player_id=ctx.player_id,
        role=role,
        memory_context=ctx.memory_context,
        strategy_advice=ctx.strategy_advice,
        selected_skills=ctx.selected_skills,
        skill_context=ctx.skill_context,
        memory_injection=ctx.memory_injection,
    )
    return ctx


def _build_minimal_messages(ctx: AgentContext) -> list[dict[str, str]]:
    """Build a prompt without role-specific skills when Role resolution fails."""
    system = build_system_prompt(
        player_id=ctx.player_id,
        role=Role.VILLAGER,  # safe default for prompt text only
    )
    user = build_request_prompt(
        ctx.request,
        ctx.memory_context,
        strategy_advice=ctx.strategy_advice or {},
        selected_skills=[],
        skill_context="",
        memory_injection=ctx.memory_injection,
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
