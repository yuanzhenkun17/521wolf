"""Target id extraction helpers for mixed archive schemas."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from engine import ActionType


DECISION_TARGET_KEYS: tuple[str, ...] = (
    "selected_target",
    "target",
    "target_id",
)

EVENT_TARGET_KEYS: tuple[str, ...] = (
    "target",
    "target_id",
    "selected_target",
)

REQUIRED_TARGET_ACTION_TYPES: frozenset[str] = frozenset({
    ActionType.SEER_CHECK.value,
    ActionType.GUARD_PROTECT.value,
    ActionType.WEREWOLF_KILL.value,
})


def read_target_id(
    *rows: Mapping[str, Any] | None,
    keys: tuple[str, ...] = DECISION_TARGET_KEYS,
    include_payload: bool = False,
) -> int | None:
    """Return the first integer target id found in direct or payload fields."""
    for row in rows:
        target = _read_from_mapping(row, keys)
        if target is not None:
            return target
        if include_payload and isinstance(row, Mapping):
            payload = _dict_value(row.get("payload"))
            target = _read_from_mapping(payload, keys)
            if target is not None:
                return target
    return None


def target_required_for_action(action_type: ActionType | str) -> bool:
    """Return whether the action contract requires a concrete player target."""
    return _action_type_value(action_type) in REQUIRED_TARGET_ACTION_TYPES


def target_in_candidates(target: Any, candidates: tuple[int, ...] | list[int]) -> bool:
    target_id = _as_int(target)
    if target_id is None:
        return False
    return target_id in {_as_int(candidate) for candidate in candidates}


def first_candidate_target(candidates: tuple[int, ...] | list[int]) -> int | None:
    for candidate in candidates:
        target = _as_int(candidate)
        if target is not None:
            return target
    return None


def _read_from_mapping(row: Mapping[str, Any] | None, keys: tuple[str, ...]) -> int | None:
    if not isinstance(row, Mapping):
        return None
    for key in keys:
        target = _as_int(row.get(key))
        if target is not None:
            return target
    return None


def _dict_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text or text[0] != "{":
        return {}
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return dict(decoded) if isinstance(decoded, Mapping) else {}


def _action_type_value(action_type: ActionType | str) -> str:
    return action_type.value if isinstance(action_type, ActionType) else str(action_type)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
