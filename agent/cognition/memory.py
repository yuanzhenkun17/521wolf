"""Enhanced memory with structured field notes and player modeling.

Extends the base memory with:
- Structured game state tracking
- Per-player behavior profiles
- Vote pattern recording
- Key events timeline
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from engine.models import ActionRequest, ActionResponse, ActionType, Role


@dataclass(slots=True)
class MemoryEvent:
    day: int
    phase: str
    event_type: str
    actor: int | None
    target: int | None
    content: str
    visibility: str = "public"

    def to_prompt_text(self) -> str:
        actor = f"P{self.actor}" if self.actor is not None else "系统"
        target = f" -> P{self.target}" if self.target is not None else ""
        return f"第{self.day}天 {self.phase} {self.event_type} {actor}{target}: {self.content}"


def as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def extract_suspected_player(content: str) -> int | None:
    patterns = [
        r"怀疑\s*(?:P)?(\d+)号?",
        r"(?:P)?(\d+)号?.{0,8}(?:像狼|狼面|可疑|有问题)",
        r"(?:P)?(\d+)号?.{0,8}(?:出掉|放逐)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return int(match.group(1))
    return None


def extract_claimed_role(content: str) -> str | None:
    role_words = {
        "预言家": "seer",
        "女巫": "witch",
        "猎人": "hunter",
        "守卫": "guard",
        "平民": "villager",
        "村民": "villager",
        "白狼王": "white_wolf_king",
    }
    if not re.search(r"(我是|自称|跳|身份)", content):
        return None
    for word, role in role_words.items():
        if word in content:
            return role
    return None


def parse_public_entry(item: str, *, fallback_day: int, fallback_phase: str) -> MemoryEvent:
    try:
        data = json.loads(item)
    except json.JSONDecodeError:
        return _parse_text_public_entry(item, fallback_day=fallback_day, fallback_phase=fallback_phase)
    if not isinstance(data, dict):
        return _parse_text_public_entry(item, fallback_day=fallback_day, fallback_phase=fallback_phase)
    return MemoryEvent(
        day=int(data.get("day", fallback_day)),
        phase=str(data.get("phase", fallback_phase)),
        event_type=str(data.get("type") or "public_log"),
        actor=as_int(data.get("actor")),
        target=as_int(data.get("target")),
        content=str(data.get("content") or ""),
        visibility=str(data.get("visibility") or "public"),
    )


def _parse_text_public_entry(item: str, *, fallback_day: int, fallback_phase: str) -> MemoryEvent:
    death = re.search(r"Player\s+(\d+)\s+died\s+by\s+([\w_]+)", item)
    if death:
        return MemoryEvent(
            day=fallback_day,
            phase=fallback_phase,
            event_type="death",
            actor=None,
            target=int(death.group(1)),
            content=f"{death.group(1)}号死亡，原因：{death.group(2)}",
        )
    chinese_death = re.search(r"(\d+)号死亡", item)
    if chinese_death:
        return MemoryEvent(
            day=fallback_day,
            phase=fallback_phase,
            event_type="death",
            actor=None,
            target=int(chinese_death.group(1)),
            content=item,
        )
    vote = re.search(r"(\d+)号.*投(?:票)?(?:给|了)(\d+)号", item)
    if vote:
        return MemoryEvent(
            day=fallback_day,
            phase=fallback_phase,
            event_type="vote",
            actor=int(vote.group(1)),
            target=int(vote.group(2)),
            content=item,
        )
    speech = re.search(r"(\d+)号.*(?:发言|说)", item)
    return MemoryEvent(
        day=fallback_day,
        phase=fallback_phase,
        event_type="speech" if speech else "public_log",
        actor=int(speech.group(1)) if speech else None,
        target=extract_suspected_player(item),
        content=item,
    )


@dataclass(slots=True)
class PlayerProfile:
    """Per-player behavior tracking within one game."""

    player_id: int
    speeches: list[str] = field(default_factory=list)
    votes_cast: list[dict] = field(default_factory=list)  # {target, day, phase}
    votes_received: list[int] = field(default_factory=list)  # player_ids who voted this player
    claimed_role: str | None = None
    attacked: list[int] = field(default_factory=list)  # players this player attacked in speech
    defended: list[int] = field(default_factory=list)  # players this player defended
    followed: list[int] = field(default_factory=list)  # players this player followed in vote

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "speech_count": len(self.speeches),
            "votes_cast": self.votes_cast[-5:],
            "votes_received": self.votes_received[-5:],
            "claimed_role": self.claimed_role,
            "attacked": self.attacked[-5:],
            "defended": self.defended[-5:],
            "followed": self.followed[-5:],
        }


@dataclass(slots=True)
class FieldNotes:
    """Structured game-state snapshot maintained by the agent."""

    game_state: dict = field(default_factory=dict)
    player_models: dict[int, PlayerProfile] = field(default_factory=dict)
    key_events: list[dict] = field(default_factory=list)
    vote_log: list[dict] = field(default_factory=list)
    relationship_graph: dict = field(default_factory=dict)  # {"attacks": [...], "protects": [...], "follows": [...]}

    def ensure_player(self, player_id: int) -> PlayerProfile:
        if player_id not in self.player_models:
            self.player_models[player_id] = PlayerProfile(player_id=player_id)
        return self.player_models[player_id]

    def record_speech(self, player_id: int, content: str) -> None:
        profile = self.ensure_player(player_id)
        profile.speeches.append(content)

    def record_vote(self, voter: int, target: int, day: int, phase: str) -> None:
        profile = self.ensure_player(voter)
        profile.votes_cast.append({"target": target, "day": day, "phase": phase})
        target_profile = self.ensure_player(target)
        target_profile.votes_received.append(voter)
        self.vote_log.append({"voter": voter, "target": target, "day": day, "phase": phase})

    def record_attack(self, attacker: int, target: int) -> None:
        self.ensure_player(attacker).attacked.append(target)

    def record_defense(self, defender: int, target: int) -> None:
        self.ensure_player(defender).defended.append(target)

    def to_prompt_dict(self) -> dict:
        alive_players = self.game_state.get("alive_players", [])
        return {
            "game_state": self.game_state,
            "player_profiles": {
                str(pid): self.player_models[pid].to_dict()
                for pid in alive_players
                if pid in self.player_models
            },
            "key_events": self.key_events[-8:],
            "vote_patterns": _summarize_vote_patterns(self.vote_log),
        }


def _summarize_vote_patterns(vote_log: list[dict]) -> list[str]:
    """Detect vote coordination patterns."""
    patterns = []
    pairs: dict[tuple, int] = {}
    for entry in vote_log:
        key = (entry["voter"], entry["target"])
        pairs[key] = pairs.get(key, 0) + 1
    for (voter, target), count in pairs.items():
        if count >= 2:
            patterns.append(f"P{voter} 连续投票给 P{target} ({count}次)")
    # Detect groups voting together — O(n) via pre-grouping
    by_day_target: dict[tuple, list[int]] = {}
    for entry in vote_log:
        by_day_target.setdefault((entry["day"], entry["target"]), []).append(entry["voter"])
    for (day, target), voters in by_day_target.items():
        if len(voters) >= 3:
            patterns.append(f"第{day}天: {len(voters)}人同票 P{target} (P{', P'.join(str(v) for v in voters)})")
    # Deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique[-8:]


_MAX_EVENTS = 200
_MAX_SELF_HISTORY = 50
_MAX_DECISION_HISTORY = 30


class AgentMemory:
    """Enhanced memory with structured field notes and player modeling."""

    def __init__(self, player_id: int, role: Role) -> None:
        self.player_id = player_id
        self.role = role
        self.events: list[MemoryEvent] = []
        self.self_history: list[str] = []
        self.decision_history: list[Any] = []
        self.suspicions: dict[int, str] = {}
        self.claims_seen: dict[int, str] = {}
        self.errors: list[str] = []
        self._seen_public_entries: set[str] = set()
        self.field_notes = FieldNotes()

    def build_context(self, request: ActionRequest) -> dict:
        self._observe_request(request)
        self._update_field_notes(request)
        observation = request.observation
        ctx = {
            "memory_events": [event.to_prompt_text() for event in self.events[-16:]],
            "private_facts": {
                "known_roles": {player_id: role.value for player_id, role in observation.known_roles.items()},
                "seer_checks": {player_id: team.value for player_id, team in observation.seer_checks.items()},
                "metadata": dict(request.metadata),
            },
            "self_history": self.self_history[-8:],
            "decisions": [decision.private_reasoning for decision in self.decision_history[-5:] if hasattr(decision, "private_reasoning") and decision.private_reasoning],
            "suspicions": dict(self.suspicions),
            "claims_seen": dict(self.claims_seen),
            "errors": self.errors[-3:],
        }
        ctx["field_notes"] = self.field_notes.to_prompt_dict()
        return ctx

    def remember_action(self, request: ActionRequest, response: ActionResponse, decision: Any = None) -> None:
        self.self_history.append(
            f"{request.action_type.value}: choice={response.choice!r} target={response.target!r} text={response.text!r}"
        )
        if len(self.self_history) > _MAX_SELF_HISTORY:
            self.self_history = self.self_history[-_MAX_SELF_HISTORY:]
        if decision is not None:
            self.decision_history.append(decision)
            if len(self.decision_history) > _MAX_DECISION_HISTORY:
                self.decision_history = self.decision_history[-_MAX_DECISION_HISTORY:]
        # Update field notes from own action
        action_type = request.action_type
        if action_type in {ActionType.EXILE_VOTE, ActionType.PK_VOTE, ActionType.SHERIFF_VOTE}:
            if response.target is not None:
                self.field_notes.record_vote(
                    request.player_id, response.target,
                    request.observation.day, request.phase.value,
                )
        if action_type in {ActionType.SPEAK, ActionType.PK_SPEAK, ActionType.LAST_WORD}:
            if response.text:
                self.field_notes.record_speech(request.player_id, response.text)

    def reset(self) -> None:
        self._seen_public_entries.clear()

    def remember_error(self, message: str) -> None:
        self.errors.append(message)

    def _observe_request(self, request: ActionRequest) -> None:
        observation = request.observation
        for item in observation.public_log:
            if item in self._seen_public_entries:
                continue
            self._seen_public_entries.add(item)
            event = parse_public_entry(str(item), fallback_day=observation.day, fallback_phase=observation.phase.value)
            self.events.append(event)
            self._index_public_event(event)
        if len(self.events) > _MAX_EVENTS:
            self.events = self.events[-_MAX_EVENTS:]

    def _index_public_event(self, event: MemoryEvent) -> None:
        if event.event_type in {"exile_vote", "pk_vote", "sheriff_vote", "vote"} and event.actor is not None and event.target is not None:
            self.suspicions[event.target] = f"P{event.actor} 投票给 P{event.target}"
        suspected = extract_suspected_player(event.content)
        if event.actor is not None and suspected is not None:
            self.suspicions[suspected] = f"P{event.actor} 发言怀疑 P{suspected}"
        claimed_role = extract_claimed_role(event.content)
        if event.actor is not None and claimed_role is not None:
            self.claims_seen[event.actor] = claimed_role

        # Also update field notes from the same event, but skip own actions
        # (already recorded immediately in remember_action to avoid duplicates)
        if event.actor != self.player_id:
            if event.event_type in {"exile_vote", "pk_vote", "sheriff_vote", "vote"} and event.actor is not None and event.target is not None:
                self.field_notes.record_vote(event.actor, event.target, event.day, event.phase)
            if event.event_type in {"speak", "sheriff_speak", "pk_speak", "last_word", "speech"} and event.actor is not None:
                self.field_notes.record_speech(event.actor, event.content)

    def _update_field_notes(self, request: ActionRequest) -> None:
        obs = request.observation
        self.field_notes.game_state = {
            "day": obs.day,
            "phase": request.phase.value,
            "alive_players": list(obs.alive_players),
            "dead_players": list(obs.dead_players),
            "sheriff_id": obs.sheriff_id,
        }
