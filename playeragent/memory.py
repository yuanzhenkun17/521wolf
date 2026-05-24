from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from werewolf.models import ActionRequest, ActionResponse, Role

from playeragent.decision import DecisionRecord


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


@dataclass(slots=True)
class AgentMemory:
    player_id: int
    role: Role
    events: list[MemoryEvent] = field(default_factory=list)
    self_history: list[str] = field(default_factory=list)
    decision_history: list[DecisionRecord] = field(default_factory=list)
    suspicions: dict[int, str] = field(default_factory=dict)
    claims_seen: dict[int, str] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    _seen_public_entries: set[str] = field(default_factory=set)

    def observe_request(self, request: ActionRequest) -> None:
        observation = request.observation
        for item in observation.public_log:
            if item in self._seen_public_entries:
                continue
            self._seen_public_entries.add(item)
            event = parse_public_entry(str(item), fallback_day=observation.day, fallback_phase=observation.phase.value)
            self.events.append(event)
            self._index_public_event(event)

    def build_context(self, request: ActionRequest) -> dict:
        self.observe_request(request)
        observation = request.observation
        return {
            "public_summary": list(observation.public_log[-12:]),
            "memory_events": [event.to_prompt_text() for event in self.events[-16:]],
            "private_facts": {
                "known_roles": {player_id: role.value for player_id, role in observation.known_roles.items()},
                "seer_checks": {player_id: team.value for player_id, team in observation.seer_checks.items()},
                "metadata": dict(request.metadata),
            },
            "self_history": self.self_history[-8:],
            "decisions": [decision.private_reasoning for decision in self.decision_history[-5:] if decision.private_reasoning],
            "suspicions": dict(self.suspicions),
            "claims_seen": dict(self.claims_seen),
            "errors": self.errors[-3:],
        }

    def remember_action(
        self,
        request: ActionRequest,
        response: ActionResponse,
        decision: DecisionRecord | None = None,
    ) -> None:
        self.self_history.append(
            f"{request.action_type.value}: choice={response.choice!r} target={response.target!r} text={response.text!r}"
        )
        if decision is not None:
            self.decision_history.append(decision)

    def remember_error(self, message: str) -> None:
        self.errors.append(message)

    def _index_public_event(self, event: MemoryEvent) -> None:
        if event.event_type in {"exile_vote", "pk_vote", "sheriff_vote"} and event.target is not None:
            self.suspicions[event.target] = f"P{event.actor} 投票给 P{event.target}"
        suspected = extract_suspected_player(event.content)
        if suspected is not None:
            self.suspicions[suspected] = f"P{event.actor} 发言怀疑 P{suspected}"
        claimed_role = extract_claimed_role(event.content)
        if event.actor is not None and claimed_role is not None:
            self.claims_seen[event.actor] = claimed_role


def parse_public_entry(item: str, *, fallback_day: int, fallback_phase: str) -> MemoryEvent:
    try:
        data = json.loads(item)
    except json.JSONDecodeError:
        return parse_legacy_public_entry(item, fallback_day=fallback_day, fallback_phase=fallback_phase)
    if not isinstance(data, dict):
        return parse_legacy_public_entry(item, fallback_day=fallback_day, fallback_phase=fallback_phase)
    return MemoryEvent(
        day=int(data.get("day") or fallback_day),
        phase=str(data.get("phase") or fallback_phase),
        event_type=str(data.get("type") or "public_log"),
        actor=as_int(data.get("actor")),
        target=as_int(data.get("target")),
        content=str(data.get("content") or ""),
        visibility=str(data.get("visibility") or "public"),
    )


def parse_legacy_public_entry(item: str, *, fallback_day: int, fallback_phase: str) -> MemoryEvent:
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


def as_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
