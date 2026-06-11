"""Public release metadata for health and operational status payloads."""

from __future__ import annotations

import os
from typing import Any


_RELEASE_ENV_KEYS = (
    "WOLF_APP_RELEASE",
    "APP_RELEASE",
    "LANGFUSE_RELEASE",
    "GITHUB_REF_NAME",
)
_GIT_SHA_ENV_KEYS = (
    "WOLF_GIT_SHA",
    "APP_GIT_SHA",
    "GITHUB_SHA",
    "COMMIT_SHA",
    "SOURCE_VERSION",
    "VERCEL_GIT_COMMIT_SHA",
)
_ENVIRONMENT_ENV_KEYS = (
    "WOLF_APP_ENVIRONMENT",
    "APP_ENVIRONMENT",
    "LANGFUSE_ENVIRONMENT",
    "ENVIRONMENT",
)


def build_release_info() -> dict[str, Any]:
    release, release_source = _first_env_value(_RELEASE_ENV_KEYS)
    git_sha, git_sha_source = _first_env_value(_GIT_SHA_ENV_KEYS)
    environment, environment_source = _first_env_value(_ENVIRONMENT_ENV_KEYS)
    payload = {
        "release": release or "",
        "git_sha": git_sha or "",
        "git_sha_short": _short_sha(git_sha),
        "environment": environment or "",
        "configured": bool(release or git_sha or environment),
        "sources": {
            "release": release_source or "",
            "git_sha": git_sha_source or "",
            "environment": environment_source or "",
        },
    }
    return payload


def _first_env_value(keys: tuple[str, ...]) -> tuple[str, str]:
    for key in keys:
        value = os.environ.get(key, "").strip()
        if value:
            return value, key
    return "", ""


def _short_sha(value: str) -> str:
    text = str(value or "").strip()
    return text[:12] if text else ""
