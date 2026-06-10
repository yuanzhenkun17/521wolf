"""Game read-model projection helpers."""

from __future__ import annotations

from typing import Any

from storage.game_history_rules import (
    AUTHORITATIVE_DEATH_EVENTS as _AUTHORITATIVE_DEATH_EVENTS,
    NIGHT_OUTCOME_EVENTS as _NIGHT_OUTCOME_EVENTS,
    VOTE_ACTION_TYPES as _VOTE_ACTION_TYPES,
    death_target_ids,
    empty_phase_summary as _empty_phase_summary,
    history_phase_key,
    normalize_history_day as _normalize_history_day,
    normalize_history_phase,
    phase_sort as _phase_sort,
    row_history_phase,
    row_type as _row_type,
    sheriff_id_after_log,
)
from storage.game_read_payloads import (
    event_row as _event_row,
    first_value as _first_value,
    int_or_none as _int_or_none,
)


def history_phase_map(
    event_phase_rows: list[dict[str, Any]],
    decision_phase_rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    phases: dict[str, dict[str, Any]] = {}

    def ensure(day: Any, phase: Any) -> dict[str, Any]:
        normalized_day = _normalize_history_day(day)
        normalized_phase = normalize_history_phase(phase)
        key = history_phase_key(normalized_day, normalized_phase)
        if key not in phases:
            phases[key] = _empty_phase_summary(normalized_day, normalized_phase)
        return phases[key]

    ensure(1, "setup")
    for row in event_phase_rows:
        phase = ensure(row.get("day"), row_history_phase(row))
        log_count = _int_or_none(row.get("log_count")) or 0
        first_index = _int_or_none(row.get("first_event_index"))
        last_index = _int_or_none(row.get("last_event_index"))
        event_type = _row_type(row)
        phase["log_count"] += log_count
        phase["has_logs"] = phase["log_count"] > 0
        phase["has_deaths"] = bool(phase.get("has_deaths")) or event_type in _AUTHORITATIVE_DEATH_EVENTS or event_type in _NIGHT_OUTCOME_EVENTS
        if first_index is not None:
            current = _int_or_none(phase.get("first_event_index"))
            phase["first_event_index"] = first_index if current is None else min(current, first_index)
        if last_index is not None:
            current = _int_or_none(phase.get("last_event_index"))
            phase["last_event_index"] = last_index if current is None else max(current, last_index)

    for row in decision_phase_rows:
        phase = ensure(row.get("day"), row_history_phase(row))
        count = _int_or_none(row.get("decision_count")) or 0
        action_type = _row_type(row)
        phase["decision_count"] += count
        phase["has_decisions"] = phase["decision_count"] > 0
        phase["has_votes"] = bool(phase.get("has_votes")) or action_type in _VOTE_ACTION_TYPES

    return phases


def attach_history_phase_state(
    phases: list[dict[str, Any]],
    players: list[dict[str, Any]],
    state_event_rows: list[dict[str, Any]],
) -> None:
    state_events = [_event_row(row) for row in state_event_rows]
    state_events.sort(
        key=lambda item: (
            _phase_sort(_normalize_history_day(item.get("day")), row_history_phase(item)),
            _int_or_none(item.get("idx")) or 0,
        )
    )
    alive: dict[int, bool] = {}
    for player in players:
        player_id = _int_or_none(_first_value(player.get("id"), player.get("seat")))
        if player_id is not None:
            alive[player_id] = True
    sheriff_id: int | None = None
    event_index = 0
    has_authoritative_deaths = any(_row_type(log) in _AUTHORITATIVE_DEATH_EVENTS for log in state_events)
    for phase in phases:
        phase_day = _normalize_history_day(phase.get("day"))
        phase_name = normalize_history_phase(phase.get("phase"))
        phase_sort = _phase_sort(phase_day, phase_name)
        phase_last_index = _int_or_none(phase.get("last_event_index"))
        while event_index < len(state_events):
            event = state_events[event_index]
            event_sort = _phase_sort(_normalize_history_day(event.get("day")), row_history_phase(event, phase_name))
            event_idx = _int_or_none(event.get("idx")) or 0
            if event_sort > phase_sort or (event_sort == phase_sort and phase_last_index is not None and event_idx > phase_last_index):
                break
            for target_id in death_target_ids(event, has_authoritative_deaths):
                alive[target_id] = False
            sheriff_id = sheriff_id_after_log(event, sheriff_id)
            event_index += 1
        alive_ids = sorted(player_id for player_id, is_alive in alive.items() if is_alive)
        dead_ids = sorted(player_id for player_id, is_alive in alive.items() if not is_alive)
        phase["alive_player_ids"] = alive_ids
        phase["dead_player_ids"] = dead_ids
        phase["sheriff_id"] = sheriff_id
        phase["state_after"] = {
            "alive": alive_ids,
            "dead": dead_ids,
            "sheriff_id": sheriff_id,
        }
