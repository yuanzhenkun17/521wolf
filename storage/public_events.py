"""Helpers for enforcing public event archive boundaries."""

from __future__ import annotations

from typing import Any


_PRIVATE_VISIBILITIES = {"private", "god"}
_PUBLIC_PAYLOAD_REDACT_KEYS = {
    "antidote_used",
    "killedTarget",
    "killed_target",
    "poisonTarget",
    "poisonedTarget",
    "poisoned_target",
    "poison_target",
    "protectedTarget",
    "protected_target",
    "roles",
    "saved",
    "used_antidote",
}
_NIGHT_OUTCOME_EVENT_TYPES = {
    "death_result",
    "night_death",
    "night_death_reveal",
    "night_end",
    "night_result",
}


def is_public_event(event: dict[str, Any]) -> bool:
    """Return whether an event may be copied into public archives."""
    if not isinstance(event, dict):
        return False
    visibility = str(event.get("visibility") or "").lower()
    if visibility in _PRIVATE_VISIBILITIES:
        return False
    return _public_flag(event.get("public"), default=True)


def sanitize_public_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Return a payload safe for public event streams and archives."""
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if _is_public_night_outcome(event):
        return {
            key: _sanitize_public_death_value(value) if key in {"dead_players", "death_ids", "deaths"} else value
            for key, value in payload.items()
            if key in {"dead_players", "death_ids", "deaths", "deferred_death_reveal"}
        }
    return {key: value for key, value in payload.items() if key not in _PUBLIC_PAYLOAD_REDACT_KEYS}


def sanitize_public_event(event: dict[str, Any]) -> dict[str, Any] | None:
    """Return a public-safe copy of an event, or None when it is private."""
    if not is_public_event(event):
        return None
    sanitized = dict(event)
    payload = sanitize_public_payload(event)
    if payload or "payload" in sanitized:
        sanitized["payload"] = payload
    if "public" in sanitized:
        sanitized["public"] = True
    if "visibility" in sanitized:
        sanitized["visibility"] = "public"
    return sanitized


def public_events_only(events: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, Any]]:
    """Filter and sanitize events for games.public_events/archive use."""
    sanitized: list[dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        item = sanitize_public_event(event)
        if item is not None:
            sanitized.append(item)
    return sanitized


def _is_public_night_outcome(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or event.get("type") or event.get("action") or event.get("action_type") or "")
    phase = str(event.get("phase") or "").lower()
    return event_type in _NIGHT_OUTCOME_EVENT_TYPES or (event_type == "death" and phase == "night")


def _sanitize_public_death_value(value: Any) -> Any:
    values = value if isinstance(value, list) else [value]
    sanitized: list[Any] = []
    for item in values:
        if isinstance(item, dict):
            player_id = _int_or_none(item.get("id") or item.get("player_id") or item.get("seat"))
            if player_id is not None:
                sanitized.append(player_id)
            continue
        sanitized.append(item)
    return sanitized if isinstance(value, list) else (sanitized[0] if sanitized else None)


def _int_or_none(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _public_flag(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"0", "false", "no", "private"}:
            return False
        if text in {"1", "true", "yes", "public"}:
            return True
    return bool(value)
