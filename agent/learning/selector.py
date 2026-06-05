"""Key decision selection for the learning evidence layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agent.common.action_types import (
    NIGHT_SKILL_ACTION_TYPES,
    SPEECH_ACTION_TYPES,
    VOTE_ACTION_TYPES,
)
from agent.learning.models import DecisionEvidenceInput, GameEvidenceBundle, KeyDecision

# ---------------------------------------------------------------------------
# Action-type sets for key-decision selection
#
# Every string must be a valid ActionType enum value. See
# AGENT_ACTION_TYPES in agent.common.action_types for the authoritative
# list.
# ---------------------------------------------------------------------------

#: Rule-level actions that directly change deaths, information,
#: rounds, or votes.  Composed from centralized category sets.
#: Note: witch_act covers both save and poison sub-choices.
RULE_KEY_ACTIONS: frozenset[str] = (
    NIGHT_SKILL_ACTION_TYPES       # guard_protect, werewolf_kill, seer_check, witch_act, white_wolf_explode
    | VOTE_ACTION_TYPES            # exile_vote, pk_vote, sheriff_vote
    | frozenset({
        "sheriff_run",             # sheriff election entry
        "sheriff_badge",           # badge transfer / destroy
    })
)

#: Actions with the highest game-outcome impact.  Used by
#: _impact_for_action to assign "highest" impact level.
HIGHEST_IMPACT_ACTIONS: frozenset[str] = (
    VOTE_ACTION_TYPES             # exile_vote, pk_vote, sheriff_vote
    | frozenset({
        "white_wolf_explode",     # white wolf king self-explode
        "werewolf_kill",          # werewolf night kill
    })
)

#: Actions relevant when a day-phase exile / turning point occurs.
DAY_WINDOW_ACTIONS: frozenset[str] = (
    SPEECH_ACTION_TYPES           # speak, pk_speak, sheriff_speak, last_word
    | VOTE_ACTION_TYPES           # exile_vote, pk_vote, sheriff_vote
    | frozenset({
        "sheriff_run",
    })
)

#: Actions relevant when a night-phase death / skill turning point
#: occurs.
NIGHT_WINDOW_ACTIONS: frozenset[str] = (
    NIGHT_SKILL_ACTION_TYPES      # guard_protect, werewolf_kill, seer_check, witch_act, white_wolf_explode
    | frozenset({
        "hunter_shoot",           # hunter shoot triggered by night death
    })
)


@dataclass(frozen=True, slots=True)
class TurningWindow:
    turning_point_id: str
    day: int | None
    phase: str
    action_types: set[str]
    note: str


def select_key_decisions(
    inputs: list[DecisionEvidenceInput],
    bundle: GameEvidenceBundle,
) -> list[KeyDecision]:
    selected: dict[str, KeyDecision] = {}

    for item in inputs:
        if item.action_type in RULE_KEY_ACTIONS:
            selected[item.decision_id] = _to_key(
                item,
                key_reason="rule_natural_key_action",
                impact_level=_impact_for_action(item.action_type, item.decision_result.selected_choice),
                note="规则上直接改变死亡、信息、轮次或票型的动作。",
            )

    for window in _detect_turning_windows(bundle.game_events):
        for item in inputs:
            if item.day != window.day:
                continue
            if window.phase and not _phase_matches(item.phase, window.phase):
                continue
            if item.action_type not in window.action_types:
                continue
            if item.decision_id in selected:
                _append_note(selected[item.decision_id], window.note)
                if selected[item.decision_id].turning_point_id is None:
                    selected[item.decision_id].turning_point_id = window.turning_point_id
                continue
            selected[item.decision_id] = _to_key(
                item,
                key_reason="turning_point_window",
                impact_level="contextual",
                turning_point_id=window.turning_point_id,
                note=window.note,
            )

    return sorted(selected.values(), key=lambda item: (item.day or 0, item.phase, item.decision_id))


def _detect_turning_windows(events: list[dict[str, Any]]) -> list[TurningWindow]:
    windows: list[TurningWindow] = []
    seen_ids: set[str] = set()
    max_day = max((_as_int(event.get("day")) or 0 for event in events), default=0)
    for event in events:
        event_type = str(event.get("event_type") or "")
        day = _as_int(event.get("day"))
        target = event.get("target")
        if event_type == "exile_result":
            _append_window(
                windows,
                seen_ids,
                TurningWindow(
                    turning_point_id=f"exile_turning_point_day_{day}_target_{target}",
                    day=day,
                    phase="day",
                    action_types=DAY_WINDOW_ACTIONS,
                    note="白天出局转折点窗口：当天发言、投票和相关遗言进入关键池。",
                ),
            )
        if event_type in {"death_result", "night_death", "werewolf_result", "witch_result", "hunter_result"}:
            _append_window(
                windows,
                seen_ids,
                TurningWindow(
                    turning_point_id=f"death_turning_point_day_{day}_target_{target}",
                    day=day,
                    phase="night",
                    action_types=NIGHT_WINDOW_ACTIONS,
                    note="夜晚死亡/技能转折点窗口：当夜技能进入关键池。",
                ),
            )
    if max_day:
        _append_window(
            windows,
            seen_ids,
            TurningWindow(
                turning_point_id=f"endgame_turning_point_day_{max_day}",
                day=max_day,
                phase="day",
                action_types=DAY_WINDOW_ACTIONS,
                note="终局转折窗口：最后一昼夜相关决策进入关键池。",
            ),
        )
        _append_window(
            windows,
            seen_ids,
            TurningWindow(
                turning_point_id=f"endgame_turning_point_day_{max_day}_night",
                day=max_day,
                phase="night",
                action_types=NIGHT_WINDOW_ACTIONS,
                note="终局转折窗口：最后一昼夜相关夜间技能进入关键池。",
            ),
        )
    return windows


def _append_window(windows: list[TurningWindow], seen_ids: set[str], window: TurningWindow) -> None:
    if window.turning_point_id in seen_ids:
        return
    seen_ids.add(window.turning_point_id)
    windows.append(window)


def _append_note(decision: KeyDecision, note: str) -> None:
    if note not in decision.selection_notes:
        decision.selection_notes.append(note)


def _phase_matches(actual: str, expected: str) -> bool:
    if actual == expected:
        return True
    if expected == "day":
        return actual.startswith("day") or actual in {"exile_vote", "sheriff_election"}
    return False


def _to_key(
    item: DecisionEvidenceInput,
    *,
    key_reason: str,
    impact_level: str,
    note: str,
    turning_point_id: str | None = None,
) -> KeyDecision:
    return KeyDecision(
        decision_id=item.decision_id,
        day=item.day,
        phase=item.phase,
        action_type=item.action_type,
        player_id=item.player_view.player_id,
        role=item.player_view.role,
        key_reason=key_reason,
        impact_level=impact_level,
        turning_point_id=turning_point_id,
        selection_notes=[note],
    )


def _impact_for_action(action_type: str, choice: Any) -> str:
    if action_type == "witch_act" and choice == "poison":
        return "highest"
    if action_type in HIGHEST_IMPACT_ACTIONS:
        return "highest"
    return "high"


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None