from __future__ import annotations

from dataclasses import dataclass, field

from werewolf.models import ActionRequest, Role, Team
from playeragent.memory import AgentMemory, extract_claimed_role, extract_suspected_player


@dataclass(slots=True)
class PlayerBelief:
    player_id: int
    suspicion: float = 0.5
    trust: float = 0.5
    possible_roles: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def clamp(self) -> None:
        self.suspicion = min(1.0, max(0.0, self.suspicion))
        self.trust = min(1.0, max(0.0, self.trust))

    def add_reason(self, reason: str) -> None:
        if reason not in self.reasons:
            self.reasons.append(reason)
        self.reasons = self.reasons[-6:]

    def to_prompt_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "suspicion": round(self.suspicion, 2),
            "trust": round(self.trust, 2),
            "possible_roles": self.possible_roles,
            "reasons": self.reasons,
        }


@dataclass(slots=True)
class BeliefState:
    player_id: int
    role: Role
    players: dict[int, PlayerBelief] = field(default_factory=dict)
    _processed_memory_count: int = 0

    def update_from_request(self, request: ActionRequest, memory: AgentMemory | None = None) -> None:
        observation = request.observation
        visible_players = set(observation.alive_players) | set(observation.dead_players) | {self.player_id}
        for player_id in visible_players:
            self.players.setdefault(player_id, PlayerBelief(player_id=player_id))

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
            (belief for belief in self.players.values() if belief.player_id in alive and belief.player_id != self.player_id),
            key=lambda belief: (-belief.suspicion, belief.player_id),
        )
        return {
            "top_suspicions": [belief.to_prompt_dict() for belief in ordered[:5]],
            "self_belief": self.players[self.player_id].to_prompt_dict(),
        }

    def most_suspicious(self, candidates: tuple[int, ...]) -> list[int]:
        return [
            belief.player_id
            for belief in sorted(
                (self.players.get(player_id, PlayerBelief(player_id=player_id)) for player_id in candidates),
                key=lambda belief: (-belief.suspicion, belief.player_id),
            )
        ]

    def most_trusted(self, candidates: tuple[int, ...]) -> list[int]:
        return [
            belief.player_id
            for belief in sorted(
                (self.players.get(player_id, PlayerBelief(player_id=player_id)) for player_id in candidates),
                key=lambda belief: (-belief.trust, belief.player_id),
            )
        ]

    def _mark_self(self) -> None:
        belief = self.players.setdefault(self.player_id, PlayerBelief(player_id=self.player_id))
        belief.suspicion = 0.0
        belief.trust = 1.0
        belief.possible_roles = {self.role.value: 1.0}
        belief.add_reason("自己身份已知")

    def _apply_private_known_roles(self, request: ActionRequest) -> None:
        for known_id, role in request.observation.known_roles.items():
            belief = self.players.setdefault(known_id, PlayerBelief(player_id=known_id))
            belief.possible_roles = {role.value: 1.0}
            if role.team is Team.WEREWOLVES and self.role.team is Team.WEREWOLVES:
                belief.suspicion = 0.0
                belief.trust = 0.9
                belief.add_reason("狼人夜晚私有视角确认队友")
            belief.clamp()

    def _apply_seer_checks(self, request: ActionRequest) -> None:
        for checked_id, team in request.observation.seer_checks.items():
            belief = self.players.setdefault(checked_id, PlayerBelief(player_id=checked_id))
            if team is Team.WEREWOLVES:
                belief.suspicion = 1.0
                belief.trust = 0.0
                belief.possible_roles["werewolf"] = 0.9
                belief.add_reason("自己的预言家查验显示狼人阵营")
            else:
                belief.suspicion = 0.0
                belief.trust = 0.9
                belief.add_reason("自己的预言家查验显示好人阵营")
            belief.clamp()

    def _mark_dead_players(self, request: ActionRequest) -> None:
        for dead_id in request.observation.dead_players:
            belief = self.players.setdefault(dead_id, PlayerBelief(player_id=dead_id))
            belief.add_reason("已经出局，当前不作为行动目标")

    def _apply_memory_events(self, memory: AgentMemory) -> None:
        new_events = memory.events[self._processed_memory_count :]
        self._processed_memory_count = len(memory.events)
        for event in new_events:
            if event.actor is not None:
                self.players.setdefault(event.actor, PlayerBelief(player_id=event.actor))
            if event.target is not None:
                self.players.setdefault(event.target, PlayerBelief(player_id=event.target))
            if event.event_type in {"exile_vote", "pk_vote", "sheriff_vote", "vote"} and event.target is not None:
                self._shift_suspicion(event.target, 0.04, f"P{event.actor} 投票给 P{event.target}")
            suspected = event.target or extract_suspected_player(event.content)
            if event.event_type in {"speak", "sheriff_speak", "pk_speak", "last_word", "speech"} and suspected:
                self._shift_suspicion(suspected, 0.07, f"P{event.actor} 公开怀疑 P{suspected}")
            claimed_role = extract_claimed_role(event.content)
            if event.actor is not None and claimed_role is not None:
                belief = self.players.setdefault(event.actor, PlayerBelief(player_id=event.actor))
                belief.possible_roles[claimed_role] = max(belief.possible_roles.get(claimed_role, 0.0), 0.55)
                belief.add_reason(f"P{event.actor} 公开声称身份为 {claimed_role}")

    def _shift_suspicion(self, player_id: int, delta: float, reason: str) -> None:
        if player_id == self.player_id:
            return
        belief = self.players.setdefault(player_id, PlayerBelief(player_id=player_id))
        belief.suspicion += delta
        belief.trust -= delta / 2
        belief.add_reason(reason)
        belief.clamp()
