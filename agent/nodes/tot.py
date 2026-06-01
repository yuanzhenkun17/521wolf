"""ToT node — single-call multi-candidate reasoning for key decisions.

Placed after prompt_node, before llm_node in the pipeline.  When the
current action qualifies for ToT, the LLM generates 3 candidates and
self-selects the best one in one API call.  On success ``ctx.source``
is set to ``"tot"`` so the runtime skips llm_node + parse_node.
"""

from __future__ import annotations

import json

from agent.runtime.context import AgentContext
from agent.runtime.model import ModelAdapter
from agent.reasoning.tot import need_tot, run_tot_selection


async def tot_node(ctx: AgentContext, model: ModelAdapter) -> AgentContext:
    if not need_tot(ctx.request.action_type.value):
        return ctx

    try:
        result = await run_tot_selection(ctx, model)
    except Exception as exc:
        ctx.errors.append(f"ToT failed: {exc}")
        return ctx

    if result.selected is None or result.final_action is None:
        ctx.errors.append("ToT selected no candidate")
        return ctx

    ctx.tot_enabled = True
    ctx.tot_prompt_messages = result.prompt_messages
    ctx.tot_raw_output = result.raw_output
    ctx.tot_candidates = [c.to_dict() for c in result.candidates]
    ctx.tot_judge_reason = result.judge_reason

    selected = result.selected
    action = result.final_action
    ctx.raw_output = json.dumps(
        {
            "choice": action.get("choice"),
            "target": action.get("target"),
            "public_text": selected.public_text,
            "private_reasoning": selected.private_reasoning,
            "confidence": result.confidence,
            "alternatives": [],
            "rejected_reasons": [],
            "memory_refs": [],
            "selected_skills": "",
        },
        ensure_ascii=False,
    )
    ctx.source = "tot"
    return ctx
