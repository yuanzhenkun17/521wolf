"""Benchmark leaderboard row normalization and compare helpers."""

from __future__ import annotations

from collections import Counter
from typing import Any

from ui.backend.services.benchmark_payload_utils import (
    decode_json_field as _decode_json_field,
    first_text as _first_text,
    json_clone as _json_clone,
    row_to_dict as _row_to_dict,
)
from ui.backend.services.benchmark_leaderboard_common import (
    _leaderboard_metric,
    _leaderboard_score,
    _leaderboard_subject_key,
)
from ui.backend.services.benchmark_leaderboard_evidence import (
    _benchmark_result_has_unrankable_evidence as _benchmark_result_has_unrankable_evidence,
    _dedupe_unrankable_evidence as _dedupe_unrankable_evidence,
    _filter_unrankable_evidence_for_compare as _filter_unrankable_evidence_for_compare,
    _leaderboard_unrankable_evidence_row as _leaderboard_unrankable_evidence_row,
)
from ui.backend.services.benchmark_leaderboard_statistics import (
    _binomial_standard_error as _binomial_standard_error,
    _dedupe_warning_codes as _dedupe_warning_codes,
    _empty_leaderboard_statistics as _empty_leaderboard_statistics,
    _first_float as _first_float,
    _first_int as _first_int,
    _leaderboard_compare_statistics,
    _leaderboard_paired_evidence as _leaderboard_paired_evidence,
    _leaderboard_row_statistics,
    _leaderboard_seed_metric_key as _leaderboard_seed_metric_key,
    _leaderboard_seed_metrics as _leaderboard_seed_metrics,
    _optional_probability_delta as _optional_probability_delta,
    _probability_from_value as _probability_from_value,
    _seed_metric_value as _seed_metric_value,
    _stat_warning_list as _stat_warning_list,
    _wilson_confidence_interval as _wilson_confidence_interval,
)


def _benchmark_results(batch: dict[str, Any]) -> list[dict[str, Any]]:
    results = batch.get("results")
    if isinstance(results, list):
        return [dict(item) for item in results if isinstance(item, dict)]
    result = batch.get("result")
    return [dict(result)] if isinstance(result, dict) else []


def _benchmark_result_batch_id(result: dict[str, Any]) -> str:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    return str(result.get("batch_id") or config.get("batch_id") or "")


def _benchmark_result_role(result: dict[str, Any]) -> str | None:
    config = result.get("config") if isinstance(result.get("config"), dict) else {}
    role = result.get("target_role") or config.get("target_role")
    return str(role) if role else None


def _benchmark_result_game_count(result: dict[str, Any]) -> int:
    for key in ("game_count", "completed", "attempted_game_count"):
        try:
            if result.get(key) is not None:
                return max(0, int(result.get(key) or 0))
        except (TypeError, ValueError):
            continue
    games = result.get("games")
    return len([item for item in games if isinstance(item, dict)]) if isinstance(games, list) else 0


