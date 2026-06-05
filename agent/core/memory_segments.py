"""Segment-based memory structures for the Agent pipeline.

Segments divide in-game events into phase-group windows. The most recent
segments are kept in full; older ones are LLM-compressed into summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# Phase group mapping: raw phase -> normalized group
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
    """Map a raw phase string to a normalized phase group.

    Unknown phases fall back to the raw string to avoid losing events.
    """
    return _PHASE_GROUP_MAP.get(phase, phase)


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
