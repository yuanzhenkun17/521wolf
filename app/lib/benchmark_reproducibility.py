"""Standalone benchmark reproducibility manifest helpers."""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

BENCHMARK_REPRODUCIBILITY_SCHEMA_VERSION = 1

_SECRET_VALUE = "[REDACTED]"
_INLINE_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|"
        r"auth[_-]?token|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;]+"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)

_SCALAR_REQUIRED_FIELDS = (
    "schema_version",
    "benchmark_id",
    "benchmark_version",
    "evaluation_set_id",
    "benchmark_config_hash",
    "seed_set_id",
    "seed_set_version",
    "seed_set_config_hash",
    "model_id",
    "model_config_hash",
    "created_at",
    "content_hash",
)
_CONTAINER_REQUIRED_FIELDS = (
    "model_runtime",
    "source_filter",
    "planner",
    "request",
    "artifact_hashes",
)
_COMPARABLE_FIELDS = _SCALAR_REQUIRED_FIELDS[1:] + _CONTAINER_REQUIRED_FIELDS
_HASH_KEYS = {
    "artifact_hash",
    "content_hash",
    "export_content_hash",
    "export_hash",
    "report_content_hash",
    "snapshot_hash",
}


def build_benchmark_reproducibility_manifest(
    run_payload: Mapping[str, Any] | None = None,
    report_payload: Mapping[str, Any] | None = None,
    export_payload: Mapping[str, Any] | None = None,
    *,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build a stable manifest from benchmark run, report, and export evidence.

    The helper intentionally stays storage/API agnostic so it can be introduced
    without changing existing benchmark persistence paths.
    """
    payloads = tuple(payload for payload in (run_payload, report_payload, export_payload) if payload)
    redacted_payloads, redacted_field_count = _redact_payloads(payloads)

    manifest: dict[str, Any] = {
        "schema_version": BENCHMARK_REPRODUCIBILITY_SCHEMA_VERSION,
        "benchmark_id": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "benchmark_id",
                    "benchmark.id",
                    "benchmark.benchmark_id",
                    "config.benchmark_id",
                    "request.benchmark_id",
                ),
            )
        ),
        "benchmark_version": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "benchmark_version",
                    "benchmark.version",
                    "benchmark.benchmark_version",
                    "config.benchmark_version",
                ),
            )
        ),
        "evaluation_set_id": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "evaluation_set_id",
                    "benchmark.evaluation_set_id",
                    "config.evaluation_set_id",
                    "request.evaluation_set_id",
                ),
            )
        ),
        "benchmark_config_hash": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "benchmark_config_hash",
                    "config.benchmark_config_hash",
                    "benchmark.benchmark_config_hash",
                    "benchmark.config_hash",
                    "config_hash",
                ),
            )
        ),
        "seed_set_id": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "seed_set_id",
                    "seed_set.id",
                    "benchmark.seed_set_id",
                    "config.seed_set_id",
                    "request.seed_set_id",
                ),
            )
        ),
        "seed_set_version": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "seed_set_version",
                    "seed_set.version",
                    "benchmark.seed_set_version",
                    "config.seed_set_version",
                ),
            )
        ),
        "seed_set_config_hash": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "seed_set_config_hash",
                    "seed_set.config_hash",
                    "benchmark.seed_set_config_hash",
                    "config.seed_set_config_hash",
                ),
            )
        ),
        "model_id": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "model_id",
                    "model.id",
                    "subject.model_id",
                    "subject.id",
                    "config.model_id",
                    "model_runtime.model_id",
                ),
            )
        ),
        "model_config_hash": _string_value(
            _first_path(
                redacted_payloads,
                (
                    "model_config_hash",
                    "model.config_hash",
                    "subject.model_config_hash",
                    "config.model_config_hash",
                    "model_runtime.model_config_hash",
                    "model_runtime.hash",
                ),
            )
        ),
        "model_runtime": _mapping_value(
            _first_path(
                redacted_payloads,
                (
                    "model_runtime",
                    "model.runtime",
                    "subject.model_runtime",
                    "config.model_runtime",
                ),
            )
        ),
        "source_filter": _mapping_value(
            _first_path(
                redacted_payloads,
                (
                    "source_filter",
                    "benchmark.source_filter",
                    "config.source_filter",
                    "request.source_filter",
                ),
            )
        ),
        "planner": _mapping_value(
            _first_path(
                redacted_payloads,
                (
                    "planner",
                    "plan",
                    "planning",
                    "benchmark_plan",
                    "metadata.planner",
                ),
            )
        ),
        "request": _mapping_value(
            _first_path(
                redacted_payloads,
                (
                    "request",
                    "params",
                    "request_params",
                    "config.request",
                    "planner.request",
                ),
            )
        ),
        "artifact_hashes": _artifact_hashes(redacted_payloads),
        "created_at": _string_value(
            created_at
            if created_at is not None
            else _first_path(
                redacted_payloads,
                (
                    "created_at",
                    "queued_at",
                    "started_at",
                    "report.created_at",
                    "artifacts.created_at",
                ),
            )
        ),
        "redaction": {
            "redacted_field_count": redacted_field_count,
        },
    }
    manifest["content_hash"] = _string_value(manifest["artifact_hashes"].get("content_hash"))
    manifest["manifest_hash"] = compute_benchmark_reproducibility_manifest_hash(manifest)
    return manifest


def stable_benchmark_hash(value: Any) -> str:
    """Return a sha256 hash over canonical JSON, insensitive to dict key order."""
    normalized = _normalize_for_hash(value)
    content = json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


def stable_reproducibility_hash(value: Any) -> str:
    """Alias for callers that prefer the benchmark-specific naming."""
    return stable_benchmark_hash(value)


def compute_benchmark_reproducibility_manifest_hash(manifest: Mapping[str, Any]) -> str:
    """Hash a manifest without including its own ``manifest_hash`` field."""
    payload = dict(manifest)
    payload.pop("manifest_hash", None)
    return stable_benchmark_hash(payload)


def verify_benchmark_reproducibility_manifest(
    manifest: Mapping[str, Any],
    expected_evidence: Mapping[str, Any] | None = None,
    current_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify required manifest evidence and compare optional expected/current data."""
    normalized_manifest = _normalize_for_hash(manifest)
    missing = _missing_required_fields(normalized_manifest)
    mismatches: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    schema_version = normalized_manifest.get("schema_version")
    if schema_version != BENCHMARK_REPRODUCIBILITY_SCHEMA_VERSION:
        warnings.append(
            {
                "code": "unsupported_schema_version",
                "field": "schema_version",
                "actual": schema_version,
                "expected": BENCHMARK_REPRODUCIBILITY_SCHEMA_VERSION,
            }
        )

    if _contains_sensitive_material(normalized_manifest):
        mismatches.append(
            {
                "code": "sensitive_material_present",
                "field": "manifest",
                "message": "manifest contains sensitive key names or secret-looking values",
            }
        )

    manifest_hash = normalized_manifest.get("manifest_hash")
    if manifest_hash:
        computed_hash = compute_benchmark_reproducibility_manifest_hash(normalized_manifest)
        if manifest_hash != computed_hash:
            mismatches.append(
                {
                    "code": "manifest_hash_mismatch",
                    "field": "manifest_hash",
                    "expected": computed_hash,
                    "actual": manifest_hash,
                }
            )

    for label, evidence in (("expected", expected_evidence), ("current", current_evidence)):
        if evidence is None:
            continue
        evidence_manifest = _manifest_like_from_evidence(evidence)
        _compare_manifest_fields(
            actual_manifest=normalized_manifest,
            evidence_manifest=evidence_manifest,
            evidence_label=label,
            mismatches=mismatches,
        )

    return {
        "ok": not missing and not mismatches,
        "missing": missing,
        "mismatches": mismatches,
        "warnings": warnings,
        "manifest_hash": compute_benchmark_reproducibility_manifest_hash(normalized_manifest),
    }


def _redact_payloads(payloads: Sequence[Mapping[str, Any]]) -> tuple[tuple[dict[str, Any], ...], int]:
    redacted: list[dict[str, Any]] = []
    redacted_field_count = 0
    for payload in payloads:
        clean_payload, count = _redact_sensitive(payload)
        if isinstance(clean_payload, Mapping):
            redacted.append(dict(clean_payload))
        redacted_field_count += count
    return tuple(redacted), redacted_field_count


def _redact_sensitive(value: Any) -> tuple[Any, int]:
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        count = 0
        for key, item in value.items():
            key_text = str(key)
            if _is_sensitive_key(key_text):
                count += 1
                continue
            clean_item, item_count = _redact_sensitive(item)
            redacted[key_text] = clean_item
            count += item_count
        return redacted, count
    if isinstance(value, tuple):
        items, count = _redact_sequence(value)
        return tuple(items), count
    if isinstance(value, list):
        return _redact_sequence(value)
    if isinstance(value, set):
        items, count = _redact_sequence(sorted(value, key=lambda item: repr(item)))
        return items, count
    if isinstance(value, str):
        cleaned = value
        for pattern in _INLINE_SECRET_PATTERNS:
            cleaned = pattern.sub(_SECRET_VALUE, cleaned)
        if cleaned != value:
            return _SECRET_VALUE, 1
        return cleaned, 0
    return _jsonable(value), 0


def _redact_sequence(value: Sequence[Any]) -> tuple[list[Any], int]:
    redacted: list[Any] = []
    count = 0
    for item in value:
        clean_item, item_count = _redact_sensitive(item)
        redacted.append(clean_item)
        count += item_count
    return redacted, count


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    if not normalized:
        return False
    exact = {
        "apikey",
        "accesskey",
        "secretkey",
        "password",
        "passwd",
        "token",
        "authorization",
        "cookie",
        "credential",
        "credentials",
        "privatekey",
        "clientsecret",
    }
    if normalized in exact:
        return True
    if any(part in normalized for part in ("apikey", "password", "passwd", "secret", "credential")):
        return True
    if normalized.endswith("token") and not normalized.endswith("tokens"):
        return True
    return normalized.endswith("key") and "access" in normalized


def _contains_sensitive_material(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            _is_sensitive_key(str(key)) or _contains_sensitive_material(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_sensitive_material(item) for item in value)
    if isinstance(value, tuple):
        return any(_contains_sensitive_material(item) for item in value)
    if isinstance(value, str):
        return any(pattern.search(value) for pattern in _INLINE_SECRET_PATTERNS)
    return False


def _first_path(payloads: Sequence[Mapping[str, Any]], paths: Sequence[str]) -> Any:
    for payload in payloads:
        for path in paths:
            found, value = _path_value(payload, path)
            if found and not _is_blank(value):
                return value
    return None


def _path_value(payload: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    value: Any = payload
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return False, None
        value = value[part]
    return True, value


def _string_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _mapping_value(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(_normalize_for_hash(value))
    return {}


def _artifact_hashes(payloads: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for payload in payloads:
        hashes.update(_collect_artifact_hashes(payload, broad=False))
        for path in ("artifacts", "artifact_hashes", "exports", "export"):
            found, value = _path_value(payload, path)
            if found:
                hashes.update(_collect_artifact_hashes(value, broad=True))
    return {key: hashes[key] for key in sorted(hashes)}


def _collect_artifact_hashes(value: Any, prefix: str = "", *, broad: bool = True) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    hashes: dict[str, str] = {}
    for key, item in value.items():
        key_text = str(key)
        normalized_key = key_text.lower()
        output_key = f"{prefix}{key_text}" if prefix else key_text
        if isinstance(item, Mapping):
            if broad:
                hashes.update(_collect_artifact_hashes(item, prefix=f"{output_key}.", broad=broad))
            continue
        if broad and prefix and isinstance(item, str) and item.startswith("sha256:"):
            hashes[output_key] = item
            continue
        if _is_hash_key(normalized_key, broad=broad) and not _is_blank(item):
            hashes[output_key] = _string_value(item)
    return hashes


def _is_hash_key(key: str, *, broad: bool) -> bool:
    return key in _HASH_KEYS or (broad and (key.endswith("_hash") or key.endswith(".hash")))


def _missing_required_fields(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for field in _SCALAR_REQUIRED_FIELDS:
        if field not in manifest or _is_blank(manifest.get(field)):
            missing.append({"field": field, "code": "missing_required_field"})
    for field in _CONTAINER_REQUIRED_FIELDS:
        if field not in manifest:
            missing.append({"field": field, "code": "missing_required_field"})
    if isinstance(manifest.get("artifact_hashes"), Mapping) and not manifest["artifact_hashes"]:
        missing.append({"field": "artifact_hashes", "code": "missing_required_hashes"})
    return missing


def _compare_manifest_fields(
    *,
    actual_manifest: Mapping[str, Any],
    evidence_manifest: Mapping[str, Any],
    evidence_label: str,
    mismatches: list[dict[str, Any]],
) -> None:
    for field in _COMPARABLE_FIELDS:
        expected = evidence_manifest.get(field)
        if _is_blank(expected):
            continue
        if field == "artifact_hashes" and isinstance(expected, Mapping):
            actual_hashes = actual_manifest.get("artifact_hashes")
            if not isinstance(actual_hashes, Mapping):
                mismatches.append(
                    {
                        "code": "evidence_mismatch",
                        "source": evidence_label,
                        "field": field,
                        "expected": expected,
                        "actual": actual_hashes,
                    }
                )
                continue
            for key, expected_hash in expected.items():
                actual_hash = actual_hashes.get(key)
                if actual_hash != expected_hash:
                    mismatches.append(
                        {
                            "code": "evidence_mismatch",
                            "source": evidence_label,
                            "field": f"artifact_hashes.{key}",
                            "expected": expected_hash,
                            "actual": actual_hash,
                        }
                    )
            continue
        actual = actual_manifest.get(field)
        if _normalize_for_hash(actual) != _normalize_for_hash(expected):
            mismatches.append(
                {
                    "code": "evidence_mismatch",
                    "source": evidence_label,
                    "field": field,
                    "expected": expected,
                    "actual": actual,
                }
            )


def _manifest_like_from_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    if "schema_version" in evidence and any(field in evidence for field in _COMPARABLE_FIELDS):
        return dict(_normalize_for_hash(evidence))
    if any(key in evidence for key in ("run_payload", "report_payload", "export_payload")):
        return build_benchmark_reproducibility_manifest(
            run_payload=_as_mapping(evidence.get("run_payload")),
            report_payload=_as_mapping(evidence.get("report_payload")),
            export_payload=_as_mapping(evidence.get("export_payload")),
        )
    return build_benchmark_reproducibility_manifest(run_payload=evidence)


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _normalize_for_hash(value: Any) -> Any:
    value = _jsonable(value)
    if isinstance(value, Mapping):
        return {str(key): _normalize_for_hash(item) for key, item in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        return [_normalize_for_hash(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize_for_hash(item) for item in value]
    if isinstance(value, set):
        return sorted((_normalize_for_hash(item) for item in value), key=lambda item: repr(item))
    return value


def _jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Path):
        return str(value)
    return value


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False
