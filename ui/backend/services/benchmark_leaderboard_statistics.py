"""Benchmark leaderboard statistical evidence helpers."""

from __future__ import annotations

import math
from typing import Any

from ui.backend.services.benchmark_payload_utils import first_text as _first_text

_LEADERBOARD_CONFIDENCE_LEVEL = 0.95
_LEADERBOARD_Z_95 = 1.96
_LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE = 30
_LEADERBOARD_MIN_PAIRED_OVERLAP = _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE


def _first_int(*values: Any, default: int = 0) -> int:
    for value in values:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            continue
        return number
    return default


def _first_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            return number
    return default


def _leaderboard_row_statistics(row: dict[str, Any] | None) -> dict[str, Any]:
    """Return row-level binomial confidence evidence for leaderboard payloads."""
    if not row:
        return _empty_leaderboard_statistics()
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    sample_size = _first_int(
        row.get("sample_size"),
        summary.get("sample_size"),
        row.get("completed_games"),
        row.get("completed"),
        summary.get("completed_games"),
        summary.get("win_rate_denominator"),
        row.get("games_played"),
        row.get("game_count"),
        summary.get("games_played"),
        summary.get("game_count"),
        default=0,
    )
    win_rate = _probability_from_value(
        _first_float(
            row.get("target_side_win_rate"),
            row.get("win_rate"),
            summary.get("target_side_win_rate"),
            summary.get("win_rate"),
            default=0.0,
        )
    )
    standard_error = _binomial_standard_error(win_rate, sample_size)
    ci_low, ci_high = _wilson_confidence_interval(win_rate, sample_size)
    paired_sample_size = _first_int(
        row.get("paired_sample_size"),
        summary.get("paired_sample_size"),
        summary.get("paired_valid_count"),
        default=0,
    )
    paired_delta = _optional_probability_delta(
        row.get("paired_delta"),
        summary.get("paired_delta"),
        summary.get("paired_seed_delta"),
    )
    warnings = _stat_warning_list(row.get("warnings"), summary.get("warnings"))
    if sample_size < _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE:
        warnings.append("low_sample")
    warnings = _dedupe_warning_codes(warnings)
    return {
        "sample_size": sample_size,
        "paired_sample_size": paired_sample_size,
        "win_rate_ci": {
            "low": ci_low,
            "high": ci_high,
            "level": _LEADERBOARD_CONFIDENCE_LEVEL,
        },
        "ci_low": ci_low,
        "ci_high": ci_high,
        "standard_error": standard_error,
        "paired_delta": paired_delta,
        "score_sample_size": _first_int(
            row.get("score_sample_size"),
            summary.get("score_sample_size"),
            default=sample_size,
        ),
        "score_stddev": _first_float(
            row.get("score_stddev"),
            row.get("role_score_stddev"),
            summary.get("score_stddev"),
            summary.get("role_score_stddev"),
            default=0.0,
        ),
        "score_standard_error": _first_float(
            row.get("score_standard_error"),
            row.get("role_score_standard_error"),
            summary.get("score_standard_error"),
            summary.get("role_score_standard_error"),
            default=0.0,
        ),
        "score_ci": _score_confidence_interval(row, summary),
        "valid_game_count": _first_int(
            row.get("valid_game_count"),
            summary.get("valid_game_count"),
            summary.get("completed_games"),
            default=sample_size,
        ),
        "abnormal_game_count": _first_int(
            row.get("abnormal_game_count"),
            summary.get("abnormal_game_count"),
            default=0,
        ),
        "significant": bool(row.get("significant", False)),
        "significance_label": str(row.get("significance_label") or "待比较"),
        "warnings": warnings,
    }


def _empty_leaderboard_statistics() -> dict[str, Any]:
    return {
        "sample_size": 0,
        "paired_sample_size": 0,
        "win_rate_ci": {"low": 0.0, "high": 0.0, "level": _LEADERBOARD_CONFIDENCE_LEVEL},
        "ci_low": 0.0,
        "ci_high": 0.0,
        "standard_error": 0.0,
        "paired_delta": None,
        "score_sample_size": 0,
        "score_stddev": 0.0,
        "score_standard_error": 0.0,
        "score_ci": {"low": 0.0, "high": 0.0, "level": _LEADERBOARD_CONFIDENCE_LEVEL},
        "valid_game_count": 0,
        "abnormal_game_count": 0,
        "significant": False,
        "significance_label": "待比较",
        "warnings": ["low_sample"],
    }