def _benchmark_batch_boundary(batch: dict[str, Any]) -> dict[str, Any]:
    benchmark = batch.get("benchmark") if isinstance(batch.get("benchmark"), dict) else {}
    config = batch.get("config") if isinstance(batch.get("config"), dict) else {}
    results = _benchmark_results(batch)

    def first_result_value(*keys: str) -> Any:
        for result in results:
            result_config = result.get("config") if isinstance(result.get("config"), dict) else {}
            for key in keys:
                value = result.get(key)
                if value not in (None, ""):
                    return value
                value = result_config.get(key)
                if value not in (None, ""):
                    return value
        return None

    target_type = str(
        batch.get("target_type")
        or benchmark.get("target_type")
        or config.get("target_type")
        or first_result_value("target_type", "comparison_type")
        or "role_version"
    ).strip().lower()
    roles = batch.get("roles") if isinstance(batch.get("roles"), list) else []
    return {
        "batch_id": str(batch.get("batch_id") or batch.get("run_id") or ""),
        "status": str(batch.get("status") or "").strip().lower(),
        "target_type": "model" if target_type == "model" else "role_version",
        "benchmark_id": str(
            benchmark.get("id")
            or batch.get("benchmark_id")
            or config.get("benchmark_id")
            or first_result_value("benchmark_id")
            or ""
        ),
        "benchmark_version": (
            benchmark.get("version")
            or batch.get("benchmark_version")
            or config.get("benchmark_version")
            or first_result_value("benchmark_version")
        ),
        "evaluation_set_id": str(
            benchmark.get("evaluation_set_id")
            or batch.get("evaluation_set_id")
            or config.get("evaluation_set_id")
            or first_result_value("evaluation_set_id")
            or ""
        ),
        "seed_set_id": str(
            benchmark.get("seed_set_id")
            or batch.get("seed_set_id")
            or config.get("seed_set_id")
            or first_result_value("seed_set_id")
            or ""
        ),
        "model_id": str(batch.get("model_id") or config.get("model_id") or first_result_value("model_id") or ""),
        "model_config_hash": str(
            batch.get("model_config_hash")
            or config.get("model_config_hash")
            or first_result_value("model_config_hash")
            or ""
        ),
        "roles": [str(role).strip().lower() for role in roles if str(role).strip()],
    }


def _leaderboard_row_payload(row: Any) -> dict[str, Any]:
    payload = _row_to_dict(row)
    by_role = _decode_json_field(payload.get("by_role_category_scores"), fallback={})
    summary = _decode_json_field(payload.get("summary"), fallback={})
    game_count = int(payload.get("games_played") or 0)
    scope = str(payload.get("scope") or "")
    subject_id = str(payload.get("subject_id") or "")
    target_version_id = payload.get("target_version_id")
    model_id = payload.get("model_id")
    model_config_hash = payload.get("model_config_hash")
    score = float(payload.get("avg_role_score") or 0.0)
    strength_score = float(payload.get("strength_score") or score or 0.0)
    source_run_id = _first_text(
        payload.get("source_run_id"),
        payload.get("run_id"),
        payload.get("batch_id"),
        summary.get("source_run_id") if isinstance(summary, dict) else None,
        summary.get("run_id") if isinstance(summary, dict) else None,
        summary.get("batch_id") if isinstance(summary, dict) else None,
        payload.get("comparison_group_id"),
    )
    result_batch_id = _first_text(
        payload.get("result_batch_id"),
        summary.get("result_batch_id") if isinstance(summary, dict) else None,
    )
    report_id = _first_text(
        payload.get("report_id"),
        summary.get("report_id") if isinstance(summary, dict) else None,
        f"benchmark_report:{source_run_id}" if source_run_id else "",
    )
    row_payload = {
        "scope": scope,
        "hash": subject_id or str(target_version_id or model_config_hash or model_id or ""),
        "subject_id": subject_id,
        "model_id": model_id,
        "model_config_hash": model_config_hash,
        "target_role": payload.get("target_role"),
        "target_version_id": target_version_id,
        "comparison_group_id": payload.get("comparison_group_id"),
        "evaluation_set_id": payload.get("evaluation_set_id"),
        "seed_set_id": payload.get("seed_set_id"),
        "benchmark_config_hash": _first_text(
            payload.get("benchmark_config_hash"),
            payload.get("config_hash"),
            summary.get("benchmark_config_hash") if isinstance(summary, dict) else None,
            summary.get("config_hash") if isinstance(summary, dict) else None,
        ) or None,
        "game_count": game_count,
        "games_played": game_count,
        "valid_game_rate": float(payload.get("valid_game_rate") or 0.0),
        "strength_score": strength_score,
        "avg_role_score": score,
        "target_role_role_weighted_score": score,
        "by_role_category_scores": by_role,
        "avg_speech_score": float(payload.get("avg_speech_score") or 0.0),
        "avg_vote_score": float(payload.get("avg_vote_score") or 0.0),
        "avg_skill_score": float(payload.get("avg_skill_score") or 0.0),
        "avg_logic_score": float(payload.get("avg_logic_score") or 0.0),
        "avg_team_score": float(payload.get("avg_team_score") or 0.0),
        "risk_penalty": float(payload.get("risk_penalty") or 0.0),
        "fallback_rate": float(payload.get("fallback_rate") or 0.0),
        "target_role_fallback_rate": float(payload.get("fallback_rate") or 0.0),
        "llm_error_rate": float(payload.get("llm_error_rate") or 0.0),
        "policy_adjusted_rate": float(payload.get("policy_adjusted_rate") or 0.0),
        "target_side_win_rate": float(payload.get("target_side_win_rate") or 0.0),
        "rankable": bool(payload.get("rankable")),
        "data_sufficient": bool(payload.get("data_sufficient")),
        "summary": summary,
        "model_runtime": _json_clone(summary.get("model_runtime") or {}),
        "is_baseline": bool(summary.get("is_baseline", False)) if isinstance(summary, dict) else False,
        "delta_vs_baseline": {},
        "source_run_id": source_run_id,
        "batch_id": source_run_id,
        "result_batch_id": result_batch_id,
        "report_id": report_id,
        "updated_at": payload.get("updated_at"),
    }
    row_payload.update(_leaderboard_row_statistics(row_payload))
    return row_payload


