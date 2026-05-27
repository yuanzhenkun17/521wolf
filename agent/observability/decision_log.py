"""Decision logging — records every agent decision within a game.

Provides the data structures and recorder used by the runtime to
persist each decision for post-game review and leaderboard evaluation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from engine.models import ActionType


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
    confidence: float = 0.0
    alternatives: list[int] = field(default_factory=list)
    rejected_reasons: list[str] = field(default_factory=list)
    selected_skills: str = ""
    memory_refs: list[str] = field(default_factory=list)
    belief_snapshot: dict = field(default_factory=dict)
    memory_summary: list[str] = field(default_factory=list)
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)
    policy_adjustments: list[str] = field(default_factory=list)
    source: Literal["llm", "fallback", "policy_adjusted", "tot", "got"] = "llm"

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
            "confidence": self.confidence,
            "alternatives": self.alternatives,
            "rejected_reasons": self.rejected_reasons,
            "selected_skills": self.selected_skills,
            "memory_refs": self.memory_refs,
            "belief_snapshot": self.belief_snapshot,
            "memory_summary": self.memory_summary,
            "raw_output": self.raw_output,
            "errors": self.errors,
            "policy_adjustments": self.policy_adjustments,
            "source": self.source,
        }


class AgentDecisionRecorder:
    def __init__(self) -> None:
        self.records: list[DecisionRecord] = []

    def record(self, decision: DecisionRecord) -> None:
        self.records.append(decision)

    def to_jsonl(self) -> str:
        lines = [json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) for record in self.records]
        return "\n".join(lines) + ("\n" if lines else "")

    def write_jsonl(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_jsonl(), encoding="utf-8")
        return output


def collect_agent_decisions(agents: dict[int, object]) -> AgentDecisionRecorder:
    recorder = AgentDecisionRecorder()
    for player_id in sorted(agents):
        agent = agents[player_id]
        runtime = getattr(agent, "runtime", None)
        memory = getattr(runtime, "memory", None)
        if memory is None:
            continue
        for decision in memory.decision_history:
            recorder.record(decision)
    recorder.records.sort(key=lambda record: (record.day, record.phase, record.player_id or 0, record.action_type.value))
    return recorder
