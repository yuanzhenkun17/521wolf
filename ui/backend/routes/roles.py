"""Role and version routes for the UI backend."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, HTTPException

from app.lib.version import ReleaseStageNotAllowedError, ensure_version_allowed_for_default_use, promote_version
from ui.backend.errors import domain_error_detail, release_stage_not_allowed_detail
from ui.backend.serializers import (
    _fallback_version,
    _version_detail_payload,
    _version_summary_payload,
)
from ui.backend.services import RoleService

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
    return RoleService.role_order_key(role)


def _available_roles(store: Any) -> list[str]:
    return RoleService(store).available_roles()


def _role_versions(store: Any, role: str) -> list[dict[str, Any]]:
    return RoleService(store).role_versions(role)


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
    return RoleService.version_release_stage(version)


def _role_float(*values: Any, default: float = 0.0) -> float:
    return RoleService.role_float(*values, default=default)


def _role_int(*values: Any, default: int = 0) -> int:
    return RoleService.role_int(*values, default=default)


def _role_probability(value: Any) -> float:
    return RoleService.role_probability(value)


def _role_wilson_interval(win_rate: float, sample_size: int) -> dict[str, float]:
    return RoleService.role_wilson_interval(win_rate, sample_size)


def _role_warning_codes(*values: Any) -> list[str]:
    return RoleService.role_warning_codes(*values)


def _role_statistics_payload(score: dict[str, Any], *, game_count: int, win_rate: float) -> dict[str, Any]:
    return RoleService.role_statistics_payload(score, game_count=game_count, win_rate=win_rate)


def _role_leaderboard_payload(
    role: str,
    versions: list[dict[str, Any]],
    scores: dict[str, dict[str, Any]],
    *,
    evaluation_set_id: str | None = None,
) -> dict[str, Any]:
    return RoleService.leaderboard_payload(role, versions, scores, evaluation_set_id=evaluation_set_id)


def clear_role_overview_cache(store: Any) -> None:
    RoleService(store).clear_overview_cache()


def _cached_role_overview(store: Any, evaluation_set_id: str | None) -> dict[str, Any] | None:
    return RoleService(store).cached_overview(evaluation_set_id)


def _store_role_overview(store: Any, evaluation_set_id: str | None, payload: dict[str, Any]) -> dict[str, Any]:
    return RoleService(store).store_overview(evaluation_set_id, payload)


def role_overview_payload(store: Any, evaluation_set_id: str | None = None) -> dict[str, Any]:
    return RoleService(store).overview_payload(evaluation_set_id=evaluation_set_id)


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
            release_stage_detail = release_stage_not_allowed_detail(
                exc,
                code="role_version_release_stage_not_allowed",
                message="Role version is not allowed for rollback.",
                detail_prefix="version not allowed",
                kind="role_rollback_version_not_allowed",
            )
            if release_stage_detail is not None:
                raise HTTPException(status_code=409, detail=release_stage_detail) from exc
            raise HTTPException(status_code=409, detail=f"version not allowed: {exc}") from exc
        except (FileNotFoundError, RuntimeError):
            if version_id != _fallback_version(role)["version_id"]:
                raise HTTPException(status_code=404, detail="version not found")
        clear_role_overview_cache(store)
        return {"kind": "role_rollback", "schema_version": 1, "role": role, "new_baseline": version_id}
