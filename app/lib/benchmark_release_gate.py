"""Standalone benchmark release gate evaluation helpers.

The helpers in this module are intentionally pure and store-agnostic so the UI
backend can adopt them without coupling the gate rules to persistence.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any


LAUNCHABLE_SUITE_STATUSES = {"enabled", "active"}
NON_LAUNCHABLE_SUITE_STATUSES = {"draft", "deprecated", "disabled", "archived"}
DEFAULT_BLOCKING_DIAGNOSTIC_LEVELS = {"error", "critical", "fatal"}
DEFAULT_WARNING_DIAGNOSTIC_LEVELS = {"warning"}
SEVERITY_RANK = {
    "trace": 0,
    "debug": 0,
    "info": 1,
    "notice": 1,
    "warning": 2,
    "warn": 2,
    "error": 3,
    "critical": 4,
    "fatal": 5,
}


def evaluate_benchmark_release_gate(
    snapshot: Any | None = None,
    request: Any | None = None,
    rows: Iterable[Any] | None = None,
    thresholds: Mapping[str, Any] | None = None,
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate whether benchmark rows are eligible for formal release.

    Args:
        snapshot: Existing or proposed snapshot payload. May contain ``rows``.
        request: Snapshot/release request payload or equivalent object.
        rows: Explicit leaderboard/report rows. Overrides rows embedded in the
            snapshot or request.
        thresholds: Gate thresholds such as ``min_sample_size``.
        config: Optional suite/gate config. ``config["gates"]`` and
            ``config["thresholds"]`` are also recognized.

    Returns:
        A JSON-safe dict with ``ok``, ``blockers``, ``warnings`` and
        ``summary``.
    """

    snapshot_data = _as_mapping(snapshot)
    request_data = _as_mapping(request)
    config_data = _as_mapping(config)
    gate_thresholds = _resolve_thresholds(thresholds, config_data)
    row_items = _resolve_rows(rows, snapshot_data, request_data)

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    row_summaries: list[dict[str, Any]] = []
    diagnostic_counts: Counter[str] = Counter()

    requested_scope = _normalize_text(
        _first_text(
            request_data.get("scope"),
            snapshot_data.get("scope"),
            config_data.get("scope"),
            _first_row_value(row_items, "scope"),
        )
    )
    requested_hash = _first_text(
        request_data.get("benchmark_config_hash"),
        request_data.get("config_hash"),
        snapshot_data.get("benchmark_config_hash"),
        snapshot_data.get("config_hash"),
        config_data.get("benchmark_config_hash"),
        config_data.get("config_hash"),
    )
    release_context = _release_context(snapshot_data, request_data, config_data)

    if not requested_scope:
        blockers.append(
            _issue(
                "scope_missing",
                "error",
                "Release gate requires an explicit snapshot scope.",
                evidence=release_context,
                affected_ids=_context_ids(snapshot_data, request_data, config_data),
            )
        )
    if not requested_hash:
        blockers.append(
            _issue(
                "benchmark_config_hash_missing",
                "error",
                "Release gate requires benchmark_config_hash on the release request.",
                evidence=release_context,
                affected_ids=_context_ids(snapshot_data, request_data, config_data),
            )
        )

    lifecycle_state = _suite_lifecycle_state(snapshot_data, request_data, config_data)
    if gate_thresholds["require_suite_lifecycle"] and not lifecycle_state["present"]:
        blockers.append(
            _issue(
                "suite_lifecycle_missing",
                "error",
                "Release gate requires benchmark suite lifecycle evidence.",
                evidence=lifecycle_state,
                affected_ids=_context_ids(snapshot_data, request_data, config_data),
            )
        )
    elif lifecycle_state["present"] and not lifecycle_state["launchable"]:
        blockers.append(
            _issue(
                "suite_not_launchable",
                "error",
                "Benchmark suite lifecycle is not launchable for release.",
                evidence=lifecycle_state,
                affected_ids=_context_ids(snapshot_data, request_data, config_data),
            )
        )

    if not row_items:
        blockers.append(
            _issue(
                "rows_empty",
                "error",
                "Release gate requires at least one benchmark row.",
                evidence=release_context,
                affected_ids=_context_ids(snapshot_data, request_data, config_data),
            )
        )

    for index, raw_row in enumerate(row_items):
        row = _as_mapping(raw_row)
        if not row:
            affected_ids = [f"row:{index}"]
            blockers.append(
                _issue(
                    "row_not_structured",
                    "error",
                    "Benchmark release rows must be structured objects.",
                    evidence={"row_index": index, "row_type": type(raw_row).__name__},
                    affected_ids=affected_ids,
                )
            )
            row_summaries.append(
                {
                    "index": index,
                    "affected_ids": affected_ids,
                    "scope": "",
                    "benchmark_config_hash": "",
                    "sample_size": 0,
                    "completed_games": 0,
                    "paired_overlap": 0,
                    "diagnostic_count": 0,
                }
            )
            continue

        summary = _row_summary(row)
        affected_ids = _row_affected_ids(row, index=index)
        row_scope = _normalize_text(_first_text(row.get("scope"), summary.get("scope")))
        row_hash = _row_benchmark_config_hash(row, summary)
        sample_size = _row_int(
            row,
            summary,
            "sample_size",
            "games_played",
            "game_count",
            "completed_games",
        )
        completed_games = _row_int(
            row,
            summary,
            "completed_games",
            "games_played",
            "game_count",
            "sample_size",
        )
        paired_overlap = _row_int(
            row,
            summary,
            "paired_sample_size",
            "paired_valid_count",
            "paired_valid_seeds",
            "paired_overlap",
        )

        if not row_scope:
            blockers.append(
                _issue(
                    "row_scope_missing",
                    "error",
                    "Benchmark release row is missing scope.",
                    evidence={"row_index": index},
                    affected_ids=affected_ids,
                )
            )
        elif requested_scope and row_scope != requested_scope:
            blockers.append(
                _issue(
                    "row_scope_mismatch",
                    "error",
                    "Benchmark release row scope does not match the requested scope.",
                    evidence={"row_index": index, "expected": requested_scope, "actual": row_scope},
                    affected_ids=affected_ids,
                )
            )

        if requested_scope == "model":
            model_hash = _first_text(
                row.get("model_config_hash"),
                summary.get("model_config_hash"),
                _as_mapping(row.get("model_runtime")).get("model_config_hash"),
                _as_mapping(summary.get("model_runtime")).get("model_config_hash"),
            )
            if not model_hash:
                blockers.append(
                    _issue(
                        "model_config_hash_missing",
                        "error",
                        "Model-scope benchmark release rows must include model_config_hash.",
                        evidence={"row_index": index, "scope": row_scope or requested_scope},
                        affected_ids=affected_ids,
                    )
                )

        if not row_hash:
            blockers.append(
                _issue(
                    "row_benchmark_config_hash_missing",
                    "error",
                    "Benchmark release row is missing benchmark_config_hash.",
                    evidence={"row_index": index},
                    affected_ids=affected_ids,
                )
            )
        elif requested_hash and row_hash != requested_hash:
            blockers.append(
                _issue(
                    "benchmark_config_hash_mismatch",
                    "error",
                    "Benchmark release row benchmark_config_hash does not match the request.",
                    evidence={"row_index": index, "expected": requested_hash, "actual": row_hash},
                    affected_ids=affected_ids,
                )
            )

        source_run_id = _row_source_value(row, summary, "source_run_id")
        report_id = _row_source_value(row, summary, "report_id")
        result_batch_id = _row_source_value(row, summary, "result_batch_id")
        if not source_run_id:
            blockers.append(
                _issue(
                    "source_run_id_missing",
                    "error",
                    "Benchmark release row is missing source_run_id.",
                    evidence={"row_index": index},
                    affected_ids=affected_ids,
                )
            )
        if not report_id:
            blockers.append(
                _issue(
                    "report_id_missing",
                    "error",
                    "Benchmark release row is missing report_id.",
                    evidence={"row_index": index},
                    affected_ids=affected_ids,
                )
            )
        if not result_batch_id:
            blockers.append(
                _issue(
                    "result_batch_id_missing",
                    "error",
                    "Benchmark release row is missing result_batch_id.",
                    evidence={"row_index": index},
                    affected_ids=affected_ids,
                )
            )

        if gate_thresholds["min_sample_size"] > 0 and sample_size < gate_thresholds["min_sample_size"]:
            blockers.append(
                _issue(
                    "sample_size_below_minimum",
                    "error",
                    "Benchmark release row sample_size is below the configured minimum.",
                    evidence={
                        "row_index": index,
                        "sample_size": sample_size,
                        "min_sample_size": gate_thresholds["min_sample_size"],
                    },
                    affected_ids=affected_ids,
                )
            )
        if gate_thresholds["min_completed_games"] > 0 and completed_games < gate_thresholds["min_completed_games"]:
            blockers.append(
                _issue(
                    "completed_games_below_minimum",
                    "error",
                    "Benchmark release row completed games are below the configured minimum.",
                    evidence={
                        "row_index": index,
                        "completed_games": completed_games,
                        "min_completed_games": gate_thresholds["min_completed_games"],
                    },
                    affected_ids=affected_ids,
                )
            )
        if gate_thresholds["min_paired_overlap"] > 0 and paired_overlap < gate_thresholds["min_paired_overlap"]:
            blockers.append(
                _issue(
                    "paired_overlap_below_minimum",
                    "error",
                    "Benchmark release row paired overlap is below the configured minimum.",
                    evidence={
                        "row_index": index,
                        "paired_overlap": paired_overlap,
                        "min_paired_overlap": gate_thresholds["min_paired_overlap"],
                    },
                    affected_ids=affected_ids,
                )
            )

        row_diagnostics = _diagnostics_from(row, summary)
        _append_diagnostic_issues(
            row_diagnostics,
            blockers=blockers,
            warnings=warnings,
            thresholds=gate_thresholds,
            source={"origin": "row", "row_index": index},
            affected_ids=affected_ids,
            diagnostic_counts=diagnostic_counts,
        )
        row_summaries.append(
            {
                "index": index,
                "affected_ids": affected_ids,
                "scope": row_scope,
                "benchmark_config_hash": row_hash,
                "sample_size": sample_size,
                "completed_games": completed_games,
                "paired_overlap": paired_overlap,
                "diagnostic_count": len(row_diagnostics),
                "source_run_id": source_run_id,
                "report_id": report_id,
                "result_batch_id": result_batch_id,
            }
        )

    global_diagnostics = _diagnostics_from(snapshot_data) + _diagnostics_from(request_data)
    _append_diagnostic_issues(
        global_diagnostics,
        blockers=blockers,
        warnings=warnings,
        thresholds=gate_thresholds,
        source={"origin": "release"},
        affected_ids=_context_ids(snapshot_data, request_data, config_data),
        diagnostic_counts=diagnostic_counts,
    )

    summary = {
        "scope": requested_scope,
        "benchmark_config_hash": requested_hash,
        "row_count": len(row_items),
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "thresholds": _public_thresholds(gate_thresholds),
        "suite_lifecycle": lifecycle_state,
        "diagnostics": {
            "total": sum(diagnostic_counts.values()),
            "by_level": dict(sorted(diagnostic_counts.items())),
        },
        "rows": row_summaries,
    }
    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "summary": _json_safe(summary),
    }


