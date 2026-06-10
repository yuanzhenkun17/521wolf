"""Pure game-history phase and state transition helpers."""

from __future__ import annotations

from typing import Any

HISTORY_PHASE_ALIASES = {
    "result": "night",
    "sheriff_election": "sheriff",
    "day_speech": "speech",
    "pk_speak": "speech",
    "finished": "ended",
}
HISTORY_PHASE_ORDER = (
    "setup",
    "night",
    "sheriff",
    "sheriff_vote",
    "sheriff_result",
    "speech",
    "exile_vote",
    "pk_vote",
    "vote",
    "ended",
)
HISTORY_PHASE_RANK = {phase: index for index, phase in enumerate(HISTORY_PHASE_ORDER)}
VOTE_PHASE_BY_TYPE = {
    "vote": "exile_vote",
    "exile": "exile_vote",
    "exile_vote": "exile_vote",
    "exile_vote_start": "exile_vote",
    "exile_vote_end": "exile_vote",
    "exile_vote_tie": "exile_vote",
    "pk_vote": "pk_vote",
    "pk_vote_start": "pk_vote",
    "pk_vote_end": "pk_vote",
    "sheriff_vote": "sheriff_vote",
    "sheriff_vote_tie": "sheriff_vote",
}
PHASE_QUERY_ALIASES = {
    "night": {"night", "result"},
    "sheriff": {"sheriff", "sheriff_election"},
    "speech": {"speech", "day_speech", "pk_speak"},
    "exile_vote": {"exile_vote", "vote"},
    "pk_vote": {"pk_vote", "vote"},
    "sheriff_vote": {"sheriff_vote", "vote"},
    "ended": {"ended", "finished"},
}
VOTE_ACTION_TYPES = {"vote", "exile", "exile_vote", "pk_vote", "sheriff_vote"}
AUTHORITATIVE_DEATH_EVENTS = {
    "death",
    "exile",
    "exile_vote_end",
    "pk_vote_end",
    "white_wolf_burst_kill",
    "white_wolf_burst_death",
    "white_wolf_explosion",
}
FALLBACK_DEATH_EVENTS = {"werewolf_kill", "hunter_shoot"}
NIGHT_OUTCOME_EVENTS = {"night_end", "night_result", "night_death", "night_death_reveal", "death_result"}
SHERIFF_RESULT_EVENTS = {"sheriff_election_end", "sheriff_result"}
SHERIFF_TRANSFER_EVENTS = {"sheriff_badge_transfer", "sheriff_transfer"}
SHERIFF_DESTROY_EVENTS = {"sheriff_badge_destroy", "sheriff_destroy"}
SHELL_STATE_EVENT_TYPES = tuple(sorted(
    AUTHORITATIVE_DEATH_EVENTS
    | FALLBACK_DEATH_EVENTS
    | NIGHT_OUTCOME_EVENTS
    | SHERIFF_RESULT_EVENTS
    | SHERIFF_TRANSFER_EVENTS
    | SHERIFF_DESTROY_EVENTS
    | {"white_wolf_explode"}
))


def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_history_day(day: Any) -> int:
    value = _int_or_none(day)
    return value if value is not None and value > 0 else 1


def normalize_history_phase(phase: Any = "setup") -> str:
    text = str(phase or "setup").strip() or "setup"
    return HISTORY_PHASE_ALIASES.get(text, text)


def history_phase_key(day: Any, phase: Any) -> str:
    return f"day-{normalize_history_day(day)}-{normalize_history_phase(phase)}"


def history_phase_title(day: Any, phase: Any) -> str:
    normalized_day = normalize_history_day(day)
    normalized_phase = normalize_history_phase(phase)
    titles = {
        "setup": "准备",
        "night": f"第{normalized_day}夜",
        "sheriff": "警长竞选",
        "sheriff_vote": "警长投票",
        "sheriff_result": "上警/退水",
        "speech": f"第{normalized_day}天",
        "exile_vote": f"第{normalized_day}天放逐投票",
        "pk_vote": f"第{normalized_day}天对决投票",
        "vote": f"第{normalized_day}天投票",
        "ended": "结果",
    }
    return titles.get(normalized_phase, normalized_phase)


def phase_sort(day: Any, phase: Any) -> int:
    normalized_phase = normalize_history_phase(phase)
    rank = HISTORY_PHASE_RANK.get(normalized_phase, len(HISTORY_PHASE_ORDER))
    return normalize_history_day(day) * 100 + rank


def row_type(row: dict[str, Any]) -> str:
    return str(
        row.get("type")
        or row.get("event_type")
        or row.get("action")
        or row.get("action_type")
        or row.get("kind")
        or ""
    ).strip()


def vote_action_phase(row: dict[str, Any]) -> str:
    return VOTE_PHASE_BY_TYPE.get(row_type(row), "")


def row_history_phase(row: dict[str, Any], fallback: str = "setup") -> str:
    raw_phase = normalize_history_phase(row.get("phase", fallback))
    vote_phase = vote_action_phase(row)
    if raw_phase == "vote" and vote_phase and vote_phase != "sheriff_vote":
        return vote_phase
    if (row.get("phase") is None or row.get("phase") == "") and vote_phase:
        return vote_phase
    return raw_phase


def phase_query_candidates(phase: str) -> set[str]:
    normalized = normalize_history_phase(phase)
    candidates = set(PHASE_QUERY_ALIASES.get(normalized, {normalized}))
    candidates.add(normalized)
    return candidates


