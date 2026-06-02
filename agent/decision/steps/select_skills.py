from __future__ import annotations

import logging
from pathlib import Path

from agent.infrastructure.tracing import observe
from engine.models import Role

from agent.core.context import AgentContext
from agent.knowledge.skills.router import select_skills, format_skill_context


@observe(name="select_skills_step")
def select_skills_step(ctx: AgentContext, *, skill_root: Path | None = None) -> AgentContext:
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
    }

    return ctx