def _resolve_rows(
    rows: Iterable[Any] | None,
    snapshot_data: Mapping[str, Any],
    request_data: Mapping[str, Any],
) -> list[Any]:
    if rows is None:
        rows = snapshot_data.get("rows")
        if rows is None:
            rows = request_data.get("rows")
    if rows is None:
        return []
    if isinstance(rows, Mapping) or isinstance(rows, (str, bytes)):
        return [rows]
    try:
        return list(rows)
    except TypeError:
        return [rows]


def _resolve_thresholds(thresholds: Mapping[str, Any] | None, config_data: Mapping[str, Any]) -> dict[str, Any]:
    raw: dict[str, Any] = {}
    for source in (
        _as_mapping(config_data.get("gates")),
        _as_mapping(config_data.get("thresholds")),
        config_data,
        _as_mapping(thresholds),
    ):
        raw.update(source)

    blocking_levels = _normalize_level_set(
        raw.get("blocking_diagnostic_levels")
        or raw.get("block_diagnostic_levels")
        or raw.get("blocked_diagnostic_levels")
        or DEFAULT_BLOCKING_DIAGNOSTIC_LEVELS
    )
    max_level = _normalize_text(raw.get("max_diagnostic_severity") or raw.get("max_allowed_diagnostic_level"))
    if max_level in SEVERITY_RANK:
        max_rank = SEVERITY_RANK[max_level]
        blocking_levels.update(level for level, rank in SEVERITY_RANK.items() if rank > max_rank)

    return {
        "min_sample_size": max(
            0,
            _first_int(
                raw.get("min_sample_size"),
                raw.get("sample_size"),
                raw.get("min_samples"),
                default=0,
            ),
        ),
        "min_completed_games": max(
            0,
            _first_int(
                raw.get("min_completed_games"),
                raw.get("min_completed"),
                raw.get("minimum_completed_games"),
                default=0,
            ),
        ),
        "min_paired_overlap": max(
            0,
            _first_int(
                raw.get("min_paired_overlap"),
                raw.get("min_paired_sample_size"),
                raw.get("min_paired_valid_seeds"),
                raw.get("min_paired_valid_seed_count"),
                default=0,
            ),
        ),
        "blocking_diagnostic_levels": blocking_levels,
        "warning_diagnostic_levels": _normalize_level_set(
            raw.get("warning_diagnostic_levels")
            or raw.get("warn_diagnostic_levels")
            or DEFAULT_WARNING_DIAGNOSTIC_LEVELS
        ),
        "require_suite_lifecycle": _first_bool(raw.get("require_suite_lifecycle"), default=True),
    }


