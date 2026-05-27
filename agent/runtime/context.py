from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from engine.models import ActionRequest, ActionResponse


@dataclass(slots=True)
class AgentContext:
    """Central state object flowing through the Agent decision pipeline.

    Each node reads from and writes to this context.  The rules layer only
    sees ActionRequest -> ActionResponse; everything else is Agent-internal.
    """

    request: ActionRequest
    player_id: int
    role: str

    # Observation
    observation_summary: dict[str, Any] = field(default_factory=dict)

    # Memory
    memory_context: dict[str, Any] = field(default_factory=dict)

    # Belief
    belief_context: dict[str, Any] = field(default_factory=dict)

    # Skill routing
    selected_skill: str | None = None
    selected_skills: list[str] = field(default_factory=list)
    skill_context: str = ""
    strategy_advice: dict[str, Any] = field(default_factory=dict)
    skill_selection: set[str] | None = None  # LLM-selected skill names (Stage 1)

    # LLM interaction
    messages: list[dict[str, str]] = field(default_factory=list)
    raw_output: str = ""

    # Decision
    parsed_decision: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    response: ActionResponse | None = None

    # Decision record (set by log_node, written back to memory by runtime)
    decision_record: Any = None

    # Tracking
    source: Literal["llm", "policy_adjusted", "fallback", "tot", "got"] = "llm"
    policy_adjustments: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    # ToT (Tree-of-Thought) multi-candidate reasoning
    tot_enabled: bool = False
    tot_candidates: list[dict[str, Any]] = field(default_factory=list)
    tot_judge_reason: str = ""

    # GoT (Graph-of-Thought) evidence/hypothesis reasoning
    got_enabled: bool = False
    got_evidence_nodes: list[dict[str, Any]] = field(default_factory=list)
    got_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    got_judge_reason: str = ""
