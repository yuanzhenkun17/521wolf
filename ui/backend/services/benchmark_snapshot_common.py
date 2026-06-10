"""Shared benchmark snapshot helpers."""

from __future__ import annotations

import hashlib
import json
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


def _stable_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _stable_json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _benchmark_snapshot_int(*values: Any, default: int = 0) -> int:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default


def _text_content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _default_benchmark_snapshot_title(scope: str, evaluation_set_id: str, target_role: str | None) -> str:
    subject = "model" if scope == "model" else (target_role or "role-version")
    return f"{evaluation_set_id} / {subject}"
