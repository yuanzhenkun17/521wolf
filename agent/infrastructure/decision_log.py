"""Decision logging — records every agent decision within a game.

Provides the data structures and recorder used by the runtime to
persist each decision for post-game review and leaderboard evaluation.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from engine.models import ActionType

from agent.common.json import DictMixin


@dataclass(slots=True)
class DecisionRecord(DictMixin):
    action_type: ActionType
    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
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
    selected_skills: list[str] = field(default_factory=list)
    memory_summary: list[str] = field(default_factory=list)
    raw_output: str = ""
    errors: list[str] = field(default_factory=list)
    policy_adjustments: list[str] = field(default_factory=list)
    source: Literal["llm", "llm_error", "fallback", "policy_adjusted", "tot", "got"] = "llm"


class DecisionSink(Protocol):
    def record_decision(self, decision: DecisionRecord) -> None:
        ...


class AgentDecisionRecorder:
    def __init__(
        self,
        stream_path: str | Path | None = None,
        sink: DecisionSink | None = None,
    ) -> None:
        self.records: list[DecisionRecord] = []
        self._stream_path: Path | None = Path(stream_path) if stream_path else None
        if self._stream_path:
            self._stream_path.parent.mkdir(parents=True, exist_ok=True)
            self._stream_path.touch()
        self._sink = sink

    def record(self, decision: DecisionRecord) -> None:
        self.records.append(decision)
        if self._stream_path:
            line = json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True)
            with self._stream_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        if self._sink is not None:
            self._sink.record_decision(decision)

    def to_jsonl(self) -> str:
        lines = [json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) for record in self.records]
        return "\n".join(lines) + ("\n" if lines else "")

    def write_jsonl(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_jsonl(), encoding="utf-8")
        return output

