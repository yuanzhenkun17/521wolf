"""Role and version routes for the UI backend."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from app.lib.version import promote_version
from ui.backend.constants import ROLE_ORDER
from ui.backend.serializers import (
    _fallback_version,
    _version_detail_payload,
    _version_summary_payload,
)


def register_role_routes(api: FastAPI, store: Any) -> None:
    @api.get("/api/roles")
    def list_roles() -> dict[str, Any]:
        roles = sorted(
            {*ROLE_ORDER, *store.registry.list_roles()},
            key=lambda role: ROLE_ORDER.index(role) if role in ROLE_ORDER else len(ROLE_ORDER),
        )
        return {"roles": roles}

    @api.get("/api/roles/{role}/versions")
    def list_versions(role: str) -> dict[str, Any]:
        versions = [_version_summary_payload(v.to_dict()) for v in store.registry.list_versions(role)]
        if not versions:
            versions = [_version_summary_payload(_fallback_version(role))]
        return {"role": role, "versions": versions}

    @api.get("/api/roles/{role}/versions/{version_id}")
    def get_version(role: str, version_id: str) -> dict[str, Any]:
        try:
            contents = store.registry.read_skill_contents(role, version_id)
            return _version_detail_payload(
                role=role,
                version_id=version_id,
                contents=contents,
                source="app-registry",
            )
        except (FileNotFoundError, ValueError):
            if version_id == _fallback_version(role)["version_id"]:
                return _version_detail_payload(
                    role=role,
                    version_id=version_id,
                    contents={},
                    source="app-fallback",
                    status="missing_registry",
                )
            raise HTTPException(status_code=404, detail="version not found")

    @api.get("/api/roles/{role}/leaderboard")
    def role_leaderboard(role: str) -> dict[str, Any]:
        versions = [v.to_dict() for v in store.registry.list_versions(role)] or [_fallback_version(role)]
        scores = store.leaderboard_scores_for_role(role)
        entries = []
        for version in versions:
            vid = version["version_id"]
            score = scores.get(vid, {})
            entries.append(
                {
                    "hash": vid,
                    "role": role,
                    "target_role": role,
                    "target_version_id": vid,
                    "target_role_role_weighted_score": float(score.get("avg_role_score", 0.0)),
                    "target_side_win_rate": float(score.get("target_side_win_rate", 0.0)),
                    "target_role_fallback_rate": float(score.get("fallback_rate", 0.0)),
                    "rankable": bool(score.get("rankable", False)),
                    "game_count": int(score.get("games_played", 0)),
                    "is_baseline": bool(version.get("is_baseline")),
                    "delta_vs_baseline": {},
                }
            )
        entries.sort(key=lambda e: (e["rankable"], e["target_role_role_weighted_score"]), reverse=True)
        return {"kind": "role_leaderboard", "schema_version": 1, "role": role, "source": "app", "entries": entries}

    @api.post("/api/roles/{role}/rollback/{version_id}")
    def rollback(role: str, version_id: str) -> dict[str, Any]:
        try:
            promote_version(store.registry, role, version_id)
        except (FileNotFoundError, RuntimeError, ValueError):
            if version_id != _fallback_version(role)["version_id"]:
                raise HTTPException(status_code=404, detail="version not found")
        return {"kind": "role_rollback", "schema_version": 1, "role": role, "new_baseline": version_id}
