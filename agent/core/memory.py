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

from agent.common.action_types import (
    PUBLIC_SPEECH_EVENT_TYPES,
    VOTE_EVENT_TYPES,
    SPEECH_ACTION_TYPES,
    VOTE_ACTION_TYPES,
)
from agent.common.coercion import as_int


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

    def phase_key(self) -> tuple[int, str]:
        return (self.day, self.phase)

    def to_prompt_dict(self) -> dict[str, Any]:
        return {
            "day": self.day,
            "phase": self.phase,
            "type": self.event_type,
            "actor": self.actor,
            "target": self.target,
            "content": self.content,
            "text": self.to_prompt_text(),
        }


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


_NEGATION_PATTERNS = re.compile(r"(?:不|没|并非|没说|没有|不跳|没跳)\s{0,2}$")


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
        idx = content.find(word)
        if idx < 0:
            continue
        prefix = content[max(0, idx - 4) : idx]
        if _NEGATION_PATTERNS.search(prefix):
            continue
        return role
    return None


def extract_defended_player(content: str) -> int | None:
    patterns = [
        r"(?:保|认好|站边|相信)\s*(?:P)?(\d+)号?",
        r"(?:P)?(\d+)号?.{0,8}(?:像好人|做好|可信|金水)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if match:
            return int(match.group(1))
    return None


def extract_claimed_check(content: str) -> dict[str, Any] | None:
    patterns = [
        r"(?:查验|验了|查了)\s*(?:P)?(\d+)号?.{0,12}(?:是|为)?\s*(狼|狼人|好人|金水|查杀)",
        r"(?:P)?(\d+)号?.{0,8}(?:查验结果|验人结果).{0,8}(狼|狼人|好人|金水|查杀)",
    ]
    for pattern in patterns:
        match = re.search(pattern, content)
        if not match:
            continue
        raw_result = match.group(2)
        if raw_result in {"狼", "狼人", "查杀"}:
            result = "werewolves"
        else:
            result = "villagers"
        return {"target": int(match.group(1)), "result": result}
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

    def ensure_player(self, player_id: int) -> PlayerProfile:
        if player_id not in self.player_models:
            self.player_models[player_id] = PlayerProfile(player_id=player_id)
        return self.player_models[player_id]

    def record_speech(self, player_id: int, content: str) -> None:
        profile = self.ensure_player(player_id)
        profile.speeches.append(content)
        claimed_role = extract_claimed_role(content)
        if claimed_role is not None:
            profile.claimed_role = claimed_role
        attacked = extract_suspected_player(content)
        if attacked is not None and attacked != player_id and attacked not in profile.attacked:
            profile.attacked.append(attacked)
        defended = extract_defended_player(content)
        if defended is not None and defended != player_id and defended not in profile.defended:
            profile.defended.append(defended)

    def record_vote(self, voter: int, target: int, day: int, phase: str) -> None:
        profile = self.ensure_player(voter)
        profile.votes_cast.append({"target": target, "day": day, "phase": phase})
        target_profile = self.ensure_player(target)
        target_profile.votes_received.append(voter)
        self.vote_log.append({"voter": voter, "target": target, "day": day, "phase": phase})

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
_MAX_ROLLING_SUMMARIES = 30
_MAX_PINNED_FACTS = 80
_MAX_SELF_COMMITMENTS = 24
_HOT_PHASE_COUNT = 2

_PINNED_FACT_PRIORITY: dict[str, int] = {
    "sheriff": 5,
    "death": 4,
    "dead_player": 4,
    "role_claim": 3,
    "claimed_check": 3,
}

_PUBLIC_SPEECH_EVENTS = PUBLIC_SPEECH_EVENT_TYPES
_VOTE_EVENTS = VOTE_EVENT_TYPES


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
        self.phase_events: dict[tuple[int, str], list[MemoryEvent]] = {}
        self.phase_order: list[tuple[int, str]] = []
        self.rolling_summary: list[str] = []
        self._summarized_phase_keys: set[tuple[int, str]] = set()
        self.pinned_facts: list[dict[str, Any]] = []
        self._pinned_fact_keys: set[tuple[Any, ...]] = set()
        self.self_commitments: list[dict[str, Any]] = []

    def build_context(self, request: ActionRequest) -> dict:
        self._observe_request(request)
        self._update_field_notes(request)
        self._pin_observation_facts(request)
        self._roll_old_phases()
        observation = request.observation
        field_notes = self.field_notes.to_prompt_dict()
        ctx = {
            "private_facts": {
                "known_roles": {player_id: role.value for player_id, role in observation.known_roles.items()},
                "seer_checks": {player_id: team.value for player_id, team in observation.seer_checks.items()},
                "metadata": dict(request.metadata),
            },
            "errors": self.errors[-3:],
            "rolling_summary": list(self.rolling_summary[-_MAX_ROLLING_SUMMARIES:]),
            "pinned_facts": [
                {k: v for k, v in f.items() if k != "_stable_key"}
                for f in self.pinned_facts
            ],
            "recent_timeline": self._build_recent_timeline(),
            "player_models": field_notes.get("player_profiles", {}),
            "self_commitments": list(self.self_commitments[-_MAX_SELF_COMMITMENTS:]),
        }
        ctx["field_notes"] = field_notes
        return ctx

    def remember_action(self, request: ActionRequest, response: ActionResponse, decision: Any = None) -> None:
        # self_history and decision_history accumulation removed (unused by prompt layer)
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
        if action_type in {
            ActionType.SPEAK,
            ActionType.SHERIFF_SPEAK,
            ActionType.PK_SPEAK,
            ActionType.LAST_WORD,
            ActionType.EXILE_VOTE,
            ActionType.PK_VOTE,
            ActionType.SHERIFF_VOTE,
        }:
            self._remember_self_commitment(request, response)

    def reset(self) -> None:
        self.events = []
        self.errors = []
        self._seen_public_entries = set()
        self.field_notes = FieldNotes()
        self.phase_events = {}
        self.phase_order = []
        self.rolling_summary = []
        self._summarized_phase_keys = set()
        self.pinned_facts = []
        self._pinned_fact_keys = set()
        self.self_commitments = []

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
            self._record_phase_event(event)
            self._index_public_event(event)
        if len(self.events) > _MAX_EVENTS:
            self.events = self.events[-_MAX_EVENTS:]

    def _index_public_event(self, event: MemoryEvent) -> None:
        claimed_role = extract_claimed_role(event.content)
        claimed_check = extract_claimed_check(event.content)
        self._pin_event_fact(event, claimed_role=claimed_role, claimed_check=claimed_check)

        # Also update field notes from the same event, but skip own actions
        # (already recorded immediately in remember_action to avoid duplicates)
        if event.actor != self.player_id:
            if event.event_type in VOTE_EVENT_TYPES and event.actor is not None and event.target is not None:
                self.field_notes.record_vote(event.actor, event.target, event.day, event.phase)
            if event.event_type in PUBLIC_SPEECH_EVENT_TYPES and event.actor is not None:
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

    def _record_phase_event(self, event: MemoryEvent) -> None:
        key = event.phase_key()
        if key not in self.phase_events:
            self.phase_events[key] = []
            self.phase_order.append(key)
        self.phase_events[key].append(event)

    def _roll_old_phases(self) -> None:
        if len(self.phase_order) <= _HOT_PHASE_COUNT:
            return
        hot_keys = set(self.phase_order[-_HOT_PHASE_COUNT:])
        for key in self.phase_order:
            if key in hot_keys or key in self._summarized_phase_keys:
                continue
            summary = _summarize_phase(key, self.phase_events.get(key, []))
            if summary:
                self.rolling_summary.append(summary)
                self.rolling_summary = self.rolling_summary[-_MAX_ROLLING_SUMMARIES:]
            self._summarized_phase_keys.add(key)

    def _build_recent_timeline(self) -> list[dict[str, Any]]:
        timeline = []
        for day, phase in self.phase_order[-_HOT_PHASE_COUNT:]:
            events = self.phase_events.get((day, phase), [])
            timeline.append({
                "phase_key": _phase_label(day, phase),
                "day": day,
                "phase": phase,
                "events": [event.to_prompt_dict() for event in events],
            })
        return timeline

    def _pin_observation_facts(self, request: ActionRequest) -> None:
        obs = request.observation
        if obs.sheriff_id is not None:
            self._add_pinned_fact(
                "sheriff",
                day=obs.day,
                phase=request.phase.value,
                target=obs.sheriff_id,
                content=f"P{obs.sheriff_id} 是当前警长",
                stable_key=("sheriff", obs.sheriff_id),
            )
        for player_id in obs.dead_players:
            self._add_pinned_fact(
                "dead_player",
                day=obs.day,
                phase=request.phase.value,
                target=player_id,
                content=f"P{player_id} 已死亡",
                stable_key=("dead_player", player_id),
            )

    def _pin_event_fact(
        self,
        event: MemoryEvent,
        *,
        claimed_role: str | None = None,
        claimed_check: dict[str, Any] | None = None,
    ) -> None:
        if event.event_type == "death" and event.target is not None:
            self._add_pinned_fact(
                "death",
                day=event.day,
                phase=event.phase,
                actor=event.actor,
                target=event.target,
                content=event.content,
                stable_key=("death", event.target, event.content),
            )
        if event.actor is not None and claimed_role is not None:
            self._add_pinned_fact(
                "role_claim",
                day=event.day,
                phase=event.phase,
                actor=event.actor,
                content=f"P{event.actor} 声称 {claimed_role}",
                details={"claimed_role": claimed_role},
                stable_key=("role_claim", event.actor, claimed_role),
            )
        if event.actor is not None and claimed_check is not None:
            target = claimed_check.get("target")
            result = claimed_check.get("result")
            self._add_pinned_fact(
                "claimed_check",
                day=event.day,
                phase=event.phase,
                actor=event.actor,
                target=target,
                content=f"P{event.actor} 声称查验 P{target} = {result}",
                details={"result": result},
                stable_key=("claimed_check", event.actor, target, result),
            )

    def _add_pinned_fact(
        self,
        fact_type: str,
        *,
        day: int,
        phase: str,
        actor: int | None = None,
        target: int | None = None,
        content: str = "",
        details: dict[str, Any] | None = None,
        stable_key: tuple[Any, ...] | None = None,
    ) -> None:
        key = stable_key or (fact_type, actor, target, content)
        if key in self._pinned_fact_keys:
            return
        self._pinned_fact_keys.add(key)
        fact: dict[str, Any] = {
            "type": fact_type,
            "day": day,
            "phase": phase,
            "actor": actor,
            "target": target,
            "content": content,
            "_stable_key": key,
        }
        if details:
            fact["details"] = dict(details)
        self.pinned_facts.append(fact)
        if len(self.pinned_facts) > _MAX_PINNED_FACTS:
            self._evict_lowest_priority_fact()

    def _evict_lowest_priority_fact(self) -> None:
        """Remove the lowest-priority pinned fact. Ties broken by oldest first."""
        worst_idx = 0
        worst_priority = _PINNED_FACT_PRIORITY.get(self.pinned_facts[0]["type"], 0)
        worst_day = self.pinned_facts[0]["day"]
        for i, fact in enumerate(self.pinned_facts[1:], start=1):
            p = _PINNED_FACT_PRIORITY.get(fact["type"], 0)
            d = fact["day"]
            if p < worst_priority or (p == worst_priority and d < worst_day):
                worst_idx = i
                worst_priority = p
                worst_day = d
        evicted = self.pinned_facts.pop(worst_idx)
        evicted_key = evicted.get("_stable_key")
        if evicted_key is not None:
            self._pinned_fact_keys.discard(evicted_key)

    def _remember_self_commitment(self, request: ActionRequest, response: ActionResponse) -> None:
        commitment = {
            "day": request.observation.day,
            "phase": request.phase.value,
            "action_type": request.action_type.value,
            "choice": response.choice,
            "target": response.target,
            "text": _clip(response.text, 180),
        }
        if response.text:
            claimed_role = extract_claimed_role(response.text)
            if claimed_role is not None:
                commitment["claimed_role"] = claimed_role
            suspected = extract_suspected_player(response.text)
            if suspected is not None:
                commitment["suspected_player"] = suspected
        self.self_commitments.append(commitment)
        self.self_commitments = self.self_commitments[-_MAX_SELF_COMMITMENTS:]


def _phase_label(day: int, phase: str) -> str:
    return f"day{day}/{phase}"


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _summarize_phase(key: tuple[int, str], events: list[MemoryEvent]) -> str:
    day, phase = key
    if not events:
        return f"{_phase_label(day, phase)}: 无公开事件"

    deaths: list[str] = []
    votes: list[str] = []
    speeches: list[str] = []
    claims: list[str] = []
    checks: list[str] = []
    others: list[str] = []

    for event in events:
        actor = f"P{event.actor}" if event.actor is not None else "系统"
        target = f"P{event.target}" if event.target is not None else "无目标"
        if event.event_type == "death":
            deaths.append(f"{target}死亡")
            continue
        if event.event_type in _VOTE_EVENTS:
            votes.append(f"{actor}->{target}")
            continue
        claimed_role = extract_claimed_role(event.content)
        if claimed_role is not None and event.actor is not None:
            claims.append(f"{actor}声称{claimed_role}")
        claimed_check = extract_claimed_check(event.content)
        if claimed_check is not None and event.actor is not None:
            checks.append(
                f"{actor}报查验P{claimed_check.get('target')}={claimed_check.get('result')}"
            )
        if event.event_type in _PUBLIC_SPEECH_EVENTS:
            suspected = extract_suspected_player(event.content)
            defended = extract_defended_player(event.content)
            parts: list[str] = []
            if suspected is not None:
                parts.append(f"怀疑P{suspected}")
            if defended is not None:
                parts.append(f"认好P{defended}")
            if claimed_role is not None:
                parts.append(f"声称{claimed_role}")
            if parts:
                speeches.append(f"{actor}: {'，'.join(parts)}")
            elif event.content:
                speeches.append(f"{actor}: {_clip(event.content, 60)}")
            continue
        if event.content:
            others.append(f"{event.event_type} {actor}->{target}: {_clip(event.content, 60)}")

    sections: list[str] = []
    if deaths:
        sections.append("死亡 " + "，".join(deaths[:6]))
    if claims:
        sections.append("身份声明 " + "，".join(_dedupe(claims)[:8]))
    if checks:
        sections.append("查验声明 " + "，".join(_dedupe(checks)[:8]))
    if speeches:
        shown = speeches[:8]
        suffix = f"，另有{len(speeches) - len(shown)}条发言" if len(speeches) > len(shown) else ""
        sections.append("发言要点 " + "；".join(shown) + suffix)
    if votes:
        shown = votes[:12]
        suffix = f"，另有{len(votes) - len(shown)}票" if len(votes) > len(shown) else ""
        sections.append("票型 " + "，".join(shown) + suffix)
    if others:
        sections.append("其他 " + "；".join(others[:6]))
    if not sections:
        sections.append(f"{len(events)}条公开事件")
    return f"{_phase_label(day, phase)}: " + "；".join(sections)


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
