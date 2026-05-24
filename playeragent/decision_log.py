from __future__ import annotations

import json
from pathlib import Path

from playeragent.decision import DecisionRecord


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
