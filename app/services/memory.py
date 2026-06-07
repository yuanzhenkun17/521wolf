"""Short-term player-view memory for the Agent pipeline.

Also provides a LangChain BaseChatMessageHistory adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine import ActionRequest, ActionResponse, Role


# ---------------------------------------------------------------------------
# Phase group mapping
# ---------------------------------------------------------------------------

_PHASE_GROUP_MAP: dict[str, str] = {
    "night": "night",
    "sheriff_elect": "sheriff",
    "sheriff_speech": "sheriff",
    "sheriff_vote": "sheriff",
    "day_speech": "day_speech",
    "day_discuss": "day_speech",
    "exile_vote": "exile_vote",
    "pk_vote": "exile_vote",
    "pk_speech": "day_speech",
    "last_word": "death_resolution",
    "death_resolution": "death_resolution",
}


def normalize_phase_group(phase: str) -> str:
    """Map a raw phase string to a normalized phase group."""
    return _PHASE_GROUP_MAP.get(phase, phase)


# ---------------------------------------------------------------------------
# Segment data classes
# ---------------------------------------------------------------------------

@dataclass
class SegmentEvent:
    """A single player-view event within a segment."""
    day: int
    phase: str
    event_type: str
    actor: int | None
    target: int | None
    content: str
    public: bool = True
    index: int | None = None

    def to_prompt_text(self) -> str:
        actor = f"P{self.actor}" if self.actor is not None else "系统"
        target = f" -> P{self.target}" if self.target is not None else ""
        vis = "" if self.public else " [私密]"
        return f"第{self.day}天 {self.phase} {self.event_type} {actor}{target}: {self.content}{vis}"


@dataclass
class Segment:
    """A group of events within the same phase_group:day window."""
    segment_key: str
    day: int
    phase_group: str
    events: list[SegmentEvent] = field(default_factory=list)
    closed: bool = False
    compression_retry_count: int = 0
    compression_failed: bool = False

    def add_event(self, event: SegmentEvent) -> None:
        self.events.append(event)

    def to_prompt_dicts(self) -> list[dict[str, Any]]:
        return [
            {
                "day": e.day,
                "phase": e.phase,
                "type": e.event_type,
                "actor": e.actor,
                "target": e.target,
                "content": e.content,
                "public": e.public,
                "text": e.to_prompt_text(),
            }
            for e in self.events
        ]


@dataclass
class CompressedSegmentSummary:
    """LLM-generated summary of a closed segment."""
    segment_key: str
    summary: str
    key_events: list[str] = field(default_factory=list)
    player_notes: dict[str, str] = field(default_factory=dict)
    unknowns: list[str] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "segment_key": self.segment_key,
            "summary": self.summary,
            "key_events": self.key_events,
            "player_notes": self.player_notes,
            "unknowns": self.unknowns,
        }


# ---------------------------------------------------------------------------
# AgentMemory
# ---------------------------------------------------------------------------

class AgentMemory:
    """Current-game memory scoped to one player view.

    The memory model intentionally contains only the first-stage runtime
    structures: current visible state, open segment events, recent closed
    segment events, compressed segment summaries, and compression state.
    Cross-game knowledge is supplied only by Markdown skills.
    """

    def __init__(self, player_id: int, role: Role) -> None:
        self.player_id = player_id
        self.role = role
        self.errors: list[str] = []
        self.segments: list[Segment] = []
        self.compressed_segment_summaries: dict[str, CompressedSegmentSummary] = {}
        self._current_segment_key: str | None = None
        self._seen_event_keys: set[int | tuple[Any, ...]] = set()
        self.game_id: str | None = None

    def build_context(self, request: ActionRequest) -> dict[str, Any]:
        """Update memory from an observation and return the prompt window."""
        self.update_segments(request)
        observation = request.observation

        closed = [segment for segment in self.segments if segment.closed]
        recent_closed = closed[-4:]
        older_closed = closed[:-4]
        open_segment = next((segment for segment in self.segments if not segment.closed), None)

        return {
            "current_visible_state": {
                "player_id": request.player_id,
                "role": observation.self_role.value
                if hasattr(observation.self_role, "value")
                else str(observation.self_role),
                "day": observation.day,
                "phase": request.phase.value,
                "alive_players": list(observation.alive_players),
                "dead_players": list(observation.dead_players),
                "sheriff_id": observation.sheriff_id,
                "candidates": list(request.candidates),
            },
            "private_facts": {
                "known_roles": {
                    player_id: role.value
                    for player_id, role in observation.known_roles.items()
                },
                "seer_checks": {
                    player_id: team.value
                    for player_id, team in observation.seer_checks.items()
                },
                "metadata": dict(request.metadata),
            },
            "open_segment": open_segment.to_prompt_dicts() if open_segment else [],
            "open_segment_key": open_segment.segment_key if open_segment else None,
            "recent_closed_segments": [
                {"segment_key": segment.segment_key, "events": segment.to_prompt_dicts()}
                for segment in recent_closed
            ],
            "compressed_segment_summaries": [
                self.compressed_segment_summaries[segment.segment_key].to_prompt_dict()
                for segment in older_closed
                if segment.segment_key in self.compressed_segment_summaries
            ],
            "compression_state": {
                "failed_segments": [
                    segment.segment_key for segment in self.segments if segment.compression_failed
                ],
                "retry_counts": {
                    segment.segment_key: segment.compression_retry_count
                    for segment in self.segments
                    if segment.compression_retry_count
                },
            },
            "errors": self.errors[-3:],
        }

    def remember_action(
        self,
        request: ActionRequest,
        response: ActionResponse,
        decision: Any = None,
    ) -> None:
        """Keep the public interface stable; actions are recorded elsewhere."""
        return None

    def reset(self) -> None:
        self.errors = []
        self.segments = []
        self.compressed_segment_summaries = {}
        self._current_segment_key = None
        self._seen_event_keys = set()

    def remember_error(self, message: str) -> None:
        self.errors.append(message)

    def update_segments(self, request: ActionRequest) -> None:
        """Route visible events into phase-group segments."""
        observation = request.observation
        current_phase = (
            observation.phase.value
            if hasattr(observation.phase, "value")
            else str(observation.phase)
        )
        phase_group = normalize_phase_group(current_phase)
        segment_key = f"{phase_group}:{observation.day}"

        if self._current_segment_key and self._current_segment_key != segment_key:
            for segment in self.segments:
                if segment.segment_key == self._current_segment_key and not segment.closed:
                    segment.closed = True
                    break

        current_segment = self._find_or_create_segment(
            segment_key=segment_key,
            day=observation.day,
            phase_group=phase_group,
        )
        self._current_segment_key = segment_key

        for event in observation.visible_events:
            event_key = _event_key(event)
            if event_key in self._seen_event_keys:
                continue
            self._seen_event_keys.add(event_key)
            phase = event.phase.value if hasattr(event.phase, "value") else str(event.phase)
            current_segment.add_event(
                SegmentEvent(
                    day=event.day,
                    phase=phase or current_phase,
                    event_type=event.type,
                    actor=event.actor,
                    target=event.target,
                    content=event.message,
                    public=event.public,
                    index=event.index if event.index > 0 else None,
                )
            )

    def _find_or_create_segment(
        self,
        *,
        segment_key: str,
        day: int,
        phase_group: str,
    ) -> Segment:
        for segment in self.segments:
            if segment.segment_key == segment_key:
                return segment
        segment = Segment(segment_key=segment_key, day=day, phase_group=phase_group)
        self.segments.append(segment)
        return segment


def _event_key(event: Any) -> int | tuple[Any, ...]:
    if getattr(event, "index", 0) > 0:
        return int(event.index)
    phase = event.phase.value if hasattr(event.phase, "value") else str(event.phase)
    return (
        event.day,
        phase,
        event.type,
        event.actor,
        event.target,
        event.message,
        event.public,
    )


# ---------------------------------------------------------------------------
# LangChain BaseChatMessageHistory adapter
# ---------------------------------------------------------------------------

def create_wolf_memory(player_id: int, role: Role) -> AgentMemory:
    """Factory function for creating an AgentMemory instance (LangChain-compatible).

    Wraps AgentMemory for use in LangGraph StateGraph nodes.
    """
    return AgentMemory(player_id=player_id, role=role)
