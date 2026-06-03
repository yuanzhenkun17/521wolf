from __future__ import annotations

from agent.infrastructure.tracing import observe
from agent.knowledge.prompts.parsing import load_json_object
from agent.core.context import AgentContext
from agent.common import as_float as _as_float, as_int_list
from engine.models import ActionResponse


@observe(name="parse_output_step")
def parse_output_step(ctx: AgentContext) -> AgentContext:
    """Parse the LLM raw output into a structured decision and response.

    Accepts both legacy output aliases (``text``, ``reasoning``) and current field
    names (``public_text``, ``private_reasoning``, ``confidence``,
    ``selected_skills``).
    """
    if not ctx.raw_output:
        if ctx.source != "llm_error":
            ctx.errors.append("Empty LLM output, will fall back to policy.")
            ctx.source = "fallback"
        return ctx

    try:
        data = load_json_object(ctx.raw_output)
    except Exception as exc:
        ctx.errors.append(f"JSON parse failed: {exc}")
        ctx.source = "fallback"
        return ctx

    # Compatible field extraction
    choice = data.get("choice")
    target = data.get("target")
    if target is not None:
        try:
            target = int(target)
        except (TypeError, ValueError):
            ctx.errors.append(f"Invalid target value: {target}")
            target = None

    # Accept both current and legacy output field names
    public_text = str(data.get("public_text") or data.get("text") or "")
    private_reasoning = str(
        data.get("private_reasoning") or data.get("reasoning") or ""
    )
    confidence = _as_float(data.get("confidence"), 0.0)
    alternatives = as_int_list(data.get("alternatives"))
    rejected_reasons = [
        str(r) for r in data.get("rejected_reasons", []) if r is not None
    ]
    selected_skills = data.get("selected_skills", [])

    ctx.response = ActionResponse(
        ctx.request.action_type,
        target=target,
        choice=choice,
        text=public_text,
    )

    ctx.parsed_decision = {
        "target": target,
        "choice": choice,
        "public_text": public_text,
        "private_reasoning": private_reasoning,
        "confidence": confidence,
        "alternatives": alternatives,
        "rejected_reasons": rejected_reasons,
        "selected_skills": selected_skills if isinstance(selected_skills, list) else [],
    }
    ctx.confidence = confidence

    return ctx
