"""Role and version response shaping helpers for the UI backend."""

from __future__ import annotations

import hashlib
from typing import Any

def _version_summary_payload(version: dict[str, Any]) -> dict[str, Any]:
    return {
        **version,
        "metrics": version.get("metrics") or _empty_version_metrics(),
    }

def _version_detail_payload(
    *,
    role: str,
    version_id: str,
    contents: dict[str, str],
    source: str,
    status: str = "active",
) -> dict[str, Any]:
    files = [{"path": path, "content": content} for path, content in sorted(contents.items())]
    skills = [
        {
            "path": path,
            "filename": path,
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "size": len(content.encode("utf-8")),
        }
        for path, content in sorted(contents.items())
    ]
    return {
        "kind": "knowledge_package",
        "schema_version": 1,
        "role": role,
        "version_id": version_id,
        "source": source,
        "provenance": {"source": source},
        "metrics": _empty_version_metrics(),
        "files": files,
        "skills": skills,
        "patterns": [],
        "status": status,
    }

def _empty_version_metrics() -> dict[str, Any]:
    return {
        "score": 0.0,
        "win_rate": 0.0,
        "games_played": 0,
    }

def _fallback_version(role: str) -> dict[str, Any]:
    return {
        "version_id": f"{role}_baseline",
        "role": role,
        "source": "app-fallback",
        "created_at": "",
        "is_baseline": True,
        "status": "missing_registry",
    }
