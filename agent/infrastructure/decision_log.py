"""Decision logging — records every agent decision within a game.

Provides the data structures and recorder used by the runtime to
persist each decision for post-game review and leaderboard evaluation.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from engine.models import ActionType


@dataclass(slots=True)
class DecisionRecord:
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

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
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
            "memory_summary": self.memory_summary,
            "raw_output": self.raw_output,
            "errors": self.errors,
            "policy_adjustments": self.policy_adjustments,
            "source": self.source,
        }


class AgentDecisionRecorder:
    def __init__(
        self,
        stream_path: str | Path | None = None,
        conn: sqlite3.Connection | None = None,
        game_id: str | None = None,
    ) -> None:
        self.records: list[DecisionRecord] = []
        self._stream_path: Path | None = Path(stream_path) if stream_path else None
        if self._stream_path:
            self._stream_path.parent.mkdir(parents=True, exist_ok=True)
            self._stream_path.touch()
        self._conn = conn
        self._game_id = game_id

    def record(self, decision: DecisionRecord) -> None:
        self.records.append(decision)
        if self._stream_path:
            line = json.dumps(decision.to_dict(), ensure_ascii=False, sort_keys=True)
            with self._stream_path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        if self._conn is not None and self._game_id is not None:
            self._conn.execute(
                "INSERT OR REPLACE INTO decisions "
                "(id, game_id, seat, role, day, phase, action_type, "
                "selected_target, selected_choice, public_text, private_reasoning, "
                "confidence, alternatives, rejected_reasons, selected_skills, "
                "raw_output, source, policy_adjustments, errors, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                (
                    decision.decision_id,
                    self._game_id,
                    decision.player_id or 0,
                    decision.role,
                    decision.day,
                    decision.phase,
                    decision.action_type.value,
                    decision.selected_target,
                    decision.selected_choice,
                    decision.public_text,
                    decision.private_reasoning,
                    decision.confidence,
                    json.dumps(decision.alternatives, ensure_ascii=False),
                    json.dumps(decision.rejected_reasons, ensure_ascii=False),
                    json.dumps(decision.selected_skills, ensure_ascii=False),
                    decision.raw_output,
                    decision.source,
                    json.dumps(decision.policy_adjustments, ensure_ascii=False),
                    json.dumps(decision.errors, ensure_ascii=False),
                ),
            )

    def to_jsonl(self) -> str:
        lines = [json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) for record in self.records]
        return "\n".join(lines) + ("\n" if lines else "")

    def write_jsonl(self, path: str | Path) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(self.to_jsonl(), encoding="utf-8")
        return output