def _public_thresholds(thresholds: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "min_sample_size": thresholds["min_sample_size"],
        "min_completed_games": thresholds["min_completed_games"],
        "min_paired_overlap": thresholds["min_paired_overlap"],
        "blocking_diagnostic_levels": sorted(thresholds["blocking_diagnostic_levels"]),
        "warning_diagnostic_levels": sorted(thresholds["warning_diagnostic_levels"]),
        "require_suite_lifecycle": thresholds["require_suite_lifecycle"],
    }


def _suite_lifecycle_state(
    snapshot_data: Mapping[str, Any],
    request_data: Mapping[str, Any],
    config_data: Mapping[str, Any],
) -> dict[str, Any]:
    lifecycle = _find_lifecycle(config_data, request_data, snapshot_data)
    if not lifecycle:
        return {"present": False, "status": "", "launchable": False, "source": ""}

    data, source = lifecycle
    status = _normalize_text(_first_text(data.get("status"), data.get("state"), data.get("lifecycle_status")))
    launchable = _first_bool(data.get("launchable"), data.get("suite_launchable"), default=None)
    if launchable is None and "enabled" in data:
        launchable = _first_bool(data.get("enabled"), default=None)
    if status in NON_LAUNCHABLE_SUITE_STATUSES:
        launchable = False
    elif launchable is None and status:
        launchable = status in LAUNCHABLE_SUITE_STATUSES
    elif launchable is None:
        launchable = False

    return {
        "present": True,
        "status": status,
        "launchable": bool(launchable),
        "source": source,
        "allowed_statuses": sorted(LAUNCHABLE_SUITE_STATUSES),
    }


