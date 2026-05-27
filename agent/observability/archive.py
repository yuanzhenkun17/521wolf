"""Game archive — full trace recording for post-game analysis.

Captures every decision's full context: observation, memory, belief, skills,
prompt, raw output, parsed decision, policy adjustments.  Written to disk
per-game for review, experience extraction, and leaderboard aggregation.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.runtime.context import AgentContext


@dataclass(slots=True)
class DecisionArchive:
    """Full trace of a single agent decision — heavier than DecisionRecord."""

    decision_id: str
    index: int
    player_id: int
    role: str
    day: int
    phase: str
    action_type: str
    candidates: list[int]
    observation_summary: dict
    memory_context: dict
    belief_context: dict
    selected_skills: list[str]
    prompt_messages: list[dict]
    raw_output: str
    parsed_decision: dict
    final_response: dict
    source: str
    confidence: float | None
    policy_adjustments: list[str]
    errors: list[str]
    tot_candidates: list[dict] = field(default_factory=list)
    tot_judge_reason: str = ""
    got_evidence_nodes: list[dict] = field(default_factory=list)
    got_hypotheses: list[dict] = field(default_factory=list)
    got_judge_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "index": self.index,
            "player_id": self.player_id,
            "role": self.role,
            "day": self.day,
            "phase": self.phase,
            "action_type": self.action_type,
            "candidates": self.candidates,
            "observation_summary": self.observation_summary,
            "memory_context": _sanitize(self.memory_context),
            "belief_context": _sanitize(self.belief_context),
            "selected_skills": self.selected_skills,
            "prompt_messages": self.prompt_messages,
            "raw_output": self.raw_output,
            "parsed_decision": _sanitize(self.parsed_decision),
            "final_response": self.final_response,
            "source": self.source,
            "confidence": self.confidence,
            "policy_adjustments": self.policy_adjustments,
            "errors": self.errors,
            "tot_candidates": self.tot_candidates,
            "tot_judge_reason": self.tot_judge_reason,
            "got_evidence_nodes": self.got_evidence_nodes,
            "got_hypotheses": self.got_hypotheses,
            "got_judge_reason": self.got_judge_reason,
        }

    @classmethod
    def from_context(cls, ctx: AgentContext, index: int = 0) -> DecisionArchive:
        """Build a DecisionArchive from the final AgentContext state."""
        pd = ctx.parsed_decision
        return cls(
            decision_id=uuid.uuid4().hex[:12],
            index=index,
            player_id=ctx.player_id,
            role=ctx.role,
            day=ctx.request.observation.day,
            phase=ctx.request.phase.value,
            action_type=ctx.request.action_type.value,
            candidates=list(ctx.request.candidates),
            observation_summary={
                "day": ctx.request.observation.day,
                "phase": ctx.request.phase.value,
                "alive_players": list(ctx.request.observation.alive_players),
                "dead_players": list(ctx.request.observation.dead_players),
                "sheriff_id": ctx.request.observation.sheriff_id,
                "candidates": list(ctx.request.candidates),
            },
            memory_context=ctx.memory_context,
            belief_context=ctx.belief_context,
            selected_skills=list(ctx.selected_skills),
            prompt_messages=list(ctx.messages),
            raw_output=ctx.raw_output,
            parsed_decision=dict(pd),
            final_response=_response_to_dict(ctx.response),
            source=ctx.source,
            confidence=ctx.confidence,
            policy_adjustments=list(ctx.policy_adjustments),
            errors=list(ctx.errors),
            tot_candidates=list(ctx.tot_candidates),
            tot_judge_reason=ctx.tot_judge_reason,
            got_evidence_nodes=list(ctx.got_evidence_nodes),
            got_hypotheses=list(ctx.got_hypotheses),
            got_judge_reason=ctx.got_judge_reason,
        )


@dataclass(slots=True)
class GameArchive:
    """Complete archive of a single game."""

    game_id: str
    seed: int
    config: dict
    player_roles: dict[int, str]
    winner: str | None
    started_at: str
    finished_at: str | None
    public_events: list[dict]
    decisions: list[DecisionArchive]
    final_state: dict

    def to_dict(self) -> dict:
        return {
            "game_id": self.game_id,
            "seed": self.seed,
            "config": self.config,
            "player_roles": {str(k): v for k, v in self.player_roles.items()},
            "winner": self.winner,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "public_events": self.public_events,
            "decisions": [d.to_dict() for d in self.decisions],
            "final_state": self.final_state,
        }

    def write_json(self, path: Path) -> None:
        """Serialize archive to JSON file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)


class AgentTraceRecorder:
    """Collects full decision traces during a game for post-game archive."""

    def __init__(self) -> None:
        self._traces: list[DecisionArchive] = []
        self._index = 1

    def record(self, ctx: AgentContext) -> None:
        """Capture a snapshot of the current decision context."""
        trace = DecisionArchive.from_context(ctx, self._index)
        self._traces.append(trace)
        self._index += 1

    def snapshot(self) -> list[DecisionArchive]:
        """Return collected traces without writing to disk.

        Use in place of ``flush()`` when the caller wants to merge
        traces from multiple recorders before a single archive write.
        """
        return list(self._traces)

    def flush(self, game_id: str, output_dir: Path, **meta) -> GameArchive:
        """Write all collected traces to disk and return the GameArchive."""
        archive = GameArchive(
            game_id=game_id,
            seed=meta.get("seed", 0),
            config=meta.get("config", {}),
            player_roles=meta.get("player_roles", {}),
            winner=meta.get("winner"),
            started_at=meta.get("started_at", _now()),
            finished_at=_now(),
            public_events=meta.get("public_events", []),
            decisions=self.snapshot(),
            final_state=meta.get("final_state", {}),
        )
        archive_path = output_dir / "archive.json"
        archive.write_json(archive_path)
        return archive

    @property
    def count(self) -> int:
        return len(self._traces)

    def clear(self) -> None:
        self._traces.clear()
        self._index = 1


# ── helpers ──────────────────────────────────────────────────────────────────


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize(obj: Any) -> Any:
    """Remove non-serializable items from a dict (e.g. LLM message objects)."""
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    try:
        json.dumps(obj)
        return obj
    except (TypeError, ValueError):
        return str(obj)


def _response_to_dict(resp) -> dict:
    if resp is None:
        return {}
    return {
        "action_type": resp.action_type.value if hasattr(resp.action_type, "value") else str(resp.action_type),
        "target": resp.target,
        "choice": resp.choice,
        "text": resp.text or "",
    }
