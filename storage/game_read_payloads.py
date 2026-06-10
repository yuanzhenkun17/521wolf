"""Payload normalization helpers for the PostgreSQL game read model."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from storage.shared.database import StorageRow

EVOLUTION_RUN_TYPES = {
    "evolution_training",
    "evolution_battle",
    "evolution_ab_baseline",
    "evolution_ab_candidate",
}


def json_object(value: Any) -> dict[str, Any]:
    decoded = json_value(value)
    return decoded if isinstance(decoded, dict) else {}


def row_dict(row: StorageRow) -> dict[str, Any]:
    return {str(key): row[key] for key in row.keys()}


def json_array(value: Any) -> list[Any]:
    decoded = json_value(value)
    return decoded if isinstance(decoded, list) else []


def json_object_list(value: Any) -> list[dict[str, Any]]:
    return [item for item in json_array(value) if isinstance(item, dict)]


def normalize_bundle_rows(rows: list[dict[str, Any]], storage_timezone: str) -> list[dict[str, Any]]:
    return [normalize_bundle_row(row, storage_timezone) for row in rows]


def normalize_bundle_row(row: dict[str, Any], storage_timezone: str) -> dict[str, Any]:
    created_at = row.get("created_at")
    if created_at is None:
        return row
    normalized = datetime_text_in_storage_timezone(created_at, storage_timezone)
    if normalized == created_at:
        return row
    next_row = dict(row)
    next_row["created_at"] = normalized
    return next_row


def datetime_text_in_storage_timezone(value: Any, storage_timezone: str) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        return value
    return parsed.astimezone(ZoneInfo(storage_timezone)).isoformat()


def history_final_state(row: dict[str, Any]) -> dict[str, Any]:
    final_state = json_object(row.get("final_state"))
    if final_state:
        return final_state
    fields = {
        "status": row.get("final_status"),
        "stop_requested": row.get("final_stop_requested"),
        "cancelled": row.get("final_cancelled"),
        "interrupted": row.get("final_interrupted"),
        "failed": row.get("final_failed"),
        "cancelled_at": row.get("final_cancelled_at"),
        "interrupted_at": row.get("final_interrupted_at"),
        "last_heartbeat_at": row.get("final_last_heartbeat_at"),
        "started_at": row.get("final_started_at"),
        "finished_at": row.get("final_finished_at"),
        "source_phase": row.get("final_source_phase"),
        "error": row.get("final_error"),
        "diagnostics": row.get("final_diagnostics"),
    }
    return {key: value for key, value in fields.items() if value is not None}


def json_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict | list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def first_value(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def first_text(*values: Any) -> str | None:
    value = first_value(*values)
    if value is None:
        return None
    text = str(value)
    return text if text else None


def bool_value(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    return default


def int_or_none(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def source_label(source: str) -> str:
    return {"normal": "人机/玩家", "benchmark": "评测", "evolution": "进化"}.get(source, source)


def source_phase_label(phase: str | None) -> str | None:
    if not phase:
        return None
    return {"training": "训练", "battle": "对战", "baseline": "基线", "candidate": "候选"}.get(phase, phase)


def clean_role_versions(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(role): str(version)
        for role, version in value.items()
        if role is not None and version is not None and str(version) != ""
    }


def evidence_source_context(
    game: dict[str, Any],
    config: dict[str, Any],
    final_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    final_state = final_state or {}
    source = first_text(game.get("log_source"), config.get("log_source"))
    if not source:
        run_type = str(game.get("run_type") or "").lower()
        if run_type in EVOLUTION_RUN_TYPES or run_type.startswith("evolution_"):
            source = "evolution"
        elif run_type in {"evaluation_batch", "benchmark", "benchmark_game"}:
            source = "benchmark"
        else:
            source = "normal"
    source_phase = first_text(game.get("source_phase"), config.get("source_phase"), final_state.get("source_phase"))
    role_versions = clean_role_versions(
        first_value(
            game.get("role_versions"),
            config.get("role_versions"),
            game.get("role_skill_dirs"),
            config.get("role_skill_dirs"),
        )
    )
    return {
        "log_source": source,
        "log_source_label": source_label(source),
        "source_run_id": first_text(game.get("source_run_id"), config.get("source_run_id")),
        "source_phase": source_phase,
        "source_phase_label": source_phase_label(source_phase),
        "seed": first_value(game.get("seed"), config.get("seed")),
        "role_versions": role_versions,
    }


def default_manifest(game_id: str, status: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_type": "game",
        "game_id": game_id,
        "status": status,
    }