def replay_window_phase_filters(event_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[int, set[str]] = {}
    for row in event_rows:
        day = normalize_history_day(row.get("day"))
        phase = row_history_phase(row)
        grouped.setdefault(day, set()).add(phase)
    filters = []
    for day in sorted(grouped):
        normalized_phases = sorted(grouped[day], key=lambda item: phase_sort(day, item))
        raw_phases = sorted({raw_phase for phase in normalized_phases for raw_phase in phase_query_candidates(phase)})
        filters.append({
            "day": day,
            "normalized_phases": normalized_phases,
            "raw_phases": raw_phases,
        })
    return filters


def empty_phase_summary(day: Any, phase: Any) -> dict[str, Any]:
    normalized_day = normalize_history_day(day)
    normalized_phase = normalize_history_phase(phase)
    return {
        "key": history_phase_key(normalized_day, normalized_phase),
        "day": normalized_day,
        "phase": normalized_phase,
        "title": history_phase_title(normalized_day, normalized_phase),
        "sort": phase_sort(normalized_day, normalized_phase),
        "log_count": 0,
        "decision_count": 0,
        "has_logs": False,
        "has_decisions": False,
        "has_votes": False,
        "has_deaths": False,
        "first_event_index": None,
        "last_event_index": None,
    }


def _payload_of(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    return payload if isinstance(payload, dict) else {}


def _numeric_id(value: Any) -> int | None:
    value = _int_or_none(value)
    return value if value is not None and value > 0 else None


def _truthy_flag(value: Any) -> bool:
    return value is True or value == 1 or value == "1" or str(value).lower() == "true"


def _row_choice(row: dict[str, Any]) -> str:
    payload = _payload_of(row)
    return str(
        payload.get("choice")
        or payload.get("selected_choice")
        or payload.get("selected_skill")
        or row.get("choice")
        or row.get("selected_choice")
        or row.get("selected_skill")
        or row.get("action_choice")
        or ""
    ).strip().lower()


def _payload_id_list(row: dict[str, Any], keys: list[str]) -> list[int]:
    payload = _payload_of(row)
    ids: list[int] = []
    seen: set[int] = set()
    for key in keys:
        raw = payload.get(key, row.get(key))
        values = raw if isinstance(raw, list) else ([] if raw is None else [raw])
        for value in values:
            if isinstance(value, dict):
                value = value.get("id", value.get("player_id", value.get("seat")))
            player_id = _numeric_id(value)
            if player_id is None or player_id in seen:
                continue
            seen.add(player_id)
            ids.append(player_id)
    return ids


def _event_target_id(row: dict[str, Any]) -> int | None:
    payload = _payload_of(row)
    return _numeric_id(
        row.get("target_id")
        or row.get("target")
        or row.get("selected_target")
        or payload.get("target_id")
        or payload.get("target")
        or payload.get("player_id")
    )


def _is_legacy_white_wolf_explode_kill(row: dict[str, Any]) -> bool:
    if row_type(row) != "white_wolf_explode":
        return False
    return _row_choice(row) in {"explode", "burst"} and _event_target_id(row) is not None


def _event_kills_player(row: dict[str, Any], has_authoritative_death_events: bool = True) -> bool:
    current_row_type = row_type(row)
    if _is_legacy_white_wolf_explode_kill(row):
        return True
    if current_row_type in AUTHORITATIVE_DEATH_EVENTS:
        return True
    return not has_authoritative_death_events and current_row_type in FALLBACK_DEATH_EVENTS


def _night_outcome_death_ids(row: dict[str, Any]) -> list[int]:
    current_row_type = row_type(row)
    if current_row_type not in NIGHT_OUTCOME_EVENTS:
        return []
    payload = _payload_of(row)
    if current_row_type == "night_end" and _truthy_flag(payload.get("deferred_death_reveal", row.get("deferred_death_reveal"))):
        return []
    if any(
        isinstance(payload.get(key), list) or isinstance(row.get(key), list)
        for key in ("deaths", "death_ids", "dead_players")
    ):
        return _payload_id_list(row, ["deaths", "death_ids", "dead_players"])
    ids: list[int] = []
    killed = _numeric_id(payload.get("killed_target", payload.get("killedTarget", row.get("killed_target", row.get("killedTarget")))))
    protected = _numeric_id(payload.get("protected_target", payload.get("protectedTarget", row.get("protected_target", row.get("protectedTarget")))))
    saved = _truthy_flag(payload.get("saved", payload.get("used_antidote", payload.get("antidote_used", row.get("saved")))))
    if killed and not saved and killed != protected:
        ids.append(killed)
    poisoned = _numeric_id(payload.get("poisoned_target", payload.get("poisonedTarget", payload.get("poison_target", payload.get("poisonTarget", row.get("poisoned_target"))))))
    if poisoned and poisoned not in ids:
        ids.append(poisoned)
    target = _event_target_id(row)
    if target and current_row_type != "night_end" and target not in ids:
        ids.append(target)
    return ids


def death_target_ids(row: dict[str, Any], has_authoritative_death_events: bool = True) -> list[int]:
    ids = _night_outcome_death_ids(row)
    if _event_kills_player(row, has_authoritative_death_events):
        target = _event_target_id(row) or _numeric_id(row.get("actor_id", row.get("actor")))
        if target and target not in ids:
            ids.append(target)
    return ids


def sheriff_id_after_log(row: dict[str, Any], current_sheriff_id: int | None = None) -> int | None:
    current_row_type = row_type(row)
    payload = _payload_of(row)
    if current_row_type in SHERIFF_RESULT_EVENTS:
        return _numeric_id(payload.get("winner") or row.get("target_id") or row.get("actor_id")) or current_sheriff_id
    if current_row_type in SHERIFF_TRANSFER_EVENTS:
        return _event_target_id(row) or current_sheriff_id
    if current_row_type in SHERIFF_DESTROY_EVENTS:
        return None
    return current_sheriff_id
