"""Settings routes for local model profiles and runtime status."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Header, HTTPException

from ui.backend.health import build_health_payload
from ui.backend.ops_metrics import build_ops_metrics_payload
from ui.backend.schemas import ModelProfileCreateRequest, ModelProfileUpdateRequest, SettingsRuntimeVariableUpdateRequest
from ui.backend.settings_audit import SettingsAuditStore, settings_audit_details_for_profile
from ui.backend.settings_runtime_variables import SettingsRuntimeVariableStore
from ui.backend.settings_model_profiles import SettingsModelProfileStore, settings_admin_authorized, settings_admin_payload
from ui.backend.settings_secret_crypto import SettingsSecretEncryptionError
from ui.backend.settings_storage import SettingsStorageUnavailable


def register_settings_routes(api: FastAPI, store: Any) -> None:
    profile_store = SettingsModelProfileStore.from_backend_store(store)
    runtime_store = SettingsRuntimeVariableStore.from_backend_store(store)
    audit_store = SettingsAuditStore.from_backend_store(store)

    @api.get("/api/settings/model-profiles")
    def list_model_profiles(compact: bool = False) -> dict[str, Any]:
        payload = profile_store.list_payload(include_variables=False)
        if compact:
            return payload
        storage = dict(payload.get("storage") or {})
        storage["runtime_variables"] = runtime_store.storage_status()
        payload["storage"] = storage
        payload["admin"] = settings_admin_payload(storage=storage)
        payload["variables"] = runtime_store.list_variables()
        health = build_health_payload(store)
        return {
            **payload,
            "health": health,
            "ops_metrics": build_ops_metrics_payload(store, health=health),
        }

    @api.get("/api/settings/runtime-variables")
    def list_runtime_variables() -> dict[str, Any]:
        return runtime_store.list_payload()

    @api.get("/api/settings/audit-log")
    def list_settings_audit_log(limit: int = 50) -> dict[str, Any]:
        return audit_store.list_payload(limit=limit)

    @api.patch("/api/settings/runtime-variables/{setting_key}")
    def update_runtime_variable(
        setting_key: str,
        request: SettingsRuntimeVariableUpdateRequest,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            variable = runtime_store.update_variable(setting_key, request.value)
            audit_store.record_best_effort(
                action="runtime_variable.updated",
                entity_kind="runtime_variable",
                entity_id=variable["key"],
                message="Runtime variable updated from Settings.",
                details={
                    "key": variable["key"],
                    "label": variable.get("label"),
                    "state": variable.get("state"),
                    "source": variable.get("source"),
                    "value_type": variable.get("value_type"),
                },
            )
            return {
                "kind": "settings_runtime_variable",
                "schema_version": 1,
                "variable": variable,
            }
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_runtime_variable_not_found", "runtime variable not found") from exc
        except PermissionError as exc:
            raise _settings_error(409, "settings_runtime_variable_locked", str(exc)) from exc
        except SettingsStorageUnavailable as exc:
            raise _settings_storage_error(exc) from exc
        except ValueError as exc:
            raise _settings_error(422, "settings_runtime_variable_invalid", str(exc)) from exc

    @api.post("/api/settings/model-profiles")
    def create_model_profile(
        request: ModelProfileCreateRequest,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            profile = profile_store.create_profile(request)
            audit_store.record_best_effort(
                action="model_profile.created",
                entity_kind="model_profile",
                entity_id=profile["profile_id"],
                message="Model profile created from Settings.",
                details=settings_audit_details_for_profile(
                    profile,
                    fields=sorted(request.model_fields_set),
                ),
            )
            return {
                "kind": "settings_model_profile",
                "schema_version": 1,
                "profile": profile,
            }
        except (SettingsStorageUnavailable, SettingsSecretEncryptionError) as exc:
            raise _settings_storage_error(exc) from exc
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
            profile = profile_store.update_profile(profile_id, request)
            audit_store.record_best_effort(
                action="model_profile.updated",
                entity_kind="model_profile",
                entity_id=profile["profile_id"],
                message="Model profile updated from Settings.",
                details=settings_audit_details_for_profile(
                    profile,
                    fields=sorted(request.model_fields_set),
                ),
            )
            return {
                "kind": "settings_model_profile",
                "schema_version": 1,
                "profile": profile,
            }
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_model_profile_not_found", "model profile not found") from exc
        except (SettingsStorageUnavailable, SettingsSecretEncryptionError) as exc:
            raise _settings_storage_error(exc) from exc
        except ValueError as exc:
            raise _settings_error(422, "settings_model_profile_invalid", str(exc)) from exc

    @api.post("/api/settings/model-profiles/{profile_id}/test")
    async def test_model_profile(
        profile_id: str,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            result = await profile_store.test_profile(profile_id)
            audit_store.record_best_effort(
                action="model_profile.tested",
                entity_kind="model_profile",
                entity_id=profile_id,
                status=str(result.get("status") or "unknown"),
                message=str(result.get("message") or "Model profile connection tested."),
                details={
                    "profile_id": profile_id,
                    "model": result.get("model"),
                    "status": result.get("status"),
                    "latency_ms": result.get("latency_ms"),
                    "error_type": (result.get("error") or {}).get("type") if isinstance(result.get("error"), dict) else None,
                },
            )
            return result
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_model_profile_not_found", "model profile not found") from exc
        except (SettingsStorageUnavailable, SettingsSecretEncryptionError) as exc:
            raise _settings_storage_error(exc) from exc
        except ValueError as exc:
            raise _settings_error(422, "settings_model_profile_invalid", str(exc)) from exc

    @api.post("/api/settings/model-profiles/{profile_id}/disable")
    def disable_model_profile(
        profile_id: str,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            profile = profile_store.disable_profile(profile_id)
            audit_store.record_best_effort(
                action="model_profile.disabled",
                entity_kind="model_profile",
                entity_id=profile["profile_id"],
                message="Model profile disabled from Settings.",
                details=settings_audit_details_for_profile(profile, fields=["enabled"]),
            )
            return {
                "kind": "settings_model_profile",
                "schema_version": 1,
                "profile": profile,
            }
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_model_profile_not_found", "model profile not found") from exc
        except (SettingsStorageUnavailable, SettingsSecretEncryptionError) as exc:
            raise _settings_storage_error(exc) from exc

    @api.delete("/api/settings/model-profiles/{profile_id}")
    def delete_model_profile(
        profile_id: str,
        x_settings_admin_token: str | None = Header(default=None),
    ) -> dict[str, Any]:
        _require_settings_admin(x_settings_admin_token)
        try:
            result = profile_store.delete_profile(profile_id)
            audit_store.record_best_effort(
                action="model_profile.deleted",
                entity_kind="model_profile",
                entity_id=profile_id,
                message="Model profile deleted from Settings.",
                details={"profile_id": profile_id, "deleted": True},
            )
            return result
        except FileNotFoundError as exc:
            raise _settings_error(404, "settings_model_profile_not_found", "model profile not found") from exc
        except (SettingsStorageUnavailable, SettingsSecretEncryptionError) as exc:
            raise _settings_storage_error(exc) from exc


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


def _settings_storage_error(exc: SettingsStorageUnavailable | SettingsSecretEncryptionError) -> HTTPException:
    status = getattr(exc, "status", {}) if isinstance(exc, SettingsStorageUnavailable) else {}
    detail = str(status.get("message") or str(exc) or "settings storage is unavailable") if isinstance(status, dict) else str(exc)
    diagnostics = [status] if isinstance(status, dict) and status else []
    return HTTPException(
        status_code=503,
        detail={
            "code": "settings_storage_unavailable",
            "message": "settings storage is unavailable",
            "detail": detail,
            "diagnostics": diagnostics,
        },
    )
