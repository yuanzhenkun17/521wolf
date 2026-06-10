"""Benchmark snapshot and saved-view cache payload helpers."""

from __future__ import annotations

from typing import Any

from ui.backend.services.benchmark_payload_utils import json_clone as _json_clone


def _filter_benchmark_snapshot_cache(
    rows: list[dict[str, Any]],
    *,
    scope: str | None = None,
    evaluation_set_id: str | None = None,
    benchmark_id: str | None = None,
    target_role: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filtered = rows
    if scope:
        filtered = [row for row in filtered if row.get("scope") == scope]
    if evaluation_set_id:
        filtered = [row for row in filtered if row.get("evaluation_set_id") == evaluation_set_id]
    if benchmark_id:
        filtered = [row for row in filtered if row.get("benchmark_id") == benchmark_id]
    if target_role:
        filtered = [row for row in filtered if row.get("target_role") == target_role]
    filtered.sort(key=lambda row: (str(row.get("created_at") or ""), str(row.get("snapshot_id") or "")), reverse=True)
    return filtered[:max(1, min(int(limit or 50), 500))]


def _benchmark_view_payload(view: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "benchmark_saved_view",
        "schema_version": 1,
        "view_key": str(view.get("view_key") or ""),
        "name": str(view.get("name") or "Default view"),
        "scope": str(view.get("scope") or "role_version"),
        "benchmark_id": view.get("benchmark_id"),
        "evaluation_set_id": view.get("evaluation_set_id"),
        "target_role": view.get("target_role"),
        "view_config": _json_clone(view.get("view_config") or {}),
        "created_at": view.get("created_at"),
        "updated_at": view.get("updated_at"),
    }


def _filter_benchmark_view_cache(
    rows: list[dict[str, Any]],
    *,
    scope: str | None = None,
    evaluation_set_id: str | None = None,
    benchmark_id: str | None = None,
    target_role: str | None = None,
    view_key: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    filtered = rows
    if view_key:
        filtered = [row for row in filtered if row.get("view_key") == view_key]
    if scope:
        filtered = [row for row in filtered if row.get("scope") == scope]
    if evaluation_set_id:
        filtered = [row for row in filtered if row.get("evaluation_set_id") == evaluation_set_id]
    if benchmark_id:
        filtered = [row for row in filtered if row.get("benchmark_id") == benchmark_id]
    if target_role:
        filtered = [row for row in filtered if row.get("target_role") == target_role]
    filtered.sort(key=lambda row: (str(row.get("updated_at") or ""), str(row.get("view_key") or "")), reverse=True)
    return filtered[:max(1, min(int(limit or 50), 500))]
