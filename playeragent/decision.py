from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from werewolf.models import ActionType


@dataclass(slots=True)
class StrategyAdvice:
    goal: str
    preferred_targets: list[int] = field(default_factory=list)
    avoid_targets: list[int] = field(default_factory=list)
    public_stance: str = ""
    private_notes: list[str] = field(default_factory=list)

    def to_prompt_dict(self) -> dict:
        return {
            "goal": self.goal,
            "preferred_targets": self.preferred_targets,
            "avoid_targets": self.avoid_targets,
            "public_stance": self.public_stance,
            "private_notes": self.private_notes,
        }


@dataclass(slots=True)
class DecisionRecord:
    action_type: ActionType
    day: int = 0
    phase: str = ""
    player_id: int | None = None
    role: str = ""
    candidates: list[int] = field(default_factory=list)
    selected_target: int | None = None
    selected_choice: str | None = None
    public_text: str = ""
    private_reasoning: str = ""
    alternatives: list[int] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)
    belief_snapshot: dict = field(default_factory=dict)
    memory_summary: list[str] = field(default_factory=list)
    source: Literal["llm", "fallback", "policy_adjusted"] = "llm"

    def to_dict(self) -> dict:
        return {
            "day": self.day,
            "phase": self.phase,
            "player_id": self.player_id,
            "role": self.role,
            "action_type": self.action_type.value,
            "candidates": self.candidates,
            "selected_target": self.selected_target,
            "selected_choice": self.selected_choice,
            "public_text": self.public_text,
            "private_reasoning": self.private_reasoning,
            "alternatives": self.alternatives,
            "rejected_reasons": self.rejected_reasons,
            "belief_snapshot": self.belief_snapshot,
            "memory_summary": self.memory_summary,
            "source": self.source,
        }