def _find_lifecycle(*sources: Mapping[str, Any]) -> tuple[dict[str, Any], str] | None:
    for source_index, source in enumerate(sources):
        for key in ("suite_lifecycle", "lifecycle", "benchmark_lifecycle"):
            value = _as_mapping(source.get(key))
            if value:
                return value, key
        for key in ("suite", "benchmark", "spec", "item"):
            container = _as_mapping(source.get(key))
            for lifecycle_key in ("lifecycle", "suite_lifecycle", "benchmark_lifecycle"):
                value = _as_mapping(container.get(lifecycle_key))
                if value:
                    return value, f"{key}.{lifecycle_key}"
        direct = {
            key: source.get(key)
            for key in ("status", "state", "lifecycle_status", "launchable", "suite_launchable", "enabled")
            if key in source
        }
        if direct:
            return direct, f"source:{source_index}"
    return None


def _append_diagnostic_issues(
    diagnostics: list[dict[str, Any]],
    *,
    blockers: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    thresholds: Mapping[str, Any],
    source: Mapping[str, Any],
    affected_ids: list[str],
    diagnostic_counts: Counter[str],
) -> None:
    for index, diagnostic in enumerate(diagnostics):
        level = _diagnostic_level(diagnostic)
        diagnostic_counts[level] += 1
        evidence = {
            **dict(source),
            "diagnostic_index": index,
            "level": level,
            "kind": _first_text(diagnostic.get("kind"), diagnostic.get("code"), diagnostic.get("type")),
            "message": _first_text(diagnostic.get("message"), diagnostic.get("detail"), diagnostic.get("reason")),
        }
        ids = _unique_strings(
            [
                *affected_ids,
                diagnostic.get("game_id"),
                diagnostic.get("seed"),
                diagnostic.get("source_run_id"),
                diagnostic.get("result_batch_id"),
            ]
        )
        if level in thresholds["blocking_diagnostic_levels"]:
            blockers.append(
                _issue(
                    "diagnostic_severity_blocked",
                    "error",
                    "Benchmark release has diagnostics at a blocking severity.",
                    evidence=evidence,
                    affected_ids=ids,
                )
            )
        elif level in thresholds["warning_diagnostic_levels"]:
            warnings.append(
                _issue(
                    "diagnostic_warning_present",
                    "warning",
                    "Benchmark release has diagnostics that should be reviewed.",
                    evidence=evidence,
                    affected_ids=ids,
                )
            )


