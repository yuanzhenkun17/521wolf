"""TypedDict definitions for role_state and action metadata fields.

These types provide IDE-visible field names and value types for the
otherwise-untyped ``dict[str, Any]`` containers used throughout the engine.

Usage:
    - ``PlayerState.role_state`` stores a role-specific TypedDict whose shape
      depends on ``PlayerState.role``.  Because dataclasses cannot express
      union-typed fields cleanly, ``role_state`` remains ``dict[str, Any]``
      at the dataclass level.  Use the type aliases below when you know the
      role and want static type narrowing:

          from engine.role_state_types import WitchRoleState
          ws: WitchRoleState = player.role_state  # type: ignore[assignment]

    - ``ActionRequest.metadata`` carries per-action-type metadata.  The
      typed dicts below document the most common shapes so that downstream
      code (agents, UI) can reference field names with confidence.
"""

from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# History entry shared by Witch, Guard, and Seer checks
# ---------------------------------------------------------------------------

class DayTargetEntry(TypedDict):
    """A lightweight history record pairing a day number with a target seat."""
    day: int
    target: int


class SeerCheckEntry(TypedDict):
    """One seer-check record stored inside ``SeerRoleState.checks``."""
    day: int
    target: int
    result: str  # Seer result Team value: "werewolves" or "villagers"


# ---------------------------------------------------------------------------
# Role-specific role_state TypedDicts
# ---------------------------------------------------------------------------

class WitchRoleState(TypedDict):
    antidote_available: bool
    poison_available: bool
    antidote_history: list[DayTargetEntry]
    poison_history: list[DayTargetEntry]


class GuardRoleState(TypedDict):
    last_target: int | None
    protect_history: list[DayTargetEntry]


class SeerRoleState(TypedDict):
    checks: dict[str, SeerCheckEntry]  # keyed by str(target_id)


class HunterRoleState(TypedDict):
    has_shot: bool
    shot_target: int | None


class WhiteWolfKingRoleState(TypedDict):
    has_exploded: bool


# ---------------------------------------------------------------------------
# Union type alias – maps a Role to its corresponding role_state type
# ---------------------------------------------------------------------------

# At runtime role_state is always dict[str, Any]; this mapping is for
# documentation and optional static-analysis use only.
ROLE_STATE_TYPE_MAP: dict[str, type] = {
    "witch": WitchRoleState,
    "guard": GuardRoleState,
    "seer": SeerRoleState,
    "hunter": HunterRoleState,
    "white_wolf_king": WhiteWolfKingRoleState,
    # werewolf and villager have empty role_state (no typed dict needed)
}


# ---------------------------------------------------------------------------
# ActionRequest.metadata TypedDicts
# ---------------------------------------------------------------------------

class WitchActionMetadata(TypedDict):
    """Metadata attached to ``ActionType.WITCH_ACT`` requests."""
    attacked_player: int | None
    can_save: bool
    can_poison: bool


class SheriffWithdrawMetadata(TypedDict):
    """Metadata attached to ``ActionType.SHERIFF_WITHDRAW`` requests."""
    initial_runners: list[int]
    runners: list[int]
    remaining_runners: list[int]


class SpeechOrderMetadata(TypedDict):
    """Metadata attached to ``ActionType.SPEECH_ORDER`` requests."""
    choices: list[str]  # always ["forward", "reverse"]