def _select_leaderboard_baseline(
    rows: list[dict[str, Any]],
    *,
    baseline_subject_id: str | None = None,
) -> dict[str, Any] | None:
    wanted = str(baseline_subject_id or "").strip()
    if wanted:
        for row in rows:
            keys = {
                _leaderboard_subject_key(row),
                str(row.get("subject_id") or "").strip(),
                str(row.get("hash") or "").strip(),
                str(row.get("model_config_hash") or "").strip(),
                str(row.get("target_version_id") or "").strip(),
                str(row.get("model_id") or "").strip(),
            }
            if wanted in keys:
                return row
    for row in rows:
        if row.get("is_baseline") is True:
            return row
    for row in rows:
        if row.get("rankable") is not False:
            return row
    return rows[0] if rows else None


def _leaderboard_boundary_warnings(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    scope: str | None,
    target_role: str | None,
) -> list[str]:
    if not baseline:
        return []
    warnings: list[str] = []
    if scope and str(row.get("scope") or "").strip().lower() != scope:
        warnings.append("scope_mismatch")
    row_eval = str(row.get("evaluation_set_id") or "").strip()
    baseline_eval = str(baseline.get("evaluation_set_id") or "").strip()
    if row_eval and baseline_eval and row_eval != baseline_eval:
        warnings.append("evaluation_set_mismatch")
    row_seed = str(row.get("seed_set_id") or "").strip()
    baseline_seed = str(baseline.get("seed_set_id") or "").strip()
    if row_seed and baseline_seed and row_seed != baseline_seed:
        warnings.append("seed_set_mismatch")
    expected_role = str(target_role or baseline.get("target_role") or "").strip()
    row_role = str(row.get("target_role") or "").strip()
    if scope == "role_version" and expected_role and row_role and row_role != expected_role:
        warnings.append("target_role_mismatch")
    return warnings


