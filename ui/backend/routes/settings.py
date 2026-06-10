"""Settings routes for local model profiles and runtime status."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException

from ui.backend.health import build_health_payload
from ui.backend.schemas import ModelProfileCreateRequest, ModelProfileUpdateRequest
from ui.backend.settings_model_profiles import SettingsModelProfileStore, settings_admin_authorized, settings_admin_payload


def register_settings_routes(api: FastAPI, store: Any) -> None:
    profile_store = SettingsModelProfileStore.from_backend_store(store)

    @api.get("/api/settings/model-profiles")
    def list_model_profiles() -> dict[str, Any]:
        return {
            **profile_store.list_payload(),
            "health": build_health_payload(store),
        }

    @api.post("/api/settings/model-profiles")
    def create_model_profile(
        request: ModelProfileCreateRequest,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            return {
                "kind": "settings_model_profile",
                "schema_version": 1,
                "profile": profile_store.create_profile(request),
            }
        except ValueError as exc:
            raise _settings_error(422, "settings_model_profile_invalid", str(exc)) from exc

    @api.patch("/api/settings/model-profiles/{profile_id}")
    def update_model_profile(
        profile_id: str,
        request: ModelProfileUpdateRequest,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            return {
                "kind": "settings_model_profile",
                "schema_version": 1,
                "profile": profile_store.update_profile(profile_id, request),
            }
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_model_profile_not_found", "model profile not found") from exc
        except ValueError as exc:
            raise _settings_error(422, "settings_model_profile_invalid", str(exc)) from exc

    @api.post("/api/settings/model-profiles/{profile_id}/test")
    async def test_model_profile(
        profile_id: str,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            return await profile_store.test_profile(profile_id)
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_model_profile_not_found", "model profile not found") from exc
        except ValueError as exc:
            raise _settings_error(422, "settings_model_profile_invalid", str(exc)) from exc

    @api.post("/api/settings/model-profiles/{profile_id}/disable")
    def disable_model_profile(
        profile_id: str,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            return {
                "kind": "settings_model_profile",
                "schema_version": 1,
                "profile": profile_store.disable_profile(profile_id),
            }
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_model_profile_not_found", "model profile not found") from exc

    @api.delete("/api/settings/model-profiles/{profile_id}")
    def delete_model_profile(
        profile_id: str,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            return profile_store.delete_profile(profile_id)
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_model_profile_not_found", "model profile not found") from exc


def _require_settings_admin(token: str | None) -> None:
    if settings_admin_authorized(token):
        return
    admin = settings_admin_payload()
    if not admin["write_available"]:
        raise _settings_error(
            403,
            "settings_admin_disabled",
            "settings admin writes are disabled",
            detail="settings admin is disabled or token is not configured",
        )
    raise _settings_error(
        403,
        "settings_admin_required",
        "settings admin token is required",
        detail="missing or invalid settings admin token",
    )


def _settings_error(status_code: int, code: str, message: str, *, detail: str | None = None) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "detail": detail or message,
        },
    )
