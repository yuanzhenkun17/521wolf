"""Local settings store for user-managed model profiles."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

from app.services.llm import create_llm
from app.util.redaction import redact, redact_text
from app.util.time import beijing_now_iso
from storage.ui import ModelProfileRepository
from ui.backend.schemas import ModelProfileCreateRequest, ModelProfileUpdateRequest
from ui.backend.settings_runtime_variables import SettingsRuntimeVariableStore
from ui.backend.settings_secret_crypto import (
    SettingsSecretEncryptionError,
    decrypt_settings_secret,
    encrypt_settings_secret,
    ensure_settings_secret_encryption_configured,
)
from ui.backend.settings_storage import (
    assert_storage_write_available,
    local_file_storage_status,
    postgres_storage_status,
    storage_write_available,
)

MODEL_PROFILE_SCOPES = ("game_decision", "judge", "benchmark", "evolution", "prompt_test")
MODEL_PROFILE_CAPABILITIES = ("chat", "json_mode", "tool_calling", "streaming", "vision")
MODEL_PROFILE_PROVIDERS = {"openai_compatible", "dashscope", "deepseek", "ollama", "custom"}
MODEL_PROFILE_TEST_PROMPT = "Return the word ok."
LLM_ENV_LOCK_KEYS = ("WEREWOLF_LLM_API_KEY", "WEREWOLF_LLM_BASE_URL", "WEREWOLF_LLM_MODEL")


class SettingsModelProfileStore:
    def __init__(self, root: Path, *, connection_factory: Callable[[], Any] | None = None) -> None:
        self._root = Path(root)
        self._profile_path = self._root / "model-profiles.json"
        self._secret_path = self._root / "model-profile-secrets.json"
        self._connection_factory = connection_factory
        self._backend_status_cache: tuple[float, "_PostgresModelProfileBackend | None", dict[str, Any]] | None = None
        self._profile_list_cache: tuple[float, list[dict[str, Any]]] | None = None

    @classmethod
    def from_backend_store(cls, store: Any) -> "SettingsModelProfileStore":
        paths = getattr(store, "paths", None)
        data_dir = Path(getattr(paths, "data_dir", Path("data")))
        connection_factory = getattr(store, "_open_ui_task_connection", None)
        return cls(data_dir / "settings", connection_factory=connection_factory if callable(connection_factory) else None)

    def list_payload(self, *, include_variables: bool = True) -> dict[str, Any]:
        backend, storage_status = self._profile_backend_with_status()
        if backend is not None:
            profiles = self._cached_backend_profiles(backend)
            secrets = {}
        else:
            profiles = self._read_profiles()
            try:
                secrets = self._read_secrets()
            except SettingsSecretEncryptionError:
                secrets = {}
        public_profiles = [self._public_profile(profile, secrets=secrets) for profile in profiles]
        payload = {
            "kind": "settings_model_profiles",
            "schema_version": 1,
            "profiles": public_profiles,
            "env_locks": env_locks_payload(),
            "admin": settings_admin_payload(storage={"model_profiles": storage_status}),
            "storage": {"model_profiles": storage_status},
            "scopes": [
                {"key": scope, "label": scope_label(scope)}
                for scope in MODEL_PROFILE_SCOPES
            ],
            "providers": sorted(MODEL_PROFILE_PROVIDERS),
        }
        if include_variables:
            payload["variables"] = SettingsRuntimeVariableStore(
                self._root,
                connection_factory=self._connection_factory,
            ).list_variables()
        return payload

    def storage_status(self) -> dict[str, Any]:
        _backend, status = self._profile_backend_with_status()
        return status

    def model_runtime_payload(
        self,
        *,
        scope: str,
        profile_id: str | None = None,
    ) -> dict[str, Any] | None:
        resolved = self._resolve_runtime_profile(scope=scope, profile_id=profile_id)
        if resolved is None:
            return None
        profile, secret, default_scope_matched = resolved
        if not secret:
            if profile_id:
                raise ValueError("model profile has no saved API key")
            return None
        model_id = str(profile.get("model") or "").strip()
        runtime_hash = model_config_hash(profile)
        hash_input = model_profile_hash_input(profile)
        return {
            "model_id": model_id,
            "model_config_hash": runtime_hash,
            "model_runtime": {
                "schema_version": 1,
                "source": "settings_profile",
                "hash_source": "settings_profile",
                "hash_algorithm": "sha256",
                "hash_input_schema_version": 1,
                "model_id": model_id,
                "model_config_hash": runtime_hash,
                "model_profile_id": str(profile.get("profile_id") or ""),
                "provider": str(profile.get("provider") or ""),
                "base_url_host": base_url_host(profile.get("base_url")),
                "scope": normalize_scope(scope),
                "default_scope_matched": bool(default_scope_matched),
                "hash_provided": False,
                "externally_provided": False,
                "hash_input": hash_input,
            },
        }

    def create_llm_for_scope(
        self,
        *,
        scope: str,
        profile_id: str | None = None,
    ) -> Any | None:
        resolved = self._resolve_runtime_profile(scope=scope, profile_id=profile_id)
        if resolved is None:
            return None
        profile, secret, _default_scope_matched = resolved
        if not secret:
            if profile_id:
                raise ValueError("model profile has no saved API key")
            return None
        return create_llm(
            env_path=None,
            api_key=secret,
            base_url=normalize_base_url(profile.get("base_url")),
            model=str(profile.get("model") or ""),
            temperature=float(profile.get("temperature") if profile.get("temperature") is not None else 0.4),
            timeout=float(profile.get("timeout_seconds") or 60),
            runtime_timeout=float(profile.get("timeout_seconds") or 60),
            max_retries=int(profile.get("max_retries") or 0),
        )

    def create_profile(self, request: ModelProfileCreateRequest) -> dict[str, Any]:
        profiles = self._read_profiles()
        secrets = self._read_secrets()
        now = beijing_now_iso()
        profile_id = _new_profile_id(request.name)
        api_key = str(request.api_key or "").strip()
        self._ensure_secret_can_be_saved(api_key)
        secret_ref = f"model_profile:{profile_id}:api_key" if api_key else ""
        profile = {
            "profile_id": profile_id,
            "name": request.name,
            "provider": normalize_provider(request.provider),
            "base_url": normalize_base_url(request.base_url),
            "model": request.model,
            "api_key_secret_ref": secret_ref,
            "temperature": request.temperature,
            "timeout_seconds": request.timeout_seconds,
            "max_retries": request.max_retries,
            "enabled": bool(request.enabled),
            "default_scopes": normalize_bool_map(request.default_scopes, MODEL_PROFILE_SCOPES),
            "capabilities": normalize_bool_map(request.capabilities, MODEL_PROFILE_CAPABILITIES, default_true={"chat"}),
            "metadata": safe_profile_metadata(request.metadata),
            "created_at": now,
            "updated_at": now,
            "last_tested_at": None,
            "last_test_status": "untested",
            "last_test_error": "",
        }
        if api_key:
            secrets[secret_ref] = api_key
        profiles.append(profile)
        self._write_profiles(profiles)
        self._write_secrets(secrets)
        self._clear_profile_list_cache()
        return self._public_profile(profile, secrets=secrets)

    def update_profile(self, profile_id: str, request: ModelProfileUpdateRequest) -> dict[str, Any]:
        profiles = self._read_profiles()
        profile = self._find_profile(profiles, profile_id)
        fields = set(request.model_fields_set)
        backend = self._profile_backend()
        secrets: dict[str, str] | None = None
        secrets_changed = False
        changed_runtime = False

        def writable_secrets() -> dict[str, str]:
            nonlocal secrets
            if secrets is None:
                secrets = {} if backend is not None else self._read_secrets()
            return secrets

        for key in ("name", "provider", "base_url", "model", "temperature", "timeout_seconds", "max_retries", "enabled"):
            if key not in fields:
                continue
            value = getattr(request, key)
            if value is None:
                continue
            if key == "provider":
                value = normalize_provider(str(value))
            if key == "base_url":
                value = normalize_base_url(value)
            if key in {"base_url", "model", "temperature", "timeout_seconds", "max_retries"} and profile.get(key) != value:
                changed_runtime = True
            profile[key] = value

        if "default_scopes" in fields and request.default_scopes is not None:
            profile["default_scopes"] = normalize_bool_map(request.default_scopes, MODEL_PROFILE_SCOPES)
        if "capabilities" in fields and request.capabilities is not None:
            profile["capabilities"] = normalize_bool_map(
                request.capabilities,
                MODEL_PROFILE_CAPABILITIES,
                default_true={"chat"},
            )
        if "metadata" in fields and request.metadata is not None:
            profile["metadata"] = safe_profile_metadata(request.metadata)

        if request.clear_api_key:
            secret_ref = str(profile.get("api_key_secret_ref") or "")
            if secret_ref and backend is None:
                writable_secrets().pop(secret_ref, None)
                secrets_changed = True
            profile["api_key_secret_ref"] = ""
            profile["api_key_masked"] = ""
            changed_runtime = True
        elif "api_key" in fields:
            api_key = str(request.api_key or "").strip()
            if not api_key:
                raise ValueError("api_key cannot be empty; use clear_api_key=true to remove it")
            self._ensure_secret_can_be_saved(api_key)
            secret_ref = str(profile.get("api_key_secret_ref") or "") or f"model_profile:{profile_id}:api_key"
            profile["api_key_secret_ref"] = secret_ref
            writable_secrets()[secret_ref] = api_key
            secrets_changed = True
            changed_runtime = True

        if changed_runtime:
            profile["last_test_status"] = "stale"
            profile["last_test_error"] = ""
        profile["updated_at"] = beijing_now_iso()
        self._write_profiles(profiles)
        if secrets_changed and secrets is not None:
            self._write_secrets(secrets)
        self._clear_profile_list_cache()
        return self._public_profile(profile, secrets=secrets or {})

    async def test_profile(self, profile_id: str) -> dict[str, Any]:
        profiles = self._read_profiles()
        profile = self._find_profile(profiles, profile_id)
        secrets = self._read_secrets()
        secret = secrets.get(_profile_secret_ref(profile))
        if not secret:
            raise ValueError("model profile has no saved API key")

        started = time.perf_counter()
        checked_at = beijing_now_iso()
        try:
            llm = create_llm(
                env_path=None,
                api_key=secret,
                base_url=normalize_base_url(profile.get("base_url")),
                model=str(profile.get("model") or ""),
                temperature=float(profile.get("temperature") if profile.get("temperature") is not None else 0.4),
                timeout=float(profile.get("timeout_seconds") or 60),
                runtime_timeout=float(profile.get("timeout_seconds") or 60),
                max_retries=int(profile.get("max_retries") or 0),
            )
            await llm.ainvoke(MODEL_PROFILE_TEST_PROMPT)
            result = {
                "ok": True,
                "status": "ok",
                "checked_at": checked_at,
                "latency_ms": int(round((time.perf_counter() - started) * 1000)),
                "profile_id": profile_id,
                "model": profile.get("model"),
                "message": "连接正常",
            }
            profile["last_test_status"] = "ok"
            profile["last_test_error"] = ""
        except Exception as exc:  # noqa: BLE001 - converted to redacted settings diagnostics.
            result = {
                "ok": False,
                "status": "error",
                "checked_at": checked_at,
                "latency_ms": int(round((time.perf_counter() - started) * 1000)),
                "profile_id": profile_id,
                "model": profile.get("model"),
                "message": "连接失败",
                "error": {
                    "type": type(exc).__name__,
                    "message": redact_text(str(exc) or type(exc).__name__, context="diagnostic"),
                },
            }
            profile["last_test_status"] = "error"
            profile["last_test_error"] = result["error"]["message"]
        profile["last_tested_at"] = checked_at
        profile["updated_at"] = checked_at
        self._write_profiles(profiles)
        self._clear_profile_list_cache()
        return result

    def disable_profile(self, profile_id: str) -> dict[str, Any]:
        return self.update_profile(profile_id, ModelProfileUpdateRequest(enabled=False))

    def delete_profile(self, profile_id: str) -> dict[str, Any]:
        profiles = self._read_profiles()
        profile = self._find_profile(profiles, profile_id)
        backend = self._profile_backend()
        if backend is not None:
            backend.delete_profile(profile_id)
            self._clear_profile_list_cache()
            return {
                "kind": "settings_model_profile_deleted",
                "schema_version": 1,
                "profile_id": profile_id,
                "deleted": True,
            }
        secrets = self._read_secrets()
        secret_ref = str(profile.get("api_key_secret_ref") or "")
        if secret_ref:
            secrets.pop(secret_ref, None)
        remaining = [item for item in profiles if item.get("profile_id") != profile_id]
        self._write_profiles(remaining)
        self._write_secrets(secrets)
        self._clear_profile_list_cache()
        return {
            "kind": "settings_model_profile_deleted",
            "schema_version": 1,
            "profile_id": profile_id,
            "deleted": True,
        }

    def _find_profile(self, profiles: list[dict[str, Any]], profile_id: str) -> dict[str, Any]:
        for profile in profiles:
            if str(profile.get("profile_id") or "") == str(profile_id):
                return profile
        raise FileNotFoundError("model profile not found")

    def _resolve_runtime_profile(
        self,
        *,
        scope: str,
        profile_id: str | None = None,
    ) -> tuple[dict[str, Any], str, bool] | None:
        normalized_scope = normalize_scope(scope)
        normalized_profile_id = str(profile_id or "").strip()
        env_locked = any(env_locks_payload()["sources"].values())

        if env_locked:
            if normalized_profile_id:
                raise ValueError("environment LLM config is locked; model_profile_id override is not allowed")
            return None

        profiles = self._read_profiles()
        secrets = self._read_secrets()

        if normalized_profile_id:
            profile = self._find_profile(profiles, normalized_profile_id)
            if not bool(profile.get("enabled", True)):
                raise ValueError("model profile is disabled")
            secret = secrets.get(_profile_secret_ref(profile), "")
            return profile, secret, bool((profile.get("default_scopes") or {}).get(normalized_scope))

        for profile in profiles:
            if not bool(profile.get("enabled", True)):
                continue
            if not bool((profile.get("default_scopes") or {}).get(normalized_scope)):
                continue
            secret = secrets.get(_profile_secret_ref(profile), "")
            if secret:
                return profile, secret, True

        for profile in profiles:
            if not bool(profile.get("enabled", True)):
                continue
            secret = secrets.get(_profile_secret_ref(profile), "")
            if secret:
                return profile, secret, False
        return None

    def _public_profile(self, profile: dict[str, Any], *, secrets: dict[str, str] | None = None) -> dict[str, Any]:
        secret_map = secrets if secrets is not None else self._read_secrets()
        secret = secret_map.get(_profile_secret_ref(profile))
        stored_mask = str(profile.get("api_key_masked") or "") if _profile_secret_ref(profile) else ""
        public = {
            key: value
            for key, value in profile.items()
            if key not in {"api_key_secret_ref", "api_key_ciphertext", "api_key_kid"}
        }
        public["base_url"] = normalize_base_url(public.get("base_url"))
        public["metadata"] = safe_profile_metadata(public.get("metadata"))
        public["api_key_masked"] = mask_secret(secret) if secret else stored_mask
        public["has_api_key"] = bool(secret or stored_mask)
        public["model_config_hash"] = model_config_hash(profile)
        return public

    def _read_profiles(self) -> list[dict[str, Any]]:
        backend = self._profile_backend()
        if backend is not None:
            return backend.read_profiles()
        payload = _read_json(self._profile_path, {"schema_version": 1, "profiles": []})
        profiles = payload.get("profiles") if isinstance(payload, dict) else []
        return [dict(item) for item in profiles] if isinstance(profiles, list) else []

    def _write_profiles(self, profiles: list[dict[str, Any]]) -> None:
        assert_storage_write_available(self.storage_status())
        backend = self._profile_backend()
        if backend is not None:
            backend.write_profiles(profiles)
            self._clear_profile_list_cache()
            return
        _write_json(self._profile_path, {"schema_version": 1, "profiles": profiles})
        self._clear_profile_list_cache()

    def _read_secrets(self) -> dict[str, str]:
        backend = self._profile_backend()
        if backend is not None:
            return backend.read_secrets()
        payload = _read_json(self._secret_path, {"schema_version": 1, "secrets": {}})
        secrets = payload.get("secrets") if isinstance(payload, dict) else {}
        return {str(key): str(value) for key, value in secrets.items()} if isinstance(secrets, dict) else {}

    def _write_secrets(self, secrets: dict[str, str]) -> None:
        assert_storage_write_available(self.storage_status())
        backend = self._profile_backend()
        if backend is not None:
            backend.write_secrets(secrets)
            return
        _write_json(self._secret_path, {"schema_version": 1, "secrets": secrets}, mode=0o600)

    def _ensure_secret_can_be_saved(self, secret: str) -> None:
        if not secret:
            return
        assert_storage_write_available(self.storage_status())
        backend = self._profile_backend()
        if backend is not None:
            backend.ensure_can_save_secret()

    def _profile_backend(self) -> "_PostgresModelProfileBackend | None":
        backend, _status = self._profile_backend_with_status()
        return backend

    def _profile_backend_with_status(self) -> tuple["_PostgresModelProfileBackend | None", dict[str, Any]]:
        cached = self._backend_status_cache
        if cached is not None and cached[0] > time.monotonic():
            return cached[1], dict(cached[2])
        if self._connection_factory is None:
            return None, local_file_storage_status(path=str(self._profile_path))
        try:
            conn = self._connection_factory()
        except Exception as exc:
            return None, postgres_storage_status(
                table="ui_model_profiles",
                ready=False,
                reason="connection_unavailable",
                message=f"PostgreSQL settings storage cannot be reached: {type(exc).__name__}",
                actions=["verify PostgreSQL connectivity for UI settings storage"],
                secret_encryption="unknown",
            )
        try:
            table_exists = getattr(conn, "table_exists", None)
            if not callable(table_exists):
                return None, postgres_storage_status(
                    table="ui_model_profiles",
                    ready=False,
                    reason="schema_check_unavailable",
                    message="PostgreSQL settings storage cannot verify ui_model_profiles.",
                    actions=["upgrade the UI storage adapter so table_exists is available"],
                    secret_encryption="unknown",
                )
            if not table_exists("ui_model_profiles"):
                return None, postgres_storage_status(
                    table="ui_model_profiles",
                    ready=False,
                    reason="missing_table",
                    message="PostgreSQL settings table ui_model_profiles is missing.",
                    actions=["run database migrations for ui_model_profiles"],
                    secret_encryption="unknown",
                )
        except Exception as exc:
            return None, postgres_storage_status(
                table="ui_model_profiles",
                ready=False,
                reason="schema_check_failed",
                message=f"PostgreSQL settings storage cannot verify ui_model_profiles: {type(exc).__name__}",
                actions=["verify PostgreSQL schema permissions for UI settings storage"],
                secret_encryption="unknown",
            )
        finally:
            try:
                conn.close()
            except Exception:
                pass
        backend = _PostgresModelProfileBackend(self._connection_factory)
        try:
            ensure_settings_secret_encryption_configured()
        except SettingsSecretEncryptionError as exc:
            return backend, postgres_storage_status(
                table="ui_model_profiles",
                ready=False,
                reason="secret_encryption_missing",
                message=str(exc),
                actions=["set SETTINGS_SECRET_ENCRYPTION_KEY before editing model profiles"],
                secret_encryption="missing",
            )
        status = postgres_storage_status(
            table="ui_model_profiles",
            ready=True,
            secret_encryption="configured",
        )
        self._backend_status_cache = (time.monotonic() + 5.0, backend, dict(status))
        return backend, status

    def _cached_backend_profiles(self, backend: "_PostgresModelProfileBackend") -> list[dict[str, Any]]:
        cached = self._profile_list_cache
        if cached is not None and cached[0] > time.monotonic():
            return [dict(item) for item in cached[1]]
        profiles = backend.read_profiles()
        self._profile_list_cache = (time.monotonic() + 5.0, [dict(item) for item in profiles])
        return profiles

    def _clear_profile_list_cache(self) -> None:
        self._profile_list_cache = None


class _PostgresModelProfileBackend:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._connection_factory = connection_factory

    def ensure_can_save_secret(self) -> None:
        ensure_settings_secret_encryption_configured()

    def read_profiles(self) -> list[dict[str, Any]]:
        conn = self._connection_factory()
        try:
            return [_profile_from_db_row(row) for row in ModelProfileRepository(conn).list_profiles()]
        finally:
            conn.close()

    def write_profiles(self, profiles: list[dict[str, Any]]) -> None:
        conn = self._connection_factory()
        try:
            repo = ModelProfileRepository(conn)
            existing = {str(row.get("profile_id") or ""): row for row in repo.list_profiles()}
            incoming_ids: set[str] = set()
            for profile in profiles:
                profile_id = str(profile.get("profile_id") or "")
                if not profile_id:
                    continue
                incoming_ids.add(profile_id)
                previous = existing.get(profile_id, {})
                row = _profile_to_db_row(profile, previous=previous)
                repo.upsert(row)
            for profile_id in sorted(set(existing) - incoming_ids):
                repo.delete(profile_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_profile(self, profile_id: str) -> None:
        conn = self._connection_factory()
        try:
            ModelProfileRepository(conn).delete(profile_id)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def read_secrets(self) -> dict[str, str]:
        conn = self._connection_factory()
        try:
            profiles = ModelProfileRepository(conn).list_profiles()
        finally:
            conn.close()
        secrets: dict[str, str] = {}
        for row in profiles:
            profile_id = str(row.get("profile_id") or "")
            ciphertext = str(row.get("api_key_ciphertext") or "")
            if not profile_id or not ciphertext:
                continue
            secrets[_secret_ref_for_profile_id(profile_id)] = decrypt_settings_secret(ciphertext)
        return secrets

    def write_secrets(self, secrets: dict[str, str]) -> None:
        conn = self._connection_factory()
        try:
            repo = ModelProfileRepository(conn)
            profiles = repo.list_profiles()
            now = beijing_now_iso()
            for profile in profiles:
                profile_id = str(profile.get("profile_id") or "")
                if not profile_id:
                    continue
                secret_ref = _secret_ref_for_profile_id(profile_id)
                secret = str(secrets.get(secret_ref) or "")
                if secret:
                    encrypted = encrypt_settings_secret(secret)
                    repo.set_api_key(
                        profile_id=profile_id,
                        ciphertext=encrypted["ciphertext"],
                        key_id=encrypted["key_id"],
                        masked=mask_secret(secret),
                        updated_at=now,
                    )
                elif not _db_row_has_secret(profile):
                    repo.clear_api_key(profile_id=profile_id, updated_at=now)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _profile_from_db_row(row: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(row.get("profile_id") or "")
    has_secret = _db_row_has_secret(row)
    return {
        "profile_id": profile_id,
        "name": str(row.get("name") or ""),
        "provider": normalize_provider(str(row.get("provider") or "")),
        "base_url": normalize_base_url(row.get("base_url")),
        "model": str(row.get("model") or ""),
        "api_key_secret_ref": _secret_ref_for_profile_id(profile_id) if has_secret else "",
        "api_key_masked": str(row.get("api_key_masked") or "") if has_secret else "",
        "temperature": row.get("temperature"),
        "timeout_seconds": row.get("timeout_seconds"),
        "max_retries": row.get("max_retries"),
        "enabled": bool(row.get("enabled", True)),
        "default_scopes": normalize_bool_map(row.get("default_scopes"), MODEL_PROFILE_SCOPES),
        "capabilities": normalize_bool_map(row.get("capabilities"), MODEL_PROFILE_CAPABILITIES, default_true={"chat"}),
        "metadata": safe_profile_metadata(row.get("metadata")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "last_tested_at": row.get("last_tested_at"),
        "last_test_status": str(row.get("last_test_status") or "untested"),
        "last_test_error": str(row.get("last_test_error") or ""),
    }


def _profile_to_db_row(profile: dict[str, Any], *, previous: dict[str, Any]) -> dict[str, Any]:
    profile_id = str(profile.get("profile_id") or "")
    keep_secret = bool(_profile_secret_ref(profile))
    return {
        "profile_id": profile_id,
        "name": str(profile.get("name") or ""),
        "provider": normalize_provider(str(profile.get("provider") or "")),
        "base_url": normalize_base_url(profile.get("base_url")),
        "model": str(profile.get("model") or ""),
        "api_key_ciphertext": previous.get("api_key_ciphertext") if keep_secret else None,
        "api_key_kid": previous.get("api_key_kid") if keep_secret else None,
        "api_key_masked": previous.get("api_key_masked") if keep_secret else "",
        "temperature": profile.get("temperature"),
        "timeout_seconds": profile.get("timeout_seconds"),
        "max_retries": profile.get("max_retries"),
        "enabled": bool(profile.get("enabled", True)),
        "default_scopes": normalize_bool_map(profile.get("default_scopes"), MODEL_PROFILE_SCOPES),
        "capabilities": normalize_bool_map(profile.get("capabilities"), MODEL_PROFILE_CAPABILITIES, default_true={"chat"}),
        "metadata": safe_profile_metadata(profile.get("metadata")),
        "created_at": profile.get("created_at") or beijing_now_iso(),
        "updated_at": profile.get("updated_at") or beijing_now_iso(),
        "last_tested_at": profile.get("last_tested_at"),
        "last_test_status": str(profile.get("last_test_status") or "untested"),
        "last_test_error": str(profile.get("last_test_error") or ""),
    }


def _profile_secret_ref(profile: dict[str, Any]) -> str:
    explicit = str(profile.get("api_key_secret_ref") or "").strip()
    if explicit:
        return explicit
    profile_id = str(profile.get("profile_id") or "").strip()
    if not profile_id:
        return ""
    if str(profile.get("api_key_masked") or ""):
        return _secret_ref_for_profile_id(profile_id)
    return ""


def _secret_ref_for_profile_id(profile_id: str) -> str:
    return f"model_profile:{profile_id}:api_key"


def _db_row_has_secret(row: dict[str, Any]) -> bool:
    return bool(row.get("api_key_ciphertext") or row.get("api_key_masked"))


def settings_admin_payload(*, storage: dict[str, Any] | None = None) -> dict[str, Any]:
    enabled = _env_true("SETTINGS_ADMIN_ENABLED")
    token_configured = bool(os.environ.get("SETTINGS_ADMIN_TOKEN"))
    storage_ready = _settings_storage_write_available(storage)
    write_blocked_reason = _settings_storage_blocked_reason(storage)
    return {
        "enabled": enabled,
        "token_configured": token_configured,
        "write_available": enabled and token_configured and storage_ready,
        "storage": storage or {},
        "write_blocked_reason": "" if storage_ready else write_blocked_reason,
    }


def settings_admin_authorized(token: str | None) -> bool:
    admin = settings_admin_payload()
    if not admin["write_available"]:
        return False
    return bool(token) and token == os.environ.get("SETTINGS_ADMIN_TOKEN")


def _settings_storage_write_available(storage: dict[str, Any] | None) -> bool:
    if not storage:
        return True
    if "ready" in storage or "read_only" in storage:
        return storage_write_available(storage)
    states = [value for value in storage.values() if isinstance(value, dict)]
    return all(storage_write_available(state) for state in states)


def _settings_storage_blocked_reason(storage: dict[str, Any] | None) -> str:
    if not storage:
        return ""
    if "ready" in storage or "read_only" in storage:
        return str(storage.get("reason") or "storage_unavailable")
    for state in storage.values():
        if isinstance(state, dict) and not storage_write_available(state):
            return str(state.get("reason") or "storage_unavailable")
    return ""


def env_locks_payload() -> dict[str, Any]:
    locked = any(bool(os.environ.get(key)) for key in LLM_ENV_LOCK_KEYS)
    return {
        **{scope: locked for scope in MODEL_PROFILE_SCOPES},
        "sources": {key: bool(os.environ.get(key)) for key in LLM_ENV_LOCK_KEYS},
    }


def runtime_variables_payload() -> list[dict[str, Any]]:
    admin = settings_admin_payload()
    env_locks = env_locks_payload()
    return [
        {
            "key": "SETTINGS_ADMIN_ENABLED",
            "label": "设置写权限",
            "value": "true" if admin["enabled"] else "false",
            "state": "requires_restart",
            "locked": True,
            "secret": False,
        },
        {
            "key": "SETTINGS_ADMIN_TOKEN",
            "label": "管理员令牌",
            "value": "已配置" if admin["token_configured"] else "未配置",
            "state": "requires_restart",
            "locked": True,
            "secret": True,
        },
        {
            "key": "WEREWOLF_LLM_*",
            "label": "环境变量模型",
            "value": "锁定默认模型" if any(env_locks["sources"].values()) else "未锁定",
            "state": "env_locked" if any(env_locks["sources"].values()) else "editable_next_task",
            "locked": any(env_locks["sources"].values()),
            "secret": True,
        },
    ]


def normalize_provider(value: str) -> str:
    provider = str(value or "openai_compatible").strip().lower()
    return provider if provider in MODEL_PROFILE_PROVIDERS else "custom"


def normalize_base_url(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        sanitized = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
    except ValueError:
        sanitized = text.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return sanitized or text.split("?", 1)[0].split("#", 1)[0].rstrip("/")


def safe_profile_metadata(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    redacted = redact(source, context="diagnostic")
    return redacted if isinstance(redacted, dict) else {}


def normalize_scope(value: str) -> str:
    scope = str(value or "").strip()
    return scope if scope in MODEL_PROFILE_SCOPES else "game_decision"


def normalize_bool_map(
    value: dict[str, Any] | None,
    keys: tuple[str, ...],
    *,
    default_true: set[str] | None = None,
) -> dict[str, bool]:
    default_true = default_true or set()
    source = value if isinstance(value, dict) else {}
    return {
        key: bool(source.get(key, key in default_true))
        for key in keys
    }


def scope_label(scope: str) -> str:
    return {
        "game_decision": "游戏决策",
        "judge": "Judge",
        "benchmark": "Benchmark",
        "evolution": "Evolution",
        "prompt_test": "Prompt/工具测试",
    }.get(scope, scope)


def mask_secret(value: str | None) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    prefix = text[:3] if text.startswith("sk-") else text[:2]
    return f"{prefix}****{text[-4:]}"


def model_config_hash(profile: dict[str, Any]) -> str:
    public_config = {
        "provider": profile.get("provider"),
        "base_url_host": base_url_host(profile.get("base_url")),
        "model": profile.get("model"),
        "temperature": profile.get("temperature"),
        "timeout_seconds": profile.get("timeout_seconds"),
        "max_retries": profile.get("max_retries"),
    }
    raw = json.dumps(public_config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def model_profile_hash_input(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "source": "settings_profile",
        "provider": str(profile.get("provider") or ""),
        "base_url_host": base_url_host(profile.get("base_url")),
        "model": str(profile.get("model") or ""),
        "temperature": profile.get("temperature"),
        "timeout_seconds": profile.get("timeout_seconds"),
        "max_retries": profile.get("max_retries"),
        "capabilities": normalize_bool_map(profile.get("capabilities"), MODEL_PROFILE_CAPABILITIES),
    }


def base_url_host(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if parsed.hostname:
        host = parsed.hostname
        if parsed.port:
            host = f"{host}:{parsed.port}"
        return host
    return text.split("/")[0]


def _new_profile_id(name: str) -> str:
    safe = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name or "model"))
    while "__" in safe:
        safe = safe.replace("__", "_")
    safe = safe.strip("_")[:28] or "model"
    return f"model_{safe}_{uuid.uuid4().hex[:8]}"


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(default)


def _write_json(path: Path, payload: dict[str, Any], *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f"{path.name}.tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temp_path.replace(path)
    if mode is not None:
        try:
            os.chmod(path, mode)
        except OSError:
            pass


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
