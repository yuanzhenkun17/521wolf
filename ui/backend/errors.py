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


def release_stage_not_allowed_detail(
    exc: Any,
    *,
    code: str,
    message: str,
    detail_prefix: str,
    kind: str,
) -> dict[str, Any] | None:
    """Normalize release-stage errors even when class identity differs across imports."""
    role = str(getattr(exc, "role", "") or "").strip()
    version_id = str(getattr(exc, "version_id", "") or "").strip()
    release_stage = str(getattr(exc, "release_stage", "") or "").strip()
    if not role or not version_id or not release_stage:
        return None

    diagnostic = None
    diagnostic_fn = getattr(exc, "diagnostic", None)
    if callable(diagnostic_fn):
        diagnostic = diagnostic_fn(kind=kind)
    if not isinstance(diagnostic, dict):
        diagnostic = release_stage_diagnostic(
            role=role,
            version_id=version_id,
            release_stage=release_stage,
            kind=kind,
            allowed_flow=str(getattr(exc, "allowed_flow", "") or "explicit_evaluation"),
        )
    return domain_error_detail(
        code=code,
        message=message,
        detail=f"{detail_prefix}: {exc}",
        diagnostics=[diagnostic],
    )

