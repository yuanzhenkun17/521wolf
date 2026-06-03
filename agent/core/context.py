from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from engine.models import ActionRequest, ActionResponse


@dataclass(slots=True)
class AgentContext:
    """Central state object flowing through the Agent decision pipeline.

    Each step reads from and writes to this context. The rules layer only
    sees ActionRequest -> ActionResponse; everything else is Agent-internal.
    """

    request: ActionRequest
    player_id: int
    role: str

    # Memory
    memory_context: dict[str, Any] = field(default_factory=dict)

    # Skill selection
    selected_skills: list[str] = field(default_factory=list)
    skill_context: str = ""
    strategy_advice: dict[str, Any] = field(default_factory=dict)

    # LLM interaction
    messages: list[dict[str, str]] = field(default_factory=list)
    raw_output: str = ""

    # Decision
    parsed_decision: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    response: ActionResponse | None = None

    # Decision record (built by runtime after pipeline steps)
    decision_record: Any = None

    # Tracking
    source: Literal["llm", "policy_adjusted", "fallback"] = "llm"
    policy_adjustments: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
