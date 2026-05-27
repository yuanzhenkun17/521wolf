from __future__ import annotations

from pathlib import Path

from langfuse import observe
from engine.models import Role

from agent.runtime.context import AgentContext
from agent.skill_system.router import select_skills, format_skill_context


@observe(name="skill_router_node")
def skill_router_node(ctx: AgentContext, *, skill_root: Path | None = None, **kwargs) -> AgentContext:
    """Select common + role skills for the current context."""
    role = Role(ctx.role)
    selected = select_skills(ctx, role, skill_root=skill_root)

    ctx.selected_skills = [s.name for s in selected]
    ctx.selected_skill = ",".join(s.name for s in selected)
    ctx.skill_context = format_skill_context(selected, ctx.request.action_type)
    ctx.strategy_advice = {
        "selected_skills": ctx.selected_skills,
        "skill_count": len(selected),
        "prompt_hints": [hint for s in selected for hint in s.prompt_hints],
    }

    return ctx
