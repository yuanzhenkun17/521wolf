"""Role and version routes for the UI backend."""

from __future__ import annotations

import math
from collections.abc import Mapping
from time import monotonic
from typing import Any

from fastapi import FastAPI, HTTPException

from app.lib.version import ReleaseStageNotAllowedError, ensure_version_allowed_for_default_use, is_experimental_release_stage, promote_version
from ui.backend.constants import ROLE_ORDER
from ui.backend.errors import domain_error_detail
from ui.backend.serializers import (
    _fallback_version,
    _version_detail_payload,
    _version_summary_payload,
)

_ROLE_OVERVIEW_CACHE_TTL_SECONDS = 10.0
_ROLE_CONFIDENCE_LEVEL = 0.95
_ROLE_Z_95 = 1.96
_ROLE_MIN_CONFIDENT_SAMPLE_SIZE = 30
_VERSION_DETAIL_SUMMARY_KEYS = (
    "version_id",
    "role",
    "source",
    "created_at",
    "is_baseline",
    "status",
    "release_stage",
    "provenance",
    "metrics",
    "trust_bundle_id",
    "gate_report_id",
    "attribution_report_id",
    "source_run_id",
    "bundle_hash",
)


def _role_order_key(role: str) -> int:
    return ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER)


def _available_roles(store: Any) -> list[str]:
    return sorted({*ROLE_ORDER, *store.registry.list_roles()}, key=_role_order_key)


def _role_versions(store: Any, role: str) -> list[dict[str, Any]]:
    versions = [_version_summary_payload(v.to_dict()) for v in store.registry.list_versions(role)]
    if not versions:
        versions = [_version_summary_payload(_fallback_version(role))]
    return versions


def _summary_dict(version: Any) -> dict[str, Any]:
    if hasattr(version, "to_dict"):
        try:
            data = version.to_dict()
        except Exception:
            data = {}
        result = dict(data) if isinstance(data, Mapping) else {}
    elif isinstance(version, Mapping):
        result = dict(version)
    else:
        result = {}
    for key in _VERSION_DETAIL_SUMMARY_KEYS:
        if key not in result and hasattr(version, key):
            result[key] = getattr(version, key)
    return result


def _version_summary_for_detail(store: Any, role: str, version_id: str) -> dict[str, Any] | None:
    list_versions = getattr(store.registry, "list_versions", None)
    if not callable(list_versions):
        return None
    try:
        versions = list_versions(role)
    except Exception:
        return None
    for version in versions:
        summary = _summary_dict(version)
        if str(summary.get("version_id") or "") == version_id:
            return _version_summary_payload(summary)
    return None


def _version_release_stage(version: dict[str, Any]) -> str:
    provenance = version.get("provenance") if isinstance(version.get("provenance"), dict) else {}
    return str(version.get("release_stage") or provenance.get("release_stage") or "").strip().lower()


def _role_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            return number
    return default


def _role_int(*values: Any, default: int = 0) -> int:
    for value in values:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            continue
    return default


def _role_probability(value: Any) -> float:
    number = _role_float(value)
    if abs(number) > 1 and abs(number) <= 100:
        number = number / 100.0
    return max(0.0, min(1.0, number))


def _role_wilson_interval(win_rate: float, sample_size: int) -> dict[str, float]:
    if sample_size <= 0:
        return {"low": 0.0, "high": 0.0, "level": _ROLE_CONFIDENCE_LEVEL}
    probability = _role_probability(win_rate)
    z_squared = _ROLE_Z_95 ** 2
    denominator = 1.0 + (z_squared / sample_size)
    center = (probability + (z_squared / (2 * sample_size))) / denominator
    half_width = (
        _ROLE_Z_95
        * math.sqrt((probability * (1.0 - probability) / sample_size) + (z_squared / (4 * sample_size ** 2)))
        / denominator
    )
    return {
        "low": max(0.0, min(1.0, center - half_width)),
        "high": max(0.0, min(1.0, center + half_width)),
        "level": _ROLE_CONFIDENCE_LEVEL,
    }


