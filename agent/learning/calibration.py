"""Confidence calibration metrics for objectively checkable decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from agent.infrastructure.decision_log import DecisionRecord
from engine.models import ActionType, Role, Team


CALIBRATION_BUCKETS: tuple[tuple[float, float], ...] = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.000000001),
)


CHECKABLE_ACTIONS = {
    ActionType.EXILE_VOTE.value,
    ActionType.PK_VOTE.value,
    ActionType.WITCH_ACT.value,
    ActionType.HUNTER_SHOOT.value,
    ActionType.WEREWOLF_KILL.value,
}


def calibrate_decisions(
    records: Iterable[DecisionRecord],
    roles: dict[int, Role],
) -> dict[str, Any]:
    """Compute expected calibration error for checkable decisions.

    The metric only counts decisions where the final hidden roles make a
    correctness label defensible. Speech and other subjective actions are
    intentionally excluded.
    """
    buckets = _empty_bucket_totals()
    for record in records:
        correctness = decision_correctness(record, roles)
        if correctness is None:
            continue
        confidence = _clamp_confidence(getattr(record, "confidence", 0.0) or 0.0)
        bucket = _bucket_name(confidence)
        buckets[bucket]["count"] += 1
        buckets[bucket]["correct"] += 1 if correctness else 0
        buckets[bucket]["confidence_sum"] += confidence
    return summarize_bucket_totals(buckets)


def calibrate_decisions_by_group(
    records: Iterable[DecisionRecord],
    roles: dict[int, Role],
    group_for_player: Callable[[int], str | None],
) -> dict[str, dict[str, Any]]:
    """Compute calibration reports grouped by player owner/version."""
    grouped: dict[str, dict[str, dict[str, float | int]]] = {}
    for record in records:
        player_id = getattr(record, "player_id", None)
        if player_id is None:
            continue
        group = group_for_player(player_id)
        if not group:
            continue
        correctness = decision_correctness(record, roles)
        if correctness is None:
            continue
        buckets = grouped.setdefault(group, _empty_bucket_totals())
        confidence = _clamp_confidence(getattr(record, "confidence", 0.0) or 0.0)
        bucket = _bucket_name(confidence)
        buckets[bucket]["count"] += 1
        buckets[bucket]["correct"] += 1 if correctness else 0
        buckets[bucket]["confidence_sum"] += confidence
    return {group: summarize_bucket_totals(buckets) for group, buckets in grouped.items()}


def merge_calibration_reports(reports: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple calibration reports into one weighted ECE report."""
    merged = _empty_bucket_totals()
    for report in reports:
        buckets = report.get("confidence_buckets", {})
        if not isinstance(buckets, dict):
            continue
        for bucket, data in buckets.items():
            if not isinstance(data, dict):
                continue
            target = merged.setdefault(str(bucket), {"count": 0, "correct": 0, "confidence_sum": 0.0})
            target["count"] += int(data.get("count", 0) or 0)
            target["correct"] += int(data.get("correct", 0) or 0)
            target["confidence_sum"] += float(data.get("confidence_sum", 0.0) or 0.0)
    return summarize_bucket_totals(merged)


def summarize_bucket_totals(buckets: dict[str, dict[str, float | int]]) -> dict[str, Any]:
    """Turn raw bucket totals into ECE and display-ready bucket metrics."""
    total_count = 0
    weighted_error = 0.0
    output: dict[str, dict[str, float | int]] = {}
    for bucket in _bucket_names():
        data = buckets.get(bucket, {"count": 0, "correct": 0, "confidence_sum": 0.0})
        count = int(data.get("count", 0) or 0)
        correct = int(data.get("correct", 0) or 0)
        confidence_sum = float(data.get("confidence_sum", 0.0) or 0.0)
        if count > 0:
            avg_confidence = confidence_sum / count
            accuracy = correct / count
            error = abs(avg_confidence - accuracy)
            total_count += count
            weighted_error += error * count
        else:
            avg_confidence = 0.0
            accuracy = 0.0
            error = 0.0
        output[bucket] = {
            "count": count,
            "correct": correct,
            "confidence_sum": round(confidence_sum, 6),
            "avg_confidence": round(avg_confidence, 3),
            "accuracy": round(accuracy, 3),
            "error": round(error, 3),
        }
    return {
        "confidence_calibration_error": weighted_error / total_count if total_count else 0.0,
        "confidence_calibration_count": total_count,
        "confidence_buckets": output,
    }


def decision_correctness(record: DecisionRecord, roles: dict[int, Role]) -> bool | None:
    """Return objective correctness for a decision, or None if uncheckable."""
    action = _action_value(getattr(record, "action_type", ""))
    if action not in CHECKABLE_ACTIONS:
        return None
    player_id = getattr(record, "player_id", None)
    target = getattr(record, "selected_target", None)
    actor_role = roles.get(player_id) if player_id is not None else None
    target_role = roles.get(target) if target is not None else None
    if actor_role is None:
        return None

    if action in {ActionType.EXILE_VOTE.value, ActionType.PK_VOTE.value}:
        if target_role is None:
            return None
        return _target_is_wolf(target_role) if not _role_is_wolf(actor_role) else not _target_is_wolf(target_role)

    if action == ActionType.WEREWOLF_KILL.value:
        if target_role is None:
            return None
        return not _target_is_wolf(target_role)

    if action == ActionType.HUNTER_SHOOT.value:
        if target_role is None:
            return None
        return _target_is_wolf(target_role)

    if action == ActionType.WITCH_ACT.value:
        choice = (getattr(record, "selected_choice", None) or "").lower()
        if choice == "poison":
            return _target_is_wolf(target_role) if target_role is not None else None
        return None

    return None


def _empty_bucket_totals() -> dict[str, dict[str, float | int]]:
    return {
        name: {"count": 0, "correct": 0, "confidence_sum": 0.0}
        for name in _bucket_names()
    }


def _bucket_names() -> list[str]:
    return [f"{low:.1f}-{min(high, 1.0):.1f}" for low, high in CALIBRATION_BUCKETS]


def _bucket_name(confidence: float) -> str:
    for low, high in CALIBRATION_BUCKETS:
        if low <= confidence < high:
            return f"{low:.1f}-{min(high, 1.0):.1f}"
    return "0.8-1.0"


def _clamp_confidence(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _action_value(action: Any) -> str:
    return action.value if hasattr(action, "value") else str(action)


def _role_is_wolf(role: Role) -> bool:
    return role.team is Team.WEREWOLVES


def _target_is_wolf(role: Role) -> bool:
    return role.team is Team.WEREWOLVES
