"""Structured API error helpers for UI backend routes."""

from __future__ import annotations

from typing import Any


def domain_error_detail(
    *,
    code: str,
    message: str,
    detail: str | None = None,
    diagnostics: list[Any] | None = None,
) -> dict[str, Any]:
    """HTTPException.detail payload consumed by the global error handler."""
    return {
        "detail": detail or message,
        "code": code,
        "message": message,
        "diagnostics": list(diagnostics or []),
    }


def release_stage_diagnostic(
    *,
    role: str,
    version_id: str,
    release_stage: str,
    kind: str,
    allowed_flow: str,
) -> dict[str, str]:
    return {
        "kind": kind,
        "role": str(role),
        "version_id": str(version_id),
        "release_stage": str(release_stage),
        "allowed_flow": str(allowed_flow),
    }

