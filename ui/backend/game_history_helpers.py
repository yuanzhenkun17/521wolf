"""Shared helpers for UI game history payloads."""

from __future__ import annotations

from typing import Any

from ui.backend.constants import LOG_SOURCE_LABELS


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _clean_role_versions(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(role): str(version)
        for role, version in value.items()
        if role is not None and version is not None and str(version) != ""
    }


def _source_phase_label(phase: Any) -> str | None:
    if not phase:
        return None
    text = str(phase)
    return {
        "training": "训练",
        "battle": "对战",
        "baseline": "基线",
        "candidate": "候选",
    }.get(text, text)


def _evidence_source_context(game: dict[str, Any], *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    config = config if isinstance(config, dict) else (game.get("config") if isinstance(game.get("config"), dict) else {})
    source = str(_first_present(game.get("log_source"), config.get("log_source"), "normal"))
    source_phase = _first_present(game.get("source_phase"), config.get("source_phase"))
    role_versions = _clean_role_versions(
        _first_present(
            game.get("role_versions"),
            config.get("role_versions"),
            game.get("role_skill_dirs"),
            config.get("role_skill_dirs"),
        )
    )
    return {
        "log_source": source,
        "log_source_label": _first_present(
            game.get("log_source_label"),
            config.get("log_source_label"),
            LOG_SOURCE_LABELS.get(source),
            "人机/玩家",
        ),
        "source_run_id": _first_present(game.get("source_run_id"), config.get("source_run_id")),
        "source_phase": source_phase,
        "source_phase_label": _first_present(
            game.get("source_phase_label"),
            config.get("source_phase_label"),
            _source_phase_label(source_phase),
        ),
        "seed": _first_present(game.get("seed"), config.get("seed")),
        "role_versions": role_versions,
    }


def _with_evidence_source_context(payload: dict[str, Any], source: dict[str, Any] | None = None) -> dict[str, Any]:
    context = _evidence_source_context(source or payload)
    payload["evidence_source"] = context
    for key in ("log_source", "log_source_label", "source_run_id", "source_phase", "source_phase_label", "seed"):
        if payload.get(key) is None or payload.get(key) == "":
            payload[key] = context[key]
    if not isinstance(payload.get("role_versions"), dict) or not payload.get("role_versions"):
        payload["role_versions"] = dict(context["role_versions"])
    return payload


def _paginate_history_rows(
    rows: list[dict[str, Any]],
    *,
    offset: int,
    limit: int | None,
    default_limit: int,
    max_limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    total = len(rows)
    try:
        safe_offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        safe_offset = 0
    try:
        safe_limit = int(limit) if limit is not None else default_limit
    except (TypeError, ValueError):
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


__all__ = [
    "_clean_role_versions",
    "_evidence_source_context",
    "_first_present",
    "_paginate_history_rows",
    "_source_phase_label",
    "_with_evidence_source_context",
]
