from __future__ import annotations

import logging
from pathlib import Path

from langfuse import observe
from engine.models import Role

from agent.runtime.context import AgentContext
from agent.skill_system.router import select_skills, format_skill_context


@observe(name="skill_router_node")
def skill_router_node(ctx: AgentContext, *, skill_root: Path | None = None, **kwargs) -> AgentContext:
    """Select common + role skills for the current context."""
    try:
        role = Role(ctx.role)
    except ValueError:
        logging.getLogger(__name__).warning(
            "Unknown role %r in context, skipping skill routing", ctx.role
        )
        return ctx
    selected = select_skills(ctx, role, skill_root=skill_root)

    ctx.selected_skills = [s.name for s in selected]
    ctx.skill_context = format_skill_context(selected, ctx.request.action_type)
    ctx.strategy_advice = {
        "skill_count": len(selected),
        "prompt_hints": [hint for s in selected for hint in s.prompt_hints],
    }

    return ctx
