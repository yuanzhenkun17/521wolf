"""GoT node — high-conflict graph reasoning before ToT/normal LLM."""

from __future__ import annotations

import json

from agent.reasoning.got import need_got, run_got_selection
from agent.runtime.context import AgentContext
from agent.runtime.model import ModelAdapter


async def got_node(ctx: AgentContext, model: ModelAdapter, *, threshold: float = 0.3) -> AgentContext:
    if not need_got(ctx, threshold=threshold):
        return ctx

    try:
        result = await run_got_selection(ctx, model)
    except Exception as exc:
        ctx.errors.append(f"GoT failed: {exc}")
        return ctx

    if result.selected is None or result.final_action is None:
        ctx.errors.append("GoT selected no hypothesis")
        return ctx

    ctx.got_enabled = True
    ctx.got_prompt_messages = result.prompt_messages
    ctx.got_raw_output = result.raw_output
    ctx.got_evidence_nodes = [node.to_dict() for node in result.evidence_nodes]
    ctx.got_hypotheses = [hyp.to_dict() for hyp in result.hypotheses]
    ctx.got_judge_reason = result.judge_reason

    action = result.final_action
    ctx.raw_output = json.dumps(
        {
            "choice": action.get("choice"),
            "target": action.get("target"),
            "public_text": result.public_text,
            "private_reasoning": result.private_reasoning,
            "confidence": result.confidence,
            "alternatives": [],
            "rejected_reasons": [],
            "memory_refs": [],
            "selected_skills": "",
        },
        ensure_ascii=False,
    )
    ctx.source = "got"
    return ctx
