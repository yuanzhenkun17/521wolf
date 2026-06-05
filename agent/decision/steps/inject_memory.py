"""Optional step: inject cross-game patterns and episodic memory into the prompt."""
from __future__ import annotations

import logging
from typing import Any

from agent.infrastructure.tracing import observe
from agent.core.context import AgentContext

_log = logging.getLogger(__name__)


@observe(name="inject_memory_step")
def inject_memory_step(
    ctx: AgentContext,
    *,
    pattern_provider: Any | None = None,   # PatternEngine or compatible callable
    episodic_provider: Any | None = None,  # callable returning list[dict]
) -> AgentContext:
    """Query pattern_provider and episodic_provider for relevant cross-game knowledge.

    Results are stored in ``ctx.memory_injection`` as a formatted string.
    If neither provider is available or both return empty results, the field
    is set to ``None`` so that downstream prompt assembly can skip the block.

    All errors are silently logged so that a failure here never breaks the
    main decision pipeline.
    """
    parts: list[str] = []

    # -- Pattern injection --------------------------------------------------------
    if pattern_provider is not None:
        try:
            patterns = pattern_provider.get_relevant_patterns(
                role=ctx.role,
                phase=ctx.request.phase.value,
                day=ctx.request.observation.day,
                action_type=ctx.request.action_type.value,
            )
            pattern_lines = _format_patterns(patterns[:5])
            if pattern_lines:
                parts.append(pattern_lines)
        except Exception:
            _log.warning("pattern_provider.get_relevant_patterns failed", exc_info=True)

    # -- Episodic memory injection ------------------------------------------------
    if episodic_provider is not None:
        try:
            memories = episodic_provider(
                ctx.role,
                ctx.request.observation.day,
                ctx.request.phase.value,
            )
            episodic_lines = _format_episodic_memories(memories[:3])
            if episodic_lines:
                parts.append(episodic_lines)
        except Exception:
            _log.warning("episodic_provider call failed", exc_info=True)

    ctx.memory_injection = "\n".join(parts) if parts else None
    return ctx


# -- Formatting helpers -----------------------------------------------------------


def _format_patterns(patterns: list[Any]) -> str:
    """Format a list of Pattern objects into structured Chinese text.

    Example output::

        经验规律:
        - [confidence=0.85] 首夜作为女巫救预言家 (胜率62%, 47局)
        - [confidence=0.72] 预言家第一天白天查验P3 (胜率58%, 31局)
    """
    if not patterns:
        return ""
    lines = ["经验规律:"]
    for p in patterns:
        try:
            confidence = getattr(p, "confidence", 0.0)
            recommendation = getattr(p, "recommendation", "")
            win_rate = getattr(p, "win_rate_with", 0.0)
            sample_size = getattr(p, "sample_size", 0)
            win_pct = int(round(win_rate * 100))
            lines.append(
                f"- [confidence={confidence:.2f}] {recommendation}"
                f" (胜率{win_pct}%, {sample_size}局)"
            )
        except Exception:
            _log.debug("Failed to format pattern entry", exc_info=True)
    return "\n".join(lines) if len(lines) > 1 else ""


def _format_episodic_memories(memories: list[dict[str, Any]]) -> str:
    """Format episodic memory dicts into brief Chinese snippets.

    Expected dict keys (all optional; gracefully skips missing fields)::

        {
            "day": 3,
            "phase": "day_speech",
            "role": "seer",
            "action": "查验了P5(狼人)",
            "outcome": "最终获胜",
            "summary": "...",  # alternative one-liner
        }

    Example output::

        历史案例:
        - 第3天白天作为预言家查验了P5(狼人)，最终获胜
        - 第1天夜晚作为女巫救了P2(预言家)，最终失败
    """
    if not memories:
        return ""
    lines = ["历史案例:"]
    for mem in memories:
        if not isinstance(mem, dict):
            continue
        # Prefer a pre-built summary if available
        summary = mem.get("summary")
        if summary:
            lines.append(f"- {summary}")
            continue
        # Build from components
        day = mem.get("day")
        phase = mem.get("phase", "")
        role = mem.get("role", "")
        action = mem.get("action", "")
        outcome = mem.get("outcome", "")
        parts = []
        if day is not None:
            parts.append(f"第{day}天{phase}")
        if role:
            parts.append(f"作为{role}")
        if action:
            parts.append(action)
        snippet = "".join(parts)
        if outcome:
            snippet = f"{snippet}，{outcome}"
        if snippet:
            lines.append(f"- {snippet}")
    return "\n".join(lines) if len(lines) > 1 else ""
