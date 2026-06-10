"""Role and version routes for the UI backend."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from ui.backend.services import RoleService



def register_role_routes(api: FastAPI, store: Any) -> None:
    service = RoleService(store)

    @api.get("/api/roles")
    def list_roles() -> dict[str, Any]:
        return {"roles": service.available_roles()}

    @api.get("/api/roles/overview")
    def roles_overview(evaluation_set_id: str | None = None) -> dict[str, Any]:
        return service.overview_payload(evaluation_set_id=evaluation_set_id)

    @api.get("/api/roles/{role}/versions")
    def list_versions(role: str) -> dict[str, Any]:
        return {"role": role, "versions": service.role_versions(role)}

    @api.get("/api/roles/{role}/versions/{version_id}")
    def get_version(role: str, version_id: str) -> dict[str, Any]:
        return service.version_detail(role, version_id)

    @api.get("/api/roles/{role}/leaderboard")
    def role_leaderboard(role: str, evaluation_set_id: str | None = None) -> dict[str, Any]:
        return service.leaderboard(role, evaluation_set_id=evaluation_set_id)

    @api.post("/api/roles/{role}/rollback/{version_id}")
    def rollback(role: str, version_id: str) -> dict[str, Any]:
        return service.rollback(role, version_id)
