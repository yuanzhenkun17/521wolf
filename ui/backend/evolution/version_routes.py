"""Routes for /api/roles/* — role versions, rollback, and per-role leaderboard."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from agent.learning.evolution.leaderboard import aggregate_role_leaderboard
from ui.backend.shared.helpers import (
    get_role_evolution_runner,
    read_role_battle_summaries_from_artifacts,
    read_role_battle_summaries_from_db,
)

router = APIRouter(prefix="/api/roles", tags=["roles"])


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("")
def list_roles(
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
) -> dict[str, Any]:
    """List all roles that have stored versions."""
    registry = getattr(runner, "registry", None)
    if registry is None:
        raise HTTPException(status_code=500, detail="VersionRegistry not configured")
    roles = registry.list_roles()
    return {"roles": roles}


@router.get("/{role}/versions")
def list_role_versions(
    role: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
) -> dict[str, Any]:
    """List all versions for a role."""
    registry = getattr(runner, "registry", None)
    if registry is None:
        raise HTTPException(status_code=500, detail="VersionRegistry not configured")
    versions = registry.list_versions(role)
    if not versions:
        raise HTTPException(status_code=404, detail=f"role '{role}' not found")
    result = [v.to_dict() for v in versions]
    return {"role": role, "versions": result}


@router.get("/{role}/versions/{version_id}")
def get_role_version(
    role: str,
    version_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
) -> dict[str, Any]:
    """Get full detail of a specific role version."""
    registry = getattr(runner, "registry", None)
    if registry is None:
        raise HTTPException(status_code=500, detail="VersionRegistry not configured")
    try:
        package = registry.get_package(role, version_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"version {role}/{version_id} not found",
        )
    data = package.to_dict()
    data["kind"] = "knowledge_package"
    data["schema_version"] = 2
    return data


@router.get("/{role}/leaderboard")
def role_leaderboard(
    role: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
) -> dict[str, Any]:
    """Return the role evolution leaderboard for a role."""
    battle_summaries = read_role_battle_summaries_from_db(role)
    source = "sqlite" if battle_summaries else "artifacts"
    if not battle_summaries:
        battle_summaries = read_role_battle_summaries_from_artifacts(role, runner)

    entries = aggregate_role_leaderboard(
        role=role,
        battle_summaries=battle_summaries,
    )
    return {
        "kind": "role_leaderboard",
        "schema_version": 1,
        "role": role,
        "source": source,
        "entries": [e.to_dict() for e in entries],
    }


@router.post("/{role}/rollback/{version_id}")
async def rollback_baseline(
    role: str,
    version_id: str,
    runner: Annotated[Any, Depends(get_role_evolution_runner)],
) -> dict[str, Any]:
    """Rollback the baseline for a role to a specific version_id."""
    registry = getattr(runner, "registry", None)
    if registry is None:
        raise HTTPException(status_code=500, detail="VersionRegistry not configured")
    try:
        registry.get_package(role, version_id)
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"version {role}/{version_id} not found",
        )

    current = registry.get_baseline(role)
    if current is None:
        raise HTTPException(
            status_code=404,
            detail=f"role '{role}' not found",
        )

    success = await registry.set_baseline(
        role=role,
        version_id=version_id,
        expected_current=current,
    )
    if not success:
        raise HTTPException(
            status_code=409,
            detail="baseline changed concurrently; retry",
        )
    return {
        "kind": "role_rollback",
        "schema_version": 2,
        "role": role,
        "new_baseline": version_id,
    }