def _role_warning_codes(*values: Any) -> list[str]:
    allowed = {"low_sample", "unpaired_seeds", "insufficient_overlap"}
    result: list[str] = []
    for value in values:
        candidates: list[Any]
        if isinstance(value, list):
            candidates = value
        elif isinstance(value, dict):
            candidates = [key for key, enabled in value.items() if enabled]
        elif value:
            candidates = [value]
        else:
            candidates = []
        for item in candidates:
            code = str(item or "").strip()
            if code in allowed and code not in result:
                result.append(code)
    return result


def _role_statistics_payload(score: dict[str, Any], *, game_count: int, win_rate: float) -> dict[str, Any]:
    summary = score.get("summary") if isinstance(score.get("summary"), Mapping) else {}
    sample_size = _role_int(
        score.get("sample_size"),
        summary.get("sample_size"),
        score.get("completed_games"),
        summary.get("completed_games"),
        summary.get("win_rate_denominator"),
        game_count,
    )
    interval = score.get("win_rate_ci") if isinstance(score.get("win_rate_ci"), Mapping) else None
    if interval is None:
        interval = _role_wilson_interval(win_rate, sample_size)
    ci_low = _role_float(score.get("ci_low"), interval.get("low"), default=0.0)
    ci_high = _role_float(score.get("ci_high"), interval.get("high"), default=0.0)
    standard_error = _role_float(score.get("standard_error"), default=0.0)
    if "standard_error" not in score and sample_size > 0:
        probability = _role_probability(win_rate)
        standard_error = math.sqrt((probability * (1.0 - probability)) / sample_size)
    warnings = _role_warning_codes(score.get("warnings"), summary.get("warnings"))
    if sample_size < _ROLE_MIN_CONFIDENT_SAMPLE_SIZE and "low_sample" not in warnings:
        warnings.append("low_sample")
    return {
        "sample_size": sample_size,
        "paired_sample_size": _role_int(score.get("paired_sample_size"), summary.get("paired_sample_size")),
        "win_rate_ci": {
            "low": ci_low,
            "high": ci_high,
            "level": _role_float(interval.get("level"), default=_ROLE_CONFIDENCE_LEVEL),
        },
        "ci_low": ci_low,
        "ci_high": ci_high,
        "standard_error": standard_error,
        "paired_delta": score.get("paired_delta", summary.get("paired_delta")),
        "significant": bool(score.get("significant", False)),
        "significance_label": str(score.get("significance_label") or "待比较"),
        "warnings": warnings,
    }


def _role_leaderboard_payload(
    role: str,
    versions: list[dict[str, Any]],
    scores: dict[str, dict[str, Any]],
    *,
    evaluation_set_id: str | None = None,
) -> dict[str, Any]:
    entries = []
    for version in versions:
        release_stage = _version_release_stage(version)
        if is_experimental_release_stage(release_stage):
            continue
        vid = version["version_id"]
        score = scores.get(vid, {})
        game_count = int(score.get("games_played", 0))
        win_rate = float(score.get("target_side_win_rate", 0.0))
        entry = {
            "hash": vid,
            "role": role,
            "target_role": role,
            "target_version_id": vid,
            "target_role_role_weighted_score": float(score.get("avg_role_score", 0.0)),
            "target_side_win_rate": win_rate,
            "target_role_fallback_rate": float(score.get("fallback_rate", 0.0)),
            "rankable": bool(score.get("rankable", False)),
            "game_count": game_count,
            "is_baseline": bool(version.get("is_baseline")),
            "release_stage": release_stage or version.get("release_stage"),
            "delta_vs_baseline": {},
        }
        entry.update(_role_statistics_payload(score, game_count=game_count, win_rate=win_rate))
        entries.append(entry)
    entries.sort(key=lambda e: (e["rankable"], e["target_role_role_weighted_score"]), reverse=True)
    return {
        "kind": "role_leaderboard",
        "schema_version": 1,
        "role": role,
        "evaluation_set_id": evaluation_set_id,
        "source": "app",
        "entries": entries,
    }


def clear_role_overview_cache(store: Any) -> None:
    invalidate = getattr(store, "invalidate_role_overview_cache", None)
    if callable(invalidate):
        invalidate()
        return
    setattr(store, "_role_overview_cache", {})


