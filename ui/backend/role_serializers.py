"""Role and version response shaping helpers for the UI backend."""

from __future__ import annotations

from collections.abc import Mapping
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
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(summary or {})
    raw_provenance = metadata.get("provenance")
    provenance = dict(raw_provenance) if isinstance(raw_provenance, Mapping) else {}
    payload_source = str(metadata.get("source") or provenance.get("source") or source)
    provenance.setdefault("source", payload_source)

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
    payload: dict[str, Any] = {
        "kind": "knowledge_package",
        "schema_version": 1,
        "role": role,
        "version_id": version_id,
        "source": payload_source,
        "provenance": provenance,
        "metrics": _version_metrics(metadata),
        "files": files,
        "skills": skills,
        "patterns": [],
        "status": str(metadata.get("status") or status),
    }
    if "created_at" in metadata:
        payload["created_at"] = metadata.get("created_at")
    if "is_baseline" in metadata:
        payload["is_baseline"] = bool(metadata.get("is_baseline"))

    release_stage = metadata.get("release_stage") or provenance.get("release_stage")
    if release_stage is not None:
        payload["release_stage"] = release_stage

    for key in ("trust_bundle_id", "gate_report_id", "attribution_report_id", "bundle_hash"):
        value = metadata.get(key)
        if value is None:
            value = provenance.get(key)
        if value is not None:
            payload[key] = value

    source_run_id = metadata.get("source_run_id") or provenance.get("source_run_id") or provenance.get("run_id")
    if source_run_id is not None:
        payload["source_run_id"] = source_run_id

    return payload


def _version_metrics(version: Mapping[str, Any]) -> dict[str, Any]:
    metrics = version.get("metrics")
    return dict(metrics) if isinstance(metrics, Mapping) else _empty_version_metrics()


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
