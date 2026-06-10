"""Benchmark snapshot source filtering helpers."""

from __future__ import annotations

from typing import Any

from ui.backend.services.benchmark_payload_utils import json_clone as _json_clone


def _filter_benchmark_snapshot_rows(rows: list[dict[str, Any]], source_filter: Any) -> list[dict[str, Any]]:
    if not isinstance(source_filter, dict) or not source_filter:
        return rows
    return [row for row in rows if _benchmark_snapshot_row_matches_source_filter(row, source_filter)]


def _benchmark_snapshot_source_filter_summary(source_filter: Any) -> dict[str, Any]:
    if not isinstance(source_filter, dict):
        return {}
    return {
        key: _json_clone(value)
        for key, value in source_filter.items()
        if str(key or "").strip() and value not in (None, "", [], (), set())
    }


def _benchmark_snapshot_filter_values(value: Any) -> set[str] | None:
    if value in (None, "", [], (), set()):
        return None
    if isinstance(value, (list, tuple, set)):
        values = {str(item).strip().lower() for item in value if str(item or "").strip()}
        return values or None
    text = str(value or "").strip()
    if not text:
        return None
    return {part.strip().lower() for part in text.split(",") if part.strip()} or None


def _benchmark_snapshot_row_field(row: dict[str, Any], key: str) -> Any:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    aliases = {
        "source_run_id": ("source_run_id", "run_id", "batch_id"),
        "batch_id": ("batch_id", "source_run_id", "run_id"),
        "report_id": ("report_id", "source_report_id"),
        "source_report_id": ("source_report_id", "report_id"),
        "result_batch_id": ("result_batch_id",),
        "subject_id": ("subject_id", "hash", "model_config_hash", "model_id", "target_version_id"),
    }
    for candidate in aliases.get(key, (key,)):
        value = row.get(candidate)
        if value not in (None, ""):
            return value
        value = summary.get(candidate)
        if value not in (None, ""):
            return value
    return None


def _benchmark_snapshot_rankable_matches(row: dict[str, Any], allowed: set[str] | None) -> bool:
    if not allowed or allowed & {"all", "any", "*"}:
        return True
    is_rankable = row.get("rankable") is not False
    if allowed & {"rankable", "true", "1", "yes"}:
        return is_rankable
    if allowed & {"unrankable", "false", "0", "no"}:
        return not is_rankable
    return True


def _benchmark_snapshot_row_matches_source_filter(row: dict[str, Any], source_filter: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    for raw_key, raw_value in source_filter.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        allowed = _benchmark_snapshot_filter_values(raw_value)
        if allowed is None:
            continue
        if key == "rankable":
            if not _benchmark_snapshot_rankable_matches(row, allowed):
                return False
            continue
        value = _benchmark_snapshot_row_field(row, key)
        if str(value or "").strip().lower() not in allowed:
            return False
    return True