def _cached_role_overview(store: Any, evaluation_set_id: str | None) -> dict[str, Any] | None:
    cache = getattr(store, "_role_overview_cache", None)
    if not isinstance(cache, dict):
        return None
    entry = cache.get(evaluation_set_id or "")
    if not isinstance(entry, dict):
        return None
    cached_at = float(entry.get("cached_at") or 0.0)
    if monotonic() - cached_at >= _ROLE_OVERVIEW_CACHE_TTL_SECONDS:
        cache.pop(evaluation_set_id or "", None)
        return None
    payload = entry.get("payload")
    return payload if isinstance(payload, dict) else None


def _store_role_overview(store: Any, evaluation_set_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    cache = getattr(store, "_role_overview_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(store, "_role_overview_cache", cache)
    cache[evaluation_set_id or ""] = {"cached_at": monotonic(), "payload": payload}
    return payload


def role_overview_payload(store: Any, evaluation_set_id: str | None = None) -> dict[str, Any]:
    cached = _cached_role_overview(store, evaluation_set_id)
    if cached is not None:
        return cached
    roles = _available_roles(store)
    versions_by_role = {role: _role_versions(store, role) for role in roles}
    bulk_scores = store.leaderboard_scores_for_roles(roles, evaluation_set_id=evaluation_set_id)
    leaderboards = {
        role: _role_leaderboard_payload(
            role,
            versions_by_role[role],
            bulk_scores.get(role, {}),
            evaluation_set_id=evaluation_set_id,
        )
        for role in roles
    }
    return _store_role_overview(
        store,
        evaluation_set_id,
        {
            "kind": "role_overview",
            "schema_version": 1,
            "roles": roles,
            "versions": versions_by_role,
            "leaderboards": leaderboards,
            "evaluation_set_id": evaluation_set_id,
        },
    )


def register_role_routes(api: FastAPI, store: Any) -> None:
    @api.get("/api/roles")
    def list_roles() -> dict[str, Any]:
        return {"roles": _available_roles(store)}

    @api.get("/api/roles/overview")
    def roles_overview(evaluation_set_id: str | None = None) -> dict[str, Any]:
        return role_overview_payload(store, evaluation_set_id=evaluation_set_id)

    @api.get("/api/roles/{role}/versions")
    def list_versions(role: str) -> dict[str, Any]:
        return {"role": role, "versions": _role_versions(store, role)}

    @api.get("/api/roles/{role}/versions/{version_id}")
    def get_version(role: str, version_id: str) -> dict[str, Any]:
        try:
            contents = store.registry.read_skill_contents(role, version_id)
            summary = _version_summary_for_detail(store, role, version_id)
            return _version_detail_payload(
                role=role,
                version_id=version_id,
                contents=contents,
                source="app-registry",
                summary=summary,
            )
        except (FileNotFoundError, ValueError):
            fallback = _fallback_version(role)
            if version_id == fallback["version_id"]:
                return _version_detail_payload(
                    role=role,
                    version_id=version_id,
                    contents={},
                    source="app-fallback",
                    status="missing_registry",
                    summary=_version_summary_payload(fallback),
                )
            raise HTTPException(status_code=404, detail="version not found")

    @api.get("/api/roles/{role}/leaderboard")
    def role_leaderboard(role: str, evaluation_set_id: str | None = None) -> dict[str, Any]:
        versions = _role_versions(store, role)
        scores = store.leaderboard_scores_for_role(role, evaluation_set_id=evaluation_set_id)
        return _role_leaderboard_payload(role, versions, scores, evaluation_set_id=evaluation_set_id)

    @api.post("/api/roles/{role}/rollback/{version_id}")
    def rollback(role: str, version_id: str) -> dict[str, Any]:
        try:
            ensure_version_allowed_for_default_use(store.registry, role, version_id)
            promote_version(store.registry, role, version_id)
        except ReleaseStageNotAllowedError as exc:
            raise HTTPException(
                status_code=409,
                detail=domain_error_detail(
                    code="role_version_release_stage_not_allowed",
                    message="Role version is not allowed for rollback.",
                    detail=f"version not allowed: {exc}",
                    diagnostics=[exc.diagnostic(kind="role_rollback_version_not_allowed")],
                ),
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=f"version not allowed: {exc}") from exc
        except (FileNotFoundError, RuntimeError):
            if version_id != _fallback_version(role)["version_id"]:
                raise HTTPException(status_code=404, detail="version not found")
        clear_role_overview_cache(store)
        return {"kind": "role_rollback", "schema_version": 1, "role": role, "new_baseline": version_id}
