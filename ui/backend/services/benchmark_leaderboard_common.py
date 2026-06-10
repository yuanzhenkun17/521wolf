"""Shared benchmark leaderboard helpers."""

from __future__ import annotations

from typing import Any


def _leaderboard_subject_key(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    for key in ("subject_id", "hash", "model_config_hash", "target_version_id", "model_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""


def _leaderboard_metric(row: dict[str, Any] | None, *keys: str) -> float:
    if not row:
        return 0.0
    for key in keys:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if value == value:
            return value
    return 0.0


def _leaderboard_score(row: dict[str, Any] | None, *, scope: str | None) -> float:
    if scope == "model":
        return _leaderboard_metric(row, "strength_score", "avg_role_score", "target_role_role_weighted_score")
    return _leaderboard_metric(row, "avg_role_score", "target_role_role_weighted_score", "strength_score")
