"""Benchmark leaderboard unrankable evidence helpers."""

from __future__ import annotations

from typing import Any

from ui.backend.services.benchmark_payload_utils import first_text as _first_text
from ui.backend.services.benchmark_leaderboard_common import _leaderboard_subject_key
from ui.backend.services.benchmark_leaderboard_statistics import (
    _first_float,
    _first_int,
)


def _filter_unrankable_evidence_for_compare(
    rows: list[dict[str, Any]],
    *,
    scope: str | None,
    evaluation_set_id: str | None,
    target_role: str | None,
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if row.get("rankable") is not False:
            continue
        row_scope = str(row.get("scope") or "").strip().lower()
        if scope and row_scope and row_scope != scope:
            continue
        row_eval = str(row.get("evaluation_set_id") or "").strip()
        if evaluation_set_id and row_eval and row_eval != str(evaluation_set_id):
            continue
        row_role = str(row.get("target_role") or "").strip().lower()
        if target_role and row_role and row_role != str(target_role).strip().lower():
            continue
        evidence.append(_leaderboard_unrankable_evidence_row(row, index=index))
    return evidence


def _benchmark_result_has_unrankable_evidence(result: dict[str, Any]) -> bool:
    if result.get("rankable") is False:
        return True
    gate = result.get("leaderboard_gate") if isinstance(result.get("leaderboard_gate"), dict) else {}
    if gate.get("accepted") is False:
        return True
    return bool(result.get("leaderboard_skipped_reason"))


def _dedupe_unrankable_evidence(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        subject = str(row.get("subject_id") or row.get("model_config_hash") or row.get("target_version_id") or "")
        batch_id = str(row.get("batch_id") or "")
        result_batch_id = str(row.get("result_batch_id") or "")
        key = (
            str(row.get("scope") or ""),
            str(row.get("evaluation_set_id") or ""),
            str(row.get("target_role") or ""),
            subject,
            batch_id,
            result_batch_id,
        )
        if not any(key):
            key = (str(row.get("evidence_key") or ""),)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def _leaderboard_unrankable_evidence_row(row: dict[str, Any], *, index: int) -> dict[str, Any]:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    completed_games = _first_int(
        row.get("completed_games"),
        row.get("games_played"),
        row.get("completed"),
        summary.get("completed_games"),
        summary.get("games_played"),
        row.get("game_count"),
    )
    total_games = _first_int(
        row.get("total_games"),
        row.get("game_count"),
        summary.get("total_games"),
        summary.get("game_count"),
        completed_games,
    )
    valid_game_rate = _first_float(row.get("valid_game_rate"), summary.get("valid_game_rate"))
    return {
        "evidence_key": _leaderboard_subject_key(row) or f"unrankable:{index}",
        "scope": row.get("scope"),
        "subject_id": row.get("subject_id") or row.get("hash"),
        "model_id": row.get("model_id"),
        "model_config_hash": row.get("model_config_hash"),
        "target_role": row.get("target_role"),
        "target_version_id": row.get("target_version_id"),
        "evaluation_set_id": row.get("evaluation_set_id"),
        "seed_set_id": row.get("seed_set_id"),
        "batch_id": row.get("batch_id") or summary.get("batch_id") or row.get("comparison_group_id"),
        "result_batch_id": row.get("result_batch_id") or summary.get("result_batch_id"),
        "status": "unrankable",
        "rankable": False,
        "reason": _first_text(
            row.get("rankable_reason"),
            row.get("leaderboard_skipped_reason"),
            row.get("reason"),
            summary.get("rankable_reason"),
            summary.get("leaderboard_skipped_reason"),
            summary.get("reason"),
            "rankable gate failed",
        ),
        "completed_games": completed_games,
        "total_games": total_games,
        "valid_game_rate": valid_game_rate,
        "updated_at": row.get("updated_at"),
        "source": row.get("source") or "leaderboard",
    }
