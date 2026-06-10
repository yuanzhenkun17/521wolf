"""Payload normalization helpers for the PostgreSQL game read model."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from storage.game_history_rules import row_history_phase
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


def paginate_rows(
    rows: list[dict[str, Any]],
    *,
    offset: int,
    limit: int | None,
    default_limit: int,
    max_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(rows)
    safe_offset = max(0, int_or_none(offset) or 0)
    safe_limit = int_or_none(limit)
    if safe_limit is None:
        safe_limit = default_limit
    safe_limit = max(1, min(safe_limit, max_limit))
    page = rows[safe_offset:safe_offset + safe_limit]
    return page, {
        "total": total,
        "offset": safe_offset,
        "limit": safe_limit,
        "returned": len(page),
        "has_more": safe_offset + len(page) < total,
    }


def event_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = json_object(row.get("payload"))
    return {
        "index": int_or_none(row.get("idx")) or 0,
        "idx": int_or_none(row.get("idx")) or 0,
        "day": int_or_none(row.get("day")) or 0,
        "phase": first_text(row.get("phase"), ""),
        "type": first_text(row.get("event_type"), ""),
        "event_type": first_text(row.get("event_type"), ""),
        "message": first_text(row.get("message"), ""),
        "public": bool_value(row.get("public"), True),
        "actor": int_or_none(row.get("actor")),
        "target": int_or_none(row.get("target")),
        "payload": payload,
        "created_at": first_text(row.get("created_at")),
    }


def decision_row(row: dict[str, Any]) -> dict[str, Any]:
    seat = int_or_none(first_value(row.get("player_id"), row.get("seat")))
    target = int_or_none(row.get("selected_target"))
    parsed = json_object(row.get("parsed_decision"))
    final_response = json_object(row.get("final_response"))
    public_text = first_text(row.get("public_text"), final_response.get("text"), parsed.get("public_text"), "")
    return {
        **row,
        "id": str(row.get("id") or ""),
        "decision_id": str(row.get("decision_id") or row.get("id") or ""),
        "player_id": seat,
        "actor_id": seat,
        "target_id": target,
        "selected_target": target,
        "action": first_text(row.get("action_type"), ""),
        "action_type": first_text(row.get("action_type"), ""),
        "day": int_or_none(row.get("day")) or 0,
        "phase": first_text(row.get("phase"), ""),
        "role": first_text(row.get("role"), ""),
        "public_text": public_text,
        "private_reasoning": first_text(row.get("private_reasoning"), ""),
        "confidence": float_or_none(row.get("confidence")),
        "candidates": json_array(row.get("candidates")),
        "selected_skills": json_array(row.get("selected_skills")),
        "alternatives": json_array(row.get("alternatives")),
        "rejected_reasons": json_array(row.get("rejected_reasons")),
        "policy_adjustments": json_array(row.get("policy_adjustments")),
        "errors": json_array(row.get("errors")),
        "parsed_decision": parsed,
        "final_response": final_response,
    }


def player_row(row: dict[str, Any]) -> dict[str, Any]:
    seat = int_or_none(row.get("seat"))
    return {
        "id": seat,
        "seat": seat,
        "name": f"{seat}号" if seat is not None else "",
        "role": first_text(row.get("role"), ""),
        "team": first_text(row.get("team"), ""),
        "alive": bool_value(row.get("alive"), True),
        "killed_day": int_or_none(row.get("killed_day")),
        "killed_cause": first_text(row.get("killed_cause")),
        "role_version_id": first_text(row.get("role_version_id")),
        "skill_package_hash": first_text(row.get("skill_package_hash")),
    }


def flow_decision_row(decision: dict[str, Any]) -> dict[str, Any]:
    public_summary = first_text(decision.get("public_summary"), decision.get("public_text"), decision.get("text"), "")
    return {
        "id": decision.get("id"),
        "decision_id": decision.get("decision_id"),
        "game_id": decision.get("game_id"),
        "actor_id": decision.get("actor_id"),
        "player_id": decision.get("player_id"),
        "target_id": decision.get("target_id"),
        "selected_target": decision.get("selected_target"),
        "selected_choice": decision.get("selected_choice"),
        "day": decision.get("day"),
        "phase": row_history_phase(decision),
        "action": decision.get("action"),
        "action_type": decision.get("action_type"),
        "role": decision.get("role"),
        "public_summary": public_summary,
        "public_text": decision.get("public_text") or public_summary,
        "private_reasoning": decision.get("private_reasoning") or "",
        "confidence": decision.get("confidence"),
        "candidates": decision.get("candidates") if isinstance(decision.get("candidates"), list) else [],
        "source": decision.get("source"),
        "policy_adjustments": decision.get("policy_adjustments") if isinstance(decision.get("policy_adjustments"), list) else [],
        "errors": decision.get("errors") if isinstance(decision.get("errors"), list) else [],
        "created_at": decision.get("created_at"),
    }


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