def _score_confidence_interval(row: dict[str, Any], summary: dict[str, Any]) -> dict[str, float]:
    for candidate in (row.get("score_ci"), row.get("role_score_ci"), summary.get("score_ci"), summary.get("role_score_ci")):
        if isinstance(candidate, dict):
            return {
                "low": _first_float(candidate.get("low"), default=0.0),
                "high": _first_float(candidate.get("high"), default=0.0),
                "level": _first_float(candidate.get("level"), default=_LEADERBOARD_CONFIDENCE_LEVEL),
            }
    return {"low": 0.0, "high": 0.0, "level": _LEADERBOARD_CONFIDENCE_LEVEL}


def _probability_from_value(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    if abs(number) > 1 and abs(number) <= 100:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _optional_probability_delta(*values: Any) -> float | None:
    for value in values:
        if value is None or value == "":
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(number):
            continue
        if abs(number) > 1 and abs(number) <= 100:
            number = number / 100.0
        return number
    return None


def _binomial_standard_error(win_rate: float, sample_size: int) -> float:
    if sample_size <= 0:
        return 0.0
    probability = max(0.0, min(1.0, float(win_rate)))
    return math.sqrt((probability * (1.0 - probability)) / sample_size)


def _wilson_confidence_interval(win_rate: float, sample_size: int) -> tuple[float, float]:
    if sample_size <= 0:
        return 0.0, 0.0
    probability = max(0.0, min(1.0, float(win_rate)))
    z_squared = _LEADERBOARD_Z_95 ** 2
    denominator = 1.0 + (z_squared / sample_size)
    center = (probability + (z_squared / (2 * sample_size))) / denominator
    half_width = (
        _LEADERBOARD_Z_95
        * math.sqrt((probability * (1.0 - probability) / sample_size) + (z_squared / (4 * sample_size ** 2)))
        / denominator
    )
    return (
        max(0.0, min(1.0, center - half_width)),
        max(0.0, min(1.0, center + half_width)),
    )


def _stat_warning_list(*values: Any) -> list[str]:
    warnings: list[str] = []
    for value in values:
        if isinstance(value, str):
            warnings.append(value)
        elif isinstance(value, list):
            warnings.extend(str(item) for item in value)
        elif isinstance(value, dict):
            warnings.extend(str(key) for key, enabled in value.items() if enabled)
    return warnings


def _dedupe_warning_codes(values: list[str]) -> list[str]:
    allowed = {"low_sample", "unpaired_seeds", "insufficient_overlap"}
    warnings: list[str] = []
    for value in values:
        code = str(value or "").strip()
        if code in allowed and code not in warnings:
            warnings.append(code)
    return warnings


def _leaderboard_seed_metrics(row: dict[str, Any] | None) -> dict[str, float]:
    if not row:
        return {}
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    candidates = (
        row.get("seed_metrics"),
        row.get("paired_seed_metrics"),
        row.get("per_seed_metrics"),
        summary.get("seed_metrics"),
        summary.get("paired_seed_metrics"),
        summary.get("per_seed_metrics"),
        summary.get("seed_results"),
        summary.get("per_seed"),
    )
    metrics: dict[str, float] = {}
    for candidate in candidates:
        if isinstance(candidate, dict):
            iterable = [{"seed": seed, "value": value} for seed, value in candidate.items()]
        elif isinstance(candidate, list):
            iterable = candidate
        else:
            continue
        for index, item in enumerate(iterable):
            if not isinstance(item, dict):
                continue
            key = _leaderboard_seed_metric_key(item, index)
            if not key:
                continue
            value = _seed_metric_value(item)
            if value is not None:
                metrics[key] = value
    return metrics


def _leaderboard_seed_metric_key(item: dict[str, Any], index: int) -> str:
    seed = _first_text(item.get("seed"), item.get("seed_id"), item.get("id"))
    if seed:
        return f"seed:{seed}"
    pair_key = _first_text(item.get("pair_key"), item.get("paired_key"), item.get("pair_id"))
    if pair_key:
        return f"pair:{pair_key}"
    game_id = _first_text(item.get("source_game_id"), item.get("game_id"))
    if game_id:
        return f"game:{game_id}"
    return f"index:{index}"


def _seed_metric_value(item: dict[str, Any]) -> float | None:
    for key in (
        "target_side_win",
        "target_side_won",
        "win",
        "won",
        "value",
        "target_side_win_rate",
        "score",
    ):
        value = item.get(key)
        if value is None or value == "":
            continue
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        text = str(value).strip().lower()
        if text in {"win", "won", "true", "yes"}:
            return 1.0
        if text in {"loss", "lost", "false", "no"}:
            return 0.0
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return _probability_from_value(number)
    return None


def _leaderboard_paired_evidence(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> tuple[float | None, int, list[str]]:
    if not baseline:
        return None, 0, []
    row_metrics = _leaderboard_seed_metrics(row)
    baseline_metrics = _leaderboard_seed_metrics(baseline)
    if not row_metrics or not baseline_metrics:
        return None, 0, ["unpaired_seeds"]
    overlap = sorted(set(row_metrics).intersection(baseline_metrics))
    if not overlap:
        return None, 0, ["insufficient_overlap"]
    deltas = [row_metrics[seed] - baseline_metrics[seed] for seed in overlap]
    paired_delta = sum(deltas) / len(deltas)
    warnings: list[str] = []
    if len(overlap) < min(len(row_metrics), len(baseline_metrics)):
        warnings.append("unpaired_seeds")
    if len(overlap) < _LEADERBOARD_MIN_PAIRED_OVERLAP:
        warnings.append("insufficient_overlap")
    return paired_delta, len(overlap), warnings


def _paired_win_statistics(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
) -> dict[str, Any]:
    if not baseline:
        return _empty_paired_win_statistics()
    row_metrics = _leaderboard_seed_metrics(row)
    baseline_metrics = _leaderboard_seed_metrics(baseline)
    overlap = sorted(set(row_metrics).intersection(baseline_metrics))
    deltas = [row_metrics[key] - baseline_metrics[key] for key in overlap]
    wins = sum(1 for delta in deltas if delta > 0)
    losses = sum(1 for delta in deltas if delta < 0)
    ties = len(deltas) - wins - losses
    decisive = wins + losses
    paired_win_rate = wins / decisive if decisive else None
    p_value = _two_sided_binomial_sign_test(wins, losses) if decisive else None
    return {
        "paired_wins": wins,
        "paired_losses": losses,
        "paired_ties": ties,
        "paired_decisive_count": decisive,
        "paired_win_rate": paired_win_rate,
        "paired_p_value": p_value,
    }


def _empty_paired_win_statistics() -> dict[str, Any]:
    return {
        "paired_wins": 0,
        "paired_losses": 0,
        "paired_ties": 0,
        "paired_decisive_count": 0,
        "paired_win_rate": None,
        "paired_p_value": None,
    }


def _two_sided_binomial_sign_test(wins: int, losses: int) -> float:
    sample_size = wins + losses
    if sample_size <= 0:
        return 1.0
    tail = min(wins, losses)
    probability = sum(math.comb(sample_size, index) for index in range(tail + 1)) / (2 ** sample_size)
    return min(1.0, 2.0 * probability)


def _leaderboard_compare_statistics(
    row: dict[str, Any],
    baseline: dict[str, Any] | None,
    *,
    boundary_warnings: list[str],
    is_reference: bool,
    win_rate_delta: float,
) -> dict[str, Any]:
    row_stats = _leaderboard_row_statistics(row)
    baseline_stats = _leaderboard_row_statistics(baseline)
    warnings = list(row_stats["warnings"])
    if baseline and baseline_stats["sample_size"] < _LEADERBOARD_MIN_CONFIDENT_SAMPLE_SIZE:
        warnings.append("low_sample")
    paired_delta, paired_sample_size, paired_warnings = _leaderboard_paired_evidence(row, baseline)
    paired_win_stats = _paired_win_statistics(row, baseline)
    warnings.extend(paired_warnings)
    paired_delta_error = None
    if paired_sample_size > 0:
        paired_delta_error = math.sqrt(
            (float(row_stats["standard_error"] or 0.0) ** 2)
            + (float(baseline_stats["standard_error"] or 0.0) ** 2)
        )
    combined_standard_error = math.sqrt(
        float(row_stats["standard_error"] or 0.0) ** 2
        + float(baseline_stats["standard_error"] or 0.0) ** 2
    )
    warning_codes = _dedupe_warning_codes(warnings)
    statistically_significant = bool(
        baseline
        and not is_reference
        and not boundary_warnings
        and paired_delta is not None
        and "low_sample" not in warning_codes
        and "unpaired_seeds" not in warning_codes
        and "insufficient_overlap" not in warning_codes
        and paired_win_stats["paired_p_value"] is not None
        and float(paired_win_stats["paired_p_value"]) < 0.05
    )
    if is_reference:
        label = "基线参考"
    elif boundary_warnings:
        label = "不可比较"
    elif statistically_significant:
        label = "显著提升" if win_rate_delta > 0 else "显著回退"
    elif baseline:
        label = "差异不显著"
    else:
        label = "等待基线"
    return {
        **row_stats,
        "paired_sample_size": paired_sample_size,
        "paired_delta": paired_delta,
        **paired_win_stats,
        "standard_error": row_stats["standard_error"],
        "combined_standard_error": combined_standard_error,
        "significant": statistically_significant,
        "significance_label": label,
        "warnings": warning_codes,
    }
