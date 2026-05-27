from __future__ import annotations

from langfuse import observe
from agent.prompts.parsing import load_json_object
from agent.runtime.context import AgentContext
from engine.models import ActionResponse


@observe(name="parse_node")
def parse_node(ctx: AgentContext) -> AgentContext:
    """Parse the LLM raw output into a structured decision and response.

    Accepts both legacy output aliases (``text``, ``reasoning``) and current field
    names (``public_text``, ``private_reasoning``, ``confidence``,
    ``memory_refs``, ``selected_skill``).
    """
    if not ctx.raw_output:
        ctx.errors.append("Empty LLM output, will fall back to policy.")
        ctx.source = "fallback"
        return ctx

    try:
        data = load_json_object(ctx.raw_output)
    except Exception as exc:
        ctx.errors.append(f"JSON parse failed: {exc}")
        ctx.source = "fallback"
        return ctx

    # --- compatible field extraction ------------------------------------------
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
    alternatives = _int_list(data.get("alternatives"))
    rejected_reasons = [
        str(r) for r in data.get("rejected_reasons", []) if r is not None
    ]
    memory_refs = [
        str(r) for r in data.get("memory_refs", []) if r is not None
    ]
    selected_skill = str(data.get("selected_skill") or "")

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
        "memory_refs": memory_refs,
        "selected_skill": selected_skill,
    }
    ctx.confidence = confidence

    return ctx


def _as_float(value, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_list(value) -> list[int]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result
