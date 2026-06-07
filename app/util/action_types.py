"""Centralized action type definitions and mapping.

Provides a single source of truth for valid action types across
engine (ActionType enum) and app (string-based) layers.

Since ActionType is a StrEnum, conversion is trivial:
- enum -> string: ``str(action_type)`` or ``action_type.value``
- string -> enum: ``ActionType(value)``

The real value of this module is the **category sets** — derived from
the enum so that adding a new ActionType member automatically makes it
available to all app code that references these sets, without
scattered string literals to update.
"""
from __future__ import annotations

from engine import ActionType

# ---------------------------------------------------------------------------
# All valid action type strings
# ---------------------------------------------------------------------------

#: Every valid action type string, derived from the ActionType enum.
AGENT_ACTION_TYPES: frozenset[str] = frozenset(a.value for a in ActionType)


def is_valid_action_type(value: str) -> bool:
    """Check if a string is a valid action type (matches an ActionType value)."""
    return value in AGENT_ACTION_TYPES


# ---------------------------------------------------------------------------
# Category sets — single source of truth for action classification
# ---------------------------------------------------------------------------

#: Actions that produce public speech content (text-based).
SPEECH_ACTION_TYPES: frozenset[str] = frozenset({
    ActionType.SPEAK.value,
    ActionType.SHERIFF_SPEAK.value,
    ActionType.PK_SPEAK.value,
    ActionType.LAST_WORD.value,
})

#: Actions that produce a vote (target-based, public).
VOTE_ACTION_TYPES: frozenset[str] = frozenset({
    ActionType.EXILE_VOTE.value,
    ActionType.PK_VOTE.value,
    ActionType.SHERIFF_VOTE.value,
})

#: Actions that require selecting a target player.
TARGET_ACTION_TYPES: frozenset[str] = frozenset({
    ActionType.SHERIFF_VOTE.value,
    ActionType.GUARD_PROTECT.value,
    ActionType.WEREWOLF_KILL.value,
    ActionType.SEER_CHECK.value,
    ActionType.EXILE_VOTE.value,
    ActionType.PK_VOTE.value,
    ActionType.HUNTER_SHOOT.value,
})

#: Actions that require a ``choice`` field (not target-based).
CHOICE_ACTION_TYPES: frozenset[str] = frozenset({
    ActionType.SHERIFF_RUN.value,
    ActionType.SHERIFF_WITHDRAW.value,
    ActionType.SHERIFF_BADGE.value,
    ActionType.SPEECH_ORDER.value,
    ActionType.WITCH_ACT.value,
    ActionType.WHITE_WOLF_EXPLODE.value,
})

#: Night-phase role skill actions (target-based or choice-based).
NIGHT_SKILL_ACTION_TYPES: frozenset[str] = frozenset({
    ActionType.GUARD_PROTECT.value,
    ActionType.WEREWOLF_KILL.value,
    ActionType.SEER_CHECK.value,
    ActionType.WITCH_ACT.value,
    ActionType.WHITE_WOLF_EXPLODE.value,
})

#: Sheriff-related actions (election, speak, withdraw, vote, badge).
SHERIFF_ACTION_TYPES: frozenset[str] = frozenset({
    ActionType.SHERIFF_RUN.value,
    ActionType.SHERIFF_SPEAK.value,
    ActionType.SHERIFF_WITHDRAW.value,
    ActionType.SHERIFF_VOTE.value,
    ActionType.SHERIFF_BADGE.value,
})

# ---------------------------------------------------------------------------
# Event-type categories (NOT ActionType values)
# ---------------------------------------------------------------------------

EVENT_TYPE_SPEECH: str = "speech"
EVENT_TYPE_VOTE: str = "vote"
PUBLIC_SPEECH_EVENT_TYPES: frozenset[str] = SPEECH_ACTION_TYPES | {EVENT_TYPE_SPEECH}
VOTE_EVENT_TYPES: frozenset[str] = VOTE_ACTION_TYPES | {EVENT_TYPE_VOTE}
