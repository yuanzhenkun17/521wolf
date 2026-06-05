from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Team(StrEnum):
    WEREWOLVES = "werewolves"
    VILLAGERS = "villagers"
    GODS = "gods"


class Winner(StrEnum):
    WEREWOLVES = "werewolves"
    VILLAGERS = "villagers"


class Role(StrEnum):
    WEREWOLF = "werewolf"
    WHITE_WOLF_KING = "white_wolf_king"
    VILLAGER = "villager"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    GUARD = "guard"

    @property
    def team(self) -> Team:
        if self in {Role.WEREWOLF, Role.WHITE_WOLF_KING}:
            return Team.WEREWOLVES
        if self is Role.VILLAGER:
            return Team.VILLAGERS
        return Team.GODS

    def is_good(self) -> bool:
        return self.team is not Team.WEREWOLVES

    def is_wolf(self) -> bool:
        return self.team is Team.WEREWOLVES


class Phase(StrEnum):
    SETUP = "setup"
    SHERIFF_ELECTION = "sheriff_election"
    NIGHT = "night"
    DAY_SPEECH = "day_speech"
    EXILE_VOTE = "exile_vote"
    FINISHED = "finished"


class ActionType(StrEnum):
    SHERIFF_RUN = "sheriff_run"
    SHERIFF_SPEAK = "sheriff_speak"
    SHERIFF_WITHDRAW = "sheriff_withdraw"
    SHERIFF_VOTE = "sheriff_vote"
    SHERIFF_BADGE = "sheriff_badge"
    SPEECH_ORDER = "speech_order"
    GUARD_PROTECT = "guard_protect"
    WEREWOLF_KILL = "werewolf_kill"
    SEER_CHECK = "seer_check"
    WITCH_ACT = "witch_act"
    LAST_WORD = "last_word"
    SPEAK = "speak"
    WHITE_WOLF_EXPLODE = "white_wolf_explode"
    EXILE_VOTE = "exile_vote"
    PK_SPEAK = "pk_speak"
    PK_VOTE = "pk_vote"
    HUNTER_SHOOT = "hunter_shoot"


class DeathCause(StrEnum):
    WEREWOLF = "werewolf"
    WITCH_POISON = "witch_poison"
    EXILE = "exile"
    HUNTER_SHOT = "hunter_shot"
    WHITE_WOLF = "white_wolf"
    SELF_EXPLODE = "self_explode"


@dataclass(slots=True)
class PlayerState:
    id: int
    role: Role
    alive: bool = True
    role_state: dict[str, Any] = field(default_factory=dict)
    # role_state is a role-specific TypedDict at runtime.  The shape depends
    # on ``self.role``; see ``engine.role_state_types`` for per-role definitions
    # (WitchRoleState, GuardRoleState, SeerRoleState, etc.).  The field is
    # declared as dict[str, Any] because dataclasses cannot cleanly express
    # union-typed defaults.  Use ROLE_STATE_TYPE_MAP to look up the correct
    # TypedDict for a given role value.

    @property
    def team(self) -> Team:
        return self.role.team


@dataclass(slots=True)
class DeathRecord:
    player_id: int
    cause: DeathCause
    day: int
    phase: Phase


@dataclass(slots=True)
class GameEvent:
    """Unified game event model.

    GameEvent represents a state transition that occurred during game execution.
    It is the single source of truth for all game events -- used for game logic,
    persistence, replay, and UI display.
    """
    type: str
    day: int
    phase: Phase
    actor: int | None = None
    target: int | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    public: bool = True
    message: str = ""
    index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "event_type": self.type,
            "day": self.day,
            "phase": self.phase.value if hasattr(self.phase, "value") else self.phase,
            "actor": self.actor,
            "target": self.target,
            "payload": dict(self.payload),
            "public": self.public,
            "message": self.message,
        }


@dataclass(slots=True)
class Observation:
    player_id: int
    self_role: Role
    phase: Phase
    day: int
    alive_players: tuple[int, ...]
    dead_players: tuple[int, ...]
    sheriff_id: int | None
    public_log: tuple[str, ...]
    known_roles: dict[int, Role] = field(default_factory=dict)
    seer_checks: dict[int, Team] = field(default_factory=dict)
    role_state: dict[str, Any] = field(default_factory=dict)
    # Same role-specific shape as PlayerState.role_state; see
    # engine.role_state_types for per-role TypedDict definitions.
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ActionRequest:
    player_id: int
    action_type: ActionType
    phase: Phase
    observation: Observation
    candidates: tuple[int, ...] = ()
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    # metadata carries per-action-type information.  Common shapes are
    # documented in engine.role_state_types (WitchActionMetadata,
    # SheriffWithdrawMetadata, SpeechOrderMetadata).


@dataclass(slots=True)
class ActionResponse:
    action_type: ActionType
    target: int | None = None
    choice: str | None = None
    text: str = ""
    decision_id: str | None = None


@dataclass(slots=True)
class GameState:
    players: dict[int, PlayerState]
    day: int = 0
    phase: Phase = Phase.SETUP
    public_log: list[str] = field(default_factory=list)
    deaths: list[DeathRecord] = field(default_factory=list)
    sheriff_id: int | None = None
    badge_destroyed: bool = False
    pending_last_words: list[int] = field(default_factory=list)
    pending_hunter_shots: list[int] = field(default_factory=list)
    winner: Winner | None = None
