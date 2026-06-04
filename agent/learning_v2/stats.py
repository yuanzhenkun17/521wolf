"""Consolidated statistics helpers: metric aggregation, confidence intervals, and calibration.

Combines the former ``metrics``, ``statistics``, and ``calibration`` modules
into a single location.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from statistics import mean, pstdev
from typing import Any

from agent.infrastructure.decision_log import DecisionRecord
from engine.models import ActionType, Role, Team

from agent.common.action_types import (
    VOTE_ACTION_TYPES,
    NIGHT_SKILL_ACTION_TYPES,
)

# ---------------------------------------------------------------------------
# Metric aggregation  (formerly agent.learning.metrics)
# ---------------------------------------------------------------------------


def new_role_accum() -> dict[str, float | int]:
    """Create a fresh per-role accumulator dict."""
    return {
        "players": 0,
        "wins": 0,
        "losses": 0,
        "total_score_sum": 0.0,
        "role_weighted_score_sum": 0.0,
        "speech_score_sum": 0.0,
        "vote_score_sum": 0.0,
        "skill_score_sum": 0.0,
        "information_score_sum": 0.0,
        "cooperation_score_sum": 0.0,
        "decision_count": 0,
        "fallback_count": 0,
        "llm_error_count": 0,
        "policy_adjusted_count": 0,
        "bad_case_count": 0,
    }


def finalize_role_metrics(state: dict[str, float | int]) -> dict[str, float | int]:
    """Convert raw accumulator state into finalised per-role metrics."""
    players = int(state.get("players", 0))
    decisions = int(state.get("decision_count", 0))
    bad_cases = int(state.get("bad_case_count", 0))

    def _avg(field: str) -> float:
        if players <= 0:
            return 0.0
        return round(float(state.get(f"{field}_sum", 0.0)) / players, 3)

    return {
        "players": players,
        "wins": int(state.get("wins", 0)),
        "losses": int(state.get("losses", 0)),
        "win_rate": round(int(state.get("wins", 0)) / players, 3) if players else 0.0,
        "total_score": _avg("total_score"),
        "role_weighted_score": _avg("role_weighted_score"),
        "speech_score": _avg("speech_score"),
        "vote_score": _avg("vote_score"),
        "skill_score": _avg("skill_score"),
        "information_score": _avg("information_score"),
        "cooperation_score": _avg("cooperation_score"),
        "decision_count": decisions,
        "fallback_count": int(state.get("fallback_count", 0)),
        "llm_error_count": int(state.get("llm_error_count", 0)),
        "policy_adjusted_count": int(state.get("policy_adjusted_count", 0)),
        "fallback_rate": round(int(state.get("fallback_count", 0)) / decisions, 4)
        if decisions else 0.0,
        "llm_error_rate": round(int(state.get("llm_error_count", 0)) / decisions, 4)
        if decisions else 0.0,
        "policy_adjusted_rate": round(int(state.get("policy_adjusted_count", 0)) / decisions, 4)
        if decisions else 0.0,
        "bad_case_count": bad_cases,
        "bad_case_rate": round(bad_cases / decisions, 4) if decisions else 0.0,
    }


# ---------------------------------------------------------------------------
# Statistical helpers  (formerly agent.learning.statistics)
# ---------------------------------------------------------------------------


def mean_ci95(samples: list[float]) -> tuple[float, float]:
    """Return a normal-approximation 95% CI for a bounded score sample."""
    if not samples:
        return (0.0, 0.0)
    avg = mean(samples)
    if len(samples) == 1:
        return (avg, avg)
    stderr = pstdev(samples) / math.sqrt(len(samples))
    delta = 1.96 * stderr
    return (avg - delta, avg + delta)


def wilson_ci95(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score confidence interval for a binomial rate.

    Args:
        successes: Number of successes.
        total: Total number of trials.
        z: Z-score for confidence level (default 1.96 for 95% CI).

    Returns:
        (lower, upper) bounds at the given confidence level.
    """
    if total <= 0:
        return (0.0, 0.0)
    p = successes / total
    denom = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denom
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


# ---------------------------------------------------------------------------
# Confidence calibration  (formerly agent.learning.calibration)
# ---------------------------------------------------------------------------

CALIBRATION_BUCKETS: tuple[tuple[float, float], ...] = (
    (0.0, 0.2),
    (0.2, 0.4),
    (0.4, 0.6),
    (0.6, 0.8),
    (0.8, 1.000000001),
)


CHECKABLE_ACTIONS = (
    VOTE_ACTION_TYPES              # exile_vote, pk_vote, sheriff_vote
    | frozenset({
        ActionType.WITCH_ACT.value,         # "witch_act"
        ActionType.HUNTER_SHOOT.value,      # "hunter_shoot"
        ActionType.WEREWOLF_KILL.value,     # "werewolf_kill"
    })
)


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
        return _role_is_wolf(target_role) if not _role_is_wolf(actor_role) else not _role_is_wolf(target_role)

    if action == ActionType.WEREWOLF_KILL.value:
        if target_role is None:
            return None
        return not _role_is_wolf(target_role)

    if action == ActionType.HUNTER_SHOOT.value:
        if target_role is None:
            return None
        return _role_is_wolf(target_role)

    if action == ActionType.WITCH_ACT.value:
        choice = (getattr(record, "selected_choice", None) or "").lower()
        if choice == "poison":
            return _role_is_wolf(target_role) if target_role is not None else None
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