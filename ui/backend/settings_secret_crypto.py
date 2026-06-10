"""Encryption helpers for locally administered settings secrets."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

SETTINGS_SECRET_ENCRYPTION_KEY = "SETTINGS_SECRET_ENCRYPTION_KEY"
SETTINGS_SECRET_ENCRYPTION_KEY_ID = "SETTINGS_SECRET_ENCRYPTION_KEY_ID"
DEFAULT_SETTINGS_SECRET_KEY_ID = "settings:v1"


class SettingsSecretEncryptionError(ValueError):
    """Raised when a settings secret cannot be encrypted or decrypted."""


def ensure_settings_secret_encryption_configured() -> None:
    _fernet()


def encrypt_settings_secret(value: str) -> dict[str, str]:
    text = str(value or "")
    token = _fernet().encrypt(text.encode("utf-8")).decode("ascii")
    return {
        "ciphertext": token,
        "key_id": settings_secret_key_id(),
    }


def decrypt_settings_secret(ciphertext: Any) -> str:
    token = str(ciphertext or "").strip()
    if not token:
        return ""
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise SettingsSecretEncryptionError("settings secret cannot be decrypted with the configured key") from exc


def settings_secret_key_id() -> str:
    return os.environ.get(SETTINGS_SECRET_ENCRYPTION_KEY_ID, "").strip() or DEFAULT_SETTINGS_SECRET_KEY_ID


def _fernet() -> Fernet:
    raw = os.environ.get(SETTINGS_SECRET_ENCRYPTION_KEY, "").strip()
    if not raw:
        raise SettingsSecretEncryptionError(
            "SETTINGS_SECRET_ENCRYPTION_KEY is required for PostgreSQL settings secret storage"
        )
    return Fernet(_normalize_fernet_key(raw))


def _normalize_fernet_key(raw: str) -> bytes:
    encoded = raw.encode("ascii", errors="ignore")
    try:
        Fernet(encoded)
        return encoded
    except (ValueError, TypeError):
        digest = hashlib.sha256(raw.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)
