"""Belief with weighted evidence, probability split, and relations.

Features:
- wolf/villager/god scores normalized into probabilities
- Evidence items with type, direction, source, and weight
- Player relationship graph (attacks, protects, follows, votes_together)
- Stance classification
"""

from __future__ import annotations

from dataclasses import dataclass, field

from engine.models import ActionRequest, Role, Team

from agent.cognition.memory import AgentMemory, MemoryEvent
from agent.cognition.memory import extract_claimed_role, extract_suspected_player


@dataclass(slots=True)
class EvidenceItem:
    type: str  # "vote", "speech", "claim", "known_role", "seer_check", "death"
    weight: float
    description: str
    direction: str = "neutral"  # "wolf" | "villager" | "god" | "neutral"
    source: int | None = None

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "weight": self.weight,
            "description": self.description,
            "direction": self.direction,
            "source": self.source,
        }


@dataclass(slots=True)
class PlayerBelief:
    player_id: int
    wolf_prob: float = 0.33
    villager_prob: float = 0.33
    god_prob: float = 0.34
    wolf_score: float = 1.0
    villager_score: float = 1.0
    god_score: float = 1.0
    claimed_role: str | None = None
    stance: str = "neutral"  # "attacks_seer", "defends_seer", "neutral"
    evidence: list[EvidenceItem] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    _evidence_keys: set[str] = field(default_factory=set)

    def clamp(self) -> None:
        self.wolf_score = max(0.05, self.wolf_score)
        self.villager_score = max(0.05, self.villager_score)
        self.god_score = max(0.05, self.god_score)
        total = self.wolf_score + self.villager_score + self.god_score
        if total > 0:
            self.wolf_prob = self.wolf_score / total
            self.villager_prob = self.villager_score / total
            self.god_prob = self.god_score / total

    def set_certainty(self, *, wolf: float, villager: float, god: float) -> None:
        """Set hard belief scores for private facts such as self role or checks."""
        self.wolf_score = max(0.05, wolf)
        self.villager_score = max(0.05, villager)
        self.god_score = max(0.05, god)
        self.clamp()

    def add_evidence(
        self,
        etype: str,
        weight: float,
        description: str,
        *,
        direction: str = "neutral",
        source: int | None = None,
    ) -> None:
        key = f"{etype}|{direction}|{source}|{description}"
        if key in self._evidence_keys:
            return
        self._evidence_keys.add(key)

        self.evidence.append(EvidenceItem(etype, weight, description, direction, source))
        if len(self.evidence) > 10:
            self.evidence = self.evidence[-10:]
            self._evidence_keys = {
                f"{e.type}|{e.direction}|{e.source}|{e.description}" for e in self.evidence
            }
        if description not in self.reasons:
            self.reasons.append(description)
        self.reasons = self.reasons[-8:]
        self.apply_weight(direction, weight)

    def apply_weight(self, direction: str, weight: float) -> None:
        """Apply directional evidence to scores, then normalize probabilities.

        This is intentionally an interpretable scoring model, not strict
        Bayesian inference. Evidence can support wolf/villager/god hypotheses
        or remain neutral while still being preserved for explanations.
        """
        if weight <= 0:
            return
        if direction == "wolf":
            self.wolf_score += weight
            self.villager_score -= weight * 0.35
            self.god_score -= weight * 0.25
        elif direction == "villager":
            self.villager_score += weight
            self.wolf_score -= weight * 0.45
        elif direction == "god":
            self.god_score += weight
            self.wolf_score -= weight * 0.35
        elif direction == "good":
            self.villager_score += weight * 0.6
            self.god_score += weight * 0.4
            self.wolf_score -= weight * 0.45
        self.clamp()

    def to_prompt_dict(self) -> dict:
        positive = [e.to_dict() for e in self.evidence if e.direction in {"wolf", "god"}]
        negative = [e.to_dict() for e in self.evidence if e.direction in {"villager", "good"}]
        return {
            "player_id": self.player_id,
            "wolf_prob": round(self.wolf_prob, 2),
            "villager_prob": round(self.villager_prob, 2),
            "god_prob": round(self.god_prob, 2),
            "scores": {
                "wolf": round(self.wolf_score, 2),
                "villager": round(self.villager_score, 2),
                "god": round(self.god_score, 2),
            },
            "claimed_role": self.claimed_role,
            "stance": self.stance,
            "top_evidence": [e.to_dict() for e in self.evidence[-5:]],
            "notable_evidence": positive[-3:],
            "good_evidence": negative[-3:],
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
    _known_relation_ids: set[int] = field(default_factory=set)

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

        def _has_evidence(b: PlayerBelief) -> bool:
            return bool(b.evidence)

        ordered = sorted(
            (b for b in self.players.values()
             if b.player_id in alive and b.player_id != self.player_id and _has_evidence(b)),
            key=lambda b: (-b.wolf_prob, b.player_id),
        )
        return {
            "top_suspicions": [b.to_prompt_dict() for b in ordered],
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
            b.set_certainty(wolf=20.0, villager=0.05, god=0.05)
            direction = "wolf"
        else:
            b.set_certainty(wolf=0.05, villager=2.0, god=2.0)
            direction = "good"
        b.add_evidence("known_role", 1.0, "自己身份已知", direction=direction)

    def _apply_private_known_roles(self, request: ActionRequest) -> None:
        for known_id, role in request.observation.known_roles.items():
            b = self.players.setdefault(known_id, PlayerBelief(player_id=known_id))
            if role.team is Team.WEREWOLVES and self.role.team is Team.WEREWOLVES:
                b.set_certainty(wolf=18.0, villager=0.05, god=0.05)
                b.add_evidence(
                    "known_role",
                    0.9,
                    "狼人夜晚私有视角确认队友",
                    direction="wolf",
                    source=self.player_id,
                )
                if known_id not in self._known_relation_ids:
                    self._known_relation_ids.add(known_id)
                    self.relations.add(self.player_id, known_id, "teammate", 0.9)

    def _apply_seer_checks(self, request: ActionRequest) -> None:
        for checked_id, team in request.observation.seer_checks.items():
            b = self.players.setdefault(checked_id, PlayerBelief(player_id=checked_id))
            if team is Team.WEREWOLVES:
                b.set_certainty(wolf=12.0, villager=0.5, god=0.5)
                b.add_evidence(
                    "seer_check",
                    0.95,
                    "自己的预言家查验显示狼人阵营",
                    direction="wolf",
                    source=self.player_id,
                )
            else:
                b.set_certainty(wolf=0.3, villager=7.0, god=1.5)
                b.add_evidence(
                    "seer_check",
                    0.9,
                    "自己的预言家查验显示好人阵营",
                    direction="good",
                    source=self.player_id,
                )

    def _mark_dead_players(self, request: ActionRequest) -> None:
        for dead_id in request.observation.dead_players:
            b = self.players.setdefault(dead_id, PlayerBelief(player_id=dead_id))
            b.add_evidence("death", 0.1, "已经出局")

    def reset(self) -> None:
        self._processed_memory_count = 0
        self._known_relation_ids.clear()

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
                    self._apply_vote_evidence(event.actor, event.target, event.day)
                    self.relations.add(event.actor, event.target, "votes_against", 0.3)

            # Speech suspicion
            suspected = event.target or extract_suspected_player(event.content)
            if event.event_type in {"speak", "sheriff_speak", "pk_speak", "last_word", "speech"}:
                if event.actor is not None and suspected is not None and suspected != self.player_id:
                    self._apply_speech_suspicion(event.actor, suspected)
                    self.relations.add(event.actor, suspected, "attacks", 0.4)

            # Role claims
            claimed_role = extract_claimed_role(event.content)
            if event.actor is not None and claimed_role is not None:
                b = self.players.setdefault(event.actor, PlayerBelief(player_id=event.actor))
                b.claimed_role = claimed_role
                if claimed_role == "seer":
                    b.add_evidence(
                        "claim",
                        0.35,
                        f"P{event.actor} 公开声称身份为预言家",
                        direction="god",
                        source=event.actor,
                    )
                    b.add_evidence(
                        "claim_risk",
                        0.12,
                        f"P{event.actor} 跳预言家也可能是悍跳",
                        direction="wolf",
                        source=event.actor,
                    )

            if event.event_type == "death" and event.target is not None:
                self._apply_death_evidence(event)

    def _apply_vote_evidence(self, voter: int, target: int, day: int) -> None:
        voter_belief = self.players.setdefault(voter, PlayerBelief(player_id=voter))
        target_belief = self.players.setdefault(target, PlayerBelief(player_id=target))
        voter_trust = _source_trust(voter_belief)
        wolf_weight = 0.08 * voter_trust
        good_weight = 0.08 * voter_belief.wolf_prob

        if wolf_weight >= good_weight:
            target_belief.add_evidence(
                "vote",
                wolf_weight,
                f"P{voter} 投票给 P{target}",
                direction="wolf",
                source=voter,
            )
        else:
            target_belief.add_evidence(
                "vote",
                good_weight,
                f"高狼面 P{voter} 投票给 P{target}，目标反而偏好",
                direction="good",
                source=voter,
            )

        # Late-day untrusted votes are evidence against the voter too.
        if day >= 2 and voter_belief.wolf_prob > 0.5:
            voter_belief.add_evidence(
                "vote_pattern",
                0.06,
                f"P{voter} 在中后期投票，需警惕冲票或跟风",
                direction="wolf",
                source=voter,
            )

    def _apply_speech_suspicion(self, speaker: int, suspected: int) -> None:
        speaker_belief = self.players.setdefault(speaker, PlayerBelief(player_id=speaker))
        target_belief = self.players.setdefault(suspected, PlayerBelief(player_id=suspected))
        speaker_trust = _source_trust(speaker_belief)
        wolf_weight = 0.10 * speaker_trust
        good_weight = 0.10 * speaker_belief.wolf_prob

        if wolf_weight >= good_weight:
            target_belief.add_evidence(
                "speech",
                wolf_weight,
                f"P{speaker} 公开怀疑 P{suspected}",
                direction="wolf",
                source=speaker,
            )
        else:
            target_belief.add_evidence(
                "speech",
                good_weight,
                f"高狼面 P{speaker} 公开踩 P{suspected}，目标反而偏好",
                direction="good",
                source=speaker,
            )

    def _apply_death_evidence(self, event: MemoryEvent) -> None:
        target = event.target
        if target is None:
            return
        b = self.players.setdefault(target, PlayerBelief(player_id=target))
        content = event.content.lower()
        if "werewolf" in content or "狼刀" in content or "night" in event.phase.lower():
            b.add_evidence(
                "death",
                0.35,
                f"P{target} 夜间死亡，通常更偏好人或神职",
                direction="good",
            )
        elif "white_wolf" in content or "白狼王" in content:
            b.add_evidence(
                "death",
                0.3,
                f"P{target} 被白狼王带走，通常偏好人或神职",
                direction="good",
            )
        else:
            b.add_evidence("death", 0.1, f"P{target} 已出局")


def _source_trust(source: PlayerBelief) -> float:
    """Convert source belief into a rough credibility weight.

    Confirmed or likely good players should make their accusations count more.
    High-wolf-probability sources should not mechanically increase the target's
    wolf probability, because wolves often push good players.
    """
    return min(1.0, max(0.15, 1.0 - source.wolf_prob))