def _diagnostics_from(*sources: Mapping[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    for source in sources:
        for key in ("diagnostics", "diagnostic_items", "issues"):
            value = source.get(key)
            if isinstance(value, Mapping):
                value = value.get("items") or value.get("diagnostics") or [value]
            if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
                for item in value:
                    diagnostic = _as_mapping(item)
                    if diagnostic:
                        diagnostics.append(diagnostic)
    return diagnostics


def _diagnostic_level(diagnostic: Mapping[str, Any]) -> str:
    level = _normalize_text(
        _first_text(
            diagnostic.get("level"),
            diagnostic.get("severity"),
            diagnostic.get("status"),
            "info",
        )
    )
    return "warning" if level == "warn" else level


def _row_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return _as_mapping(row.get("summary"))


def _row_benchmark_config_hash(row: Mapping[str, Any], summary: Mapping[str, Any]) -> str:
    return _first_text(
        row.get("benchmark_config_hash"),
        row.get("config_hash"),
        summary.get("benchmark_config_hash"),
        summary.get("config_hash"),
    )


def _row_source_value(row: Mapping[str, Any], summary: Mapping[str, Any], key: str) -> str:
    if key == "source_run_id":
        return _first_text(
            row.get("source_run_id"),
            row.get("run_id"),
            row.get("batch_id"),
            summary.get("source_run_id"),
            summary.get("run_id"),
            summary.get("batch_id"),
        )
    if key == "report_id":
        return _first_text(
            row.get("report_id"),
            row.get("source_report_id"),
            summary.get("report_id"),
            summary.get("source_report_id"),
        )
    if key == "result_batch_id":
        return _first_text(row.get("result_batch_id"), summary.get("result_batch_id"))
    return _first_text(row.get(key), summary.get(key))


def _row_int(row: Mapping[str, Any], summary: Mapping[str, Any], *keys: str) -> int:
    values: list[Any] = []
    for key in keys:
        values.append(row.get(key))
        values.append(summary.get(key))
    return _first_int(*values, default=0)


def _row_affected_ids(row: Mapping[str, Any], *, index: int) -> list[str]:
    summary = _row_summary(row)
    ids = _unique_strings(
        [
            row.get("subject_id"),
            row.get("hash"),
            row.get("target_version_id"),
            row.get("model_config_hash"),
            row.get("model_id"),
            row.get("result_batch_id"),
            row.get("source_run_id"),
            row.get("batch_id"),
            row.get("report_id"),
            summary.get("subject_id"),
            summary.get("result_batch_id"),
        ]
    )
    return ids or [f"row:{index}"]


def _context_ids(*sources: Mapping[str, Any]) -> list[str]:
    values: list[Any] = []
    for source in sources:
        values.extend(
            [
                source.get("snapshot_id"),
                source.get("benchmark_id"),
                source.get("evaluation_set_id"),
                source.get("seed_set_id"),
                source.get("report_id"),
                source.get("source_run_id"),
                source.get("batch_id"),
            ]
        )
        suite = _as_mapping(source.get("suite"))
        values.append(suite.get("benchmark_id") or suite.get("id"))
    return _unique_strings(values)


def _release_context(
    snapshot_data: Mapping[str, Any],
    request_data: Mapping[str, Any],
    config_data: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "snapshot_id": _first_text(snapshot_data.get("snapshot_id"), request_data.get("snapshot_id")),
        "benchmark_id": _first_text(
            request_data.get("benchmark_id"),
            snapshot_data.get("benchmark_id"),
            config_data.get("benchmark_id"),
            _as_mapping(config_data.get("suite")).get("benchmark_id"),
            _as_mapping(config_data.get("suite")).get("id"),
        ),
        "scope": _first_text(request_data.get("scope"), snapshot_data.get("scope"), config_data.get("scope")),
        "benchmark_config_hash": _first_text(
            request_data.get("benchmark_config_hash"),
            snapshot_data.get("benchmark_config_hash"),
            config_data.get("benchmark_config_hash"),
        ),
    }


def _first_row_value(rows: list[Any], key: str) -> Any:
    for row in rows:
        mapping = _as_mapping(row)
        summary = _row_summary(mapping)
        value = _first_text(mapping.get(key), summary.get(key))
        if value:
            return value
    return ""


def _issue(
    code: str,
    severity: str,
    message: str,
    *,
    evidence: Mapping[str, Any] | None = None,
    affected_ids: Iterable[Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "message": message,
        "evidence": _json_safe(dict(evidence or {})),
        "affected_ids": _unique_strings(affected_ids or []),
    }


def _as_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    if hasattr(value, "dict"):
        dumped = value.dict()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    if hasattr(value, "__dict__"):
        return dict(vars(value))
    return {}


def _first_text(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _normalize_text(value: Any) -> str:
    return _first_text(value).strip().lower()


def _first_int(*values: Any, default: int = 0) -> int:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return int(float(value))
            except (TypeError, ValueError):
                continue
    return default


def _first_bool(*values: Any, default: bool | None = False) -> bool | None:
    for value in values:
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "y", "on", "enabled", "active", "launchable"}:
            return True
        if text in {"0", "false", "no", "n", "off", "disabled", "deprecated", "archived", "draft"}:
            return False
    return default


def _normalize_level_set(value: Any) -> set[str]:
    if isinstance(value, str):
        return {_normalize_text(item) for item in value.split(",") if _normalize_text(item)}
    if isinstance(value, Iterable):
        return {_normalize_text(item) for item in value if _normalize_text(item)}
    return set()


def _unique_strings(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            output.append(text)
    return output


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
