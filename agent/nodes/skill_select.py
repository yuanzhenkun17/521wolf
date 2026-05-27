"""Skill select node — Stage 1 of two-stage skill selection.

Sends skill descriptions to the LLM and receives a list of relevant
skill names.  Stores the selection in ``ctx`` so that ``skill_router_node``
can filter accordingly.

If the LLM call fails, ``ctx.skill_selection`` stays ``None`` and
``skill_router_node`` falls back to injecting all role-matched skills.
"""

from __future__ import annotations

from pathlib import Path

from langfuse import observe

from agent.runtime.context import AgentContext
from agent.runtime.model import ModelAdapter
from agent.skill_system.router import select_skills_by_llm


@observe(name="skill_select_node")
async def skill_select_node(
    ctx: AgentContext,
    model: ModelAdapter,
    *,
    skill_root: Path | None = None,
) -> AgentContext:
    """Ask the LLM to select relevant skills from descriptions."""
    import logging
    from engine.models import Role

    try:
        role = Role(ctx.role)
    except ValueError:
        logging.getLogger(__name__).warning(
            "Unknown role %r in context, skipping skill selection", ctx.role
        )
        return ctx

    selected = await select_skills_by_llm(ctx, role, model, skill_root=skill_root)

    if selected is not None and selected:
        ctx.skill_selection = {s.name for s in selected}
    # else: leave skill_selection as None → fallback in skill_router_node
    return ctx
