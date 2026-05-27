"""Belief with probability split, evidence tracking, and relations.

Features:
- wolf_prob / villager_prob / god_prob split per player
- Evidence items with type and weight
- Player relationship graph (attacks, protects, follows, votes_together)
- Stance classification
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.models import ActionRequest, Role, Team

from agent.cognition.memory import AgentMemory
from agent.cognition.memory import extract_claimed_role, extract_suspected_player


@dataclass(slots=True)
class EvidenceItem:
    type: str  # "vote", "speech", "claim", "known_role", "seer_check", "death"
    weight: float
    description: str

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "weight": self.weight,
            "description": self.description,
        }


@dataclass(slots=True)
class PlayerBelief:
    player_id: int
    wolf_prob: float = 0.33
    villager_prob: float = 0.33
    god_prob: float = 0.34
    claimed_role: str | None = None
    stance: str = "neutral"  # "attacks_seer", "defends_seer", "neutral"
    evidence: list[EvidenceItem] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def clamp(self) -> None:
        total = self.wolf_prob + self.villager_prob + self.god_prob
        if total > 0:
            scale = 1.0 / total
            self.wolf_prob *= scale
            self.villager_prob *= scale
            self.god_prob *= scale

    def add_evidence(self, etype: str, weight: float, description: str) -> None:
        self.evidence.append(EvidenceItem(etype, weight, description))
        self.evidence = self.evidence[-10:]
        if description not in self.reasons:
            self.reasons.append(description)
        self.reasons = self.reasons[-8:]

    def to_prompt_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "wolf_prob": round(self.wolf_prob, 2),
            "villager_prob": round(self.villager_prob, 2),
            "god_prob": round(self.god_prob, 2),
            "claimed_role": self.claimed_role,
            "stance": self.stance,
            "top_evidence": [e.to_dict() for e in self.evidence[-5:]],
            "reasons": self.reasons,
        }


@dataclass(slots=True)
class RelationGraph:
    """Tracks relationships between players."""

    relations: list[dict] = field(default_factory=list)

    def add(self, source: int, target: int, rel_type: str, weight: float = 0.5) -> None:
        self.relations.append({
            "source": source,
            "target": target,
            "type": rel_type,
            "weight": weight,
        })
        # Keep last 30 relations
        self.relations = self.relations[-30:]

    def to_list(self) -> list[dict]:
        return self.relations[-20:]


@dataclass(slots=True)
class BeliefState:
    """Enhanced belief state with probability split and relationship graph."""

    player_id: int
    role: Role
    players: dict[int, PlayerBelief] = field(default_factory=dict)
    relations: RelationGraph = field(default_factory=RelationGraph)
    _processed_memory_count: int = 0

    def update_from_request(self, request: ActionRequest, memory: AgentMemory | None = None) -> None:
        observation = request.observation
        visible = set(observation.alive_players) | set(observation.dead_players) | {self.player_id}
        for pid in visible:
            self.players.setdefault(pid, PlayerBelief(player_id=pid))

        if memory is not None:
            self._apply_memory_events(memory)
        self._apply_private_known_roles(request)
        self._apply_seer_checks(request)
        self._mark_dead_players(request)
        self._mark_self()

    def build_context(self, request: ActionRequest, memory: AgentMemory | None = None) -> dict:
        self.update_from_request(request, memory)
        alive = set(request.observation.alive_players)
        ordered = sorted(
            (b for b in self.players.values() if b.player_id in alive and b.player_id != self.player_id),
            key=lambda b: (-b.wolf_prob, b.player_id),
        )
        return {
            "top_suspicions": [b.to_prompt_dict() for b in ordered[:5]],
            "self_belief": self.players[self.player_id].to_prompt_dict(),
            "relations": self.relations.to_list(),
        }

    def most_suspicious(self, candidates: tuple[int, ...]) -> list[int]:
        return [
            b.player_id
            for b in sorted(
                (self.players.get(pid, PlayerBelief(player_id=pid)) for pid in candidates),
                key=lambda b: (-b.wolf_prob, b.player_id),
            )
        ]

    def most_trusted(self, candidates: tuple[int, ...]) -> list[int]:
        return [
            b.player_id
            for b in sorted(
                (self.players.get(pid, PlayerBelief(player_id=pid)) for pid in candidates),
                key=lambda b: (-b.villager_prob - b.god_prob, b.player_id),
            )
        ]

    def _mark_self(self) -> None:
        b = self.players.setdefault(self.player_id, PlayerBelief(player_id=self.player_id))
        if self.role.team is Team.WEREWOLVES:
            b.wolf_prob = 1.0
            b.villager_prob = 0.0
            b.god_prob = 0.0
        else:
            b.wolf_prob = 0.0
            b.villager_prob = 0.5
            b.god_prob = 0.5
        b.add_evidence("known_role", 1.0, "自己身份已知")
        b.clamp()

    def _apply_private_known_roles(self, request: ActionRequest) -> None:
        for known_id, role in request.observation.known_roles.items():
            b = self.players.setdefault(known_id, PlayerBelief(player_id=known_id))
            if role.team is Team.WEREWOLVES and self.role.team is Team.WEREWOLVES:
                b.wolf_prob = 1.0
                b.villager_prob = 0.0
                b.god_prob = 0.0
                b.add_evidence("known_role", 0.9, "狼人夜晚私有视角确认队友")
                self.relations.add(self.player_id, known_id, "teammate", 0.9)
            b.clamp()

    def _apply_seer_checks(self, request: ActionRequest) -> None:
        for checked_id, team in request.observation.seer_checks.items():
            b = self.players.setdefault(checked_id, PlayerBelief(player_id=checked_id))
            if team is Team.WEREWOLVES:
                b.wolf_prob = 0.9
                b.villager_prob = 0.05
                b.god_prob = 0.05
                b.add_evidence("seer_check", 0.8, "自己的预言家查验显示狼人阵营")
            else:
                b.wolf_prob = 0.05
                b.villager_prob = 0.8
                b.god_prob = 0.15
                b.add_evidence("seer_check", 0.8, "自己的预言家查验显示好人阵营")
            b.clamp()

    def _mark_dead_players(self, request: ActionRequest) -> None:
        for dead_id in request.observation.dead_players:
            b = self.players.setdefault(dead_id, PlayerBelief(player_id=dead_id))
            b.add_evidence("death", 0.3, "已经出局")

    def reset(self) -> None:
        self._processed_memory_count = 0

    def _apply_memory_events(self, memory: AgentMemory) -> None:
        new_events = memory.events[self._processed_memory_count:]
        self._processed_memory_count = len(memory.events)
        for event in new_events:
            if event.actor is not None:
                self.players.setdefault(event.actor, PlayerBelief(player_id=event.actor))
            if event.target is not None:
                self.players.setdefault(event.target, PlayerBelief(player_id=event.target))

            # Vote patterns
            if event.event_type in {"exile_vote", "pk_vote", "sheriff_vote", "vote"}:
                if event.actor is not None and event.target is not None and event.target != self.player_id:
                    self._shift_wolf_prob(event.target, 0.05, f"P{event.actor} 投票给 P{event.target}", "vote")
                    self.relations.add(event.actor, event.target, "votes_against", 0.3)

            # Speech suspicion
            suspected = event.target or extract_suspected_player(event.content)
            if event.event_type in {"speak", "sheriff_speak", "pk_speak", "last_word", "speech"}:
                if event.actor is not None and suspected is not None and suspected != self.player_id:
                    self._shift_wolf_prob(suspected, 0.08, f"P{event.actor} 公开怀疑 P{suspected}", "speech")
                    self.relations.add(event.actor, suspected, "attacks", 0.4)

            # Role claims
            claimed_role = extract_claimed_role(event.content)
            if event.actor is not None and claimed_role is not None:
                b = self.players.setdefault(event.actor, PlayerBelief(player_id=event.actor))
                b.claimed_role = claimed_role
                if claimed_role == "seer":
                    b.god_prob = max(b.god_prob, 0.7)
                    b.wolf_prob = min(b.wolf_prob, 0.3)
                    b.add_evidence("claim", 0.5, f"P{event.actor} 公开声称身份为预言家")

    def _shift_wolf_prob(self, player_id: int, delta: float, reason: str, etype: str) -> None:
        if player_id == self.player_id:
            return
        b = self.players.setdefault(player_id, PlayerBelief(player_id=player_id))
        b.wolf_prob += delta
        b.villager_prob -= delta * 0.6
        b.god_prob -= delta * 0.4
        b.add_evidence(etype, abs(delta), reason)
        b.clamp()