def _leaderboard_compare_row(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    scope: str | None,
    target_role: str | None,
) -> dict[str, Any]:
    row_key = _leaderboard_subject_key(row)
    baseline_key = _leaderboard_subject_key(baseline)
    score_delta = _leaderboard_score(row, scope=scope) - _leaderboard_score(baseline, scope=scope)
    win_rate_delta = _leaderboard_metric(row, "target_side_win_rate") - _leaderboard_metric(
        baseline,
        "target_side_win_rate",
    )
    fallback_delta = _leaderboard_metric(row, "fallback_rate", "target_role_fallback_rate") - _leaderboard_metric(
        baseline,
        "fallback_rate",
        "target_role_fallback_rate",
    )
    llm_error_delta = _leaderboard_metric(row, "llm_error_rate") - _leaderboard_metric(baseline, "llm_error_rate")
    policy_adjusted_delta = _leaderboard_metric(row, "policy_adjusted_rate") - _leaderboard_metric(
        baseline,
        "policy_adjusted_rate",
    )
    boundary_warnings = _leaderboard_boundary_warnings(row, baseline, scope=scope, target_role=target_role)
    is_reference = bool(baseline_key and row_key == baseline_key)
    comparable = bool(baseline and not boundary_warnings)
    if is_reference:
        change = "reference"
    elif not comparable:
        change = "incomparable"
    elif score_delta > 0:
        change = "improvement"
    elif score_delta < 0:
        change = "regression"
    else:
        change = "stable"
    games = int(_leaderboard_metric(row, "games_played", "game_count", "total_games"))
    baseline_games = int(_leaderboard_metric(baseline, "games_played", "game_count", "total_games"))
    statistics = _leaderboard_compare_statistics(
        row,
        baseline,
        boundary_warnings=boundary_warnings,
        is_reference=is_reference,
        win_rate_delta=win_rate_delta,
    )
    confidence = "low_sample" if "low_sample" in statistics["warnings"] or games < 30 or baseline_games < 30 else (
        "significant" if statistics["significant"] else "not_significant"
    )
    payload = dict(row)
    payload.update(
        {
            "is_reference": is_reference,
            "baseline_subject_id": baseline_key or None,
            "comparable": comparable,
            "boundary_warnings": boundary_warnings,
            "change": change,
            "confidence": confidence,
            **statistics,
            "delta": {
                "score": score_delta,
                "target_side_win_rate": win_rate_delta,
                "paired_delta": statistics["paired_delta"],
                "fallback_rate": fallback_delta,
                "llm_error_rate": llm_error_delta,
                "policy_adjusted_rate": policy_adjusted_delta,
            },
            "delta_vs_baseline": {
                "score": score_delta,
                "target_role_role_weighted_score": score_delta,
                "strength_score": score_delta,
                "target_side_win_rate": win_rate_delta,
                "paired_delta": statistics["paired_delta"],
                "fallback_rate": fallback_delta,
                "llm_error_rate": llm_error_delta,
                "policy_adjusted_rate": policy_adjusted_delta,
            },
        }
    )
    return payload


def _leaderboard_compare_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    changes = Counter(str(row.get("change") or "unknown") for row in rows)
    return {
        "row_count": len(rows),
        "rankable_count": sum(1 for row in rows if row.get("rankable") is not False),
        "unrankable_count": sum(1 for row in rows if row.get("rankable") is False),
        "improvement_count": changes.get("improvement", 0),
        "regression_count": changes.get("regression", 0),
        "stable_count": changes.get("stable", 0),
        "incomparable_count": changes.get("incomparable", 0),
        "reference_count": changes.get("reference", 0),
        "boundary_mismatch_count": sum(1 for row in rows if row.get("boundary_warnings")),
        "significant_count": sum(1 for row in rows if row.get("significant") is True),
        "not_significant_count": sum(
            1
            for row in rows
            if row.get("significant") is False and str(row.get("significance_label") or "") == "差异不显著"
        ),
        "low_sample_count": sum(1 for row in rows if "low_sample" in set(row.get("warnings") or [])),
        "unpaired_seed_count": sum(1 for row in rows if "unpaired_seeds" in set(row.get("warnings") or [])),
        "insufficient_overlap_count": sum(
            1 for row in rows if "insufficient_overlap" in set(row.get("warnings") or [])
        ),
        "by_change": dict(sorted(changes.items())),
    }
