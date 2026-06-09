from __future__ import annotations

import json

from app.lib.benchmark_reproducibility import (
    build_benchmark_reproducibility_manifest,
    compute_benchmark_reproducibility_manifest_hash,
    stable_benchmark_hash,
    stable_reproducibility_hash,
    verify_benchmark_reproducibility_manifest,
)


def _run_payload() -> dict:
    return {
        "benchmark": {
            "id": "role-baseline-v1",
            "version": "1.0.0",
            "evaluation_set_id": "role-baseline-eval",
            "config_hash": "sha256:benchmark",
            "seed_set_id": "role-baseline-seeds",
            "seed_set_version": "2026-06-01",
            "seed_set_config_hash": "sha256:seeds",
            "source_filter": {"sources": ["archive"], "min_finished_at": "2026-05-01"},
        },
        "model_runtime": {
            "model_id": "qwen-max",
            "model_config_hash": "sha256:model",
            "temperature": 0.2,
            "hash_source": "request",
        },
        "request": {
            "concurrency": 3,
            "game_count": 20,
            "budget_limit_cost": 12.5,
        },
        "planner": {
            "dry_run": False,
            "estimated_tokens": 12345,
            "estimated_cost": 3.21,
        },
        "queued_at": "2026-06-09T12:00:00Z",
    }


def _report_payload() -> dict:
    return {
        "subject": {
            "model_id": "qwen-max",
            "model_config_hash": "sha256:model",
        },
        "artifacts": {
            "content_hash": "sha256:report",
            "markdown": {"artifact_hash": "sha256:markdown"},
        },
    }


def _export_payload() -> dict:
    return {
        "export": {
            "format": "csv",
            "export_content_hash": "sha256:csv",
        }
    }


def test_stable_hash_ignores_dict_key_order() -> None:
    left = {
        "z": [{"b": 2, "a": 1}],
        "a": {"c": 3, "b": 2},
    }
    right = {
        "a": {"b": 2, "c": 3},
        "z": [{"a": 1, "b": 2}],
    }

    assert stable_benchmark_hash(left) == stable_benchmark_hash(right)
    assert stable_reproducibility_hash(left) == stable_benchmark_hash(left)
    assert stable_benchmark_hash(left).startswith("sha256:")


def test_build_manifest_collects_core_evidence_and_stable_manifest_hash() -> None:
    manifest = build_benchmark_reproducibility_manifest(
        _run_payload(),
        _report_payload(),
        _export_payload(),
        created_at="2026-06-09T12:05:00Z",
    )

    assert manifest["schema_version"] == 1
    assert manifest["benchmark_id"] == "role-baseline-v1"
    assert manifest["benchmark_version"] == "1.0.0"
    assert manifest["evaluation_set_id"] == "role-baseline-eval"
    assert manifest["benchmark_config_hash"] == "sha256:benchmark"
    assert manifest["seed_set_id"] == "role-baseline-seeds"
    assert manifest["seed_set_version"] == "2026-06-01"
    assert manifest["seed_set_config_hash"] == "sha256:seeds"
    assert manifest["model_id"] == "qwen-max"
    assert manifest["model_config_hash"] == "sha256:model"
    assert manifest["model_runtime"]["hash_source"] == "request"
    assert manifest["source_filter"] == {
        "min_finished_at": "2026-05-01",
        "sources": ["archive"],
    }
    assert manifest["planner"]["estimated_tokens"] == 12345
    assert manifest["request"]["game_count"] == 20
    assert manifest["artifact_hashes"] == {
        "content_hash": "sha256:report",
        "export_content_hash": "sha256:csv",
        "markdown.artifact_hash": "sha256:markdown",
    }
    assert manifest["content_hash"] == "sha256:report"
    assert manifest["manifest_hash"] == compute_benchmark_reproducibility_manifest_hash(manifest)

    shuffled_run = _run_payload()
    shuffled_run["benchmark"] = {
        "source_filter": shuffled_run["benchmark"]["source_filter"],
        "seed_set_config_hash": "sha256:seeds",
        "seed_set_version": "2026-06-01",
        "seed_set_id": "role-baseline-seeds",
        "config_hash": "sha256:benchmark",
        "evaluation_set_id": "role-baseline-eval",
        "version": "1.0.0",
        "id": "role-baseline-v1",
    }
    same_manifest = build_benchmark_reproducibility_manifest(
        shuffled_run,
        _report_payload(),
        _export_payload(),
        created_at="2026-06-09T12:05:00Z",
    )
    assert same_manifest["manifest_hash"] == manifest["manifest_hash"]


def test_verify_manifest_reports_missing_fields() -> None:
    manifest = build_benchmark_reproducibility_manifest(_run_payload(), _report_payload())
    manifest["benchmark_config_hash"] = ""
    manifest["content_hash"] = ""
    manifest["artifact_hashes"] = {}

    result = verify_benchmark_reproducibility_manifest(manifest)

    assert result["ok"] is False
    missing_fields = {item["field"] for item in result["missing"]}
    assert {"benchmark_config_hash", "content_hash", "artifact_hashes"} <= missing_fields


def test_verify_manifest_reports_expected_and_current_mismatches() -> None:
    manifest = build_benchmark_reproducibility_manifest(
        _run_payload(),
        _report_payload(),
        _export_payload(),
    )

    result = verify_benchmark_reproducibility_manifest(
        manifest,
        expected_evidence={
            "benchmark_id": "role-baseline-v1",
            "model_config_hash": "sha256:other-model",
            "artifact_hashes": {"content_hash": "sha256:other-report"},
        },
        current_evidence={
            "benchmark_id": "different-suite",
            "seed_set_config_hash": "sha256:seeds",
        },
    )

    assert result["ok"] is False
    fields = {item["field"] for item in result["mismatches"]}
    assert "model_config_hash" in fields
    assert "artifact_hashes.content_hash" in fields
    assert "benchmark_id" in fields


def test_build_manifest_redacts_secrets_from_runtime_request_and_hash_input() -> None:
    run_payload = _run_payload()
    run_payload["model_runtime"]["api_key"] = "sk-super-secret"
    run_payload["model_runtime"]["model_kwargs"] = {
        "public_label": "kept",
        "password": "hunter2",
    }
    run_payload["request"]["token"] = "request-token"
    run_payload["request"]["notes"] = "Authorization: Bearer secret-token-value"
    run_payload["planner"]["prompt"] = "no secret here"

    manifest = build_benchmark_reproducibility_manifest(
        run_payload,
        _report_payload(),
        _export_payload(),
    )
    serialized = json.dumps(manifest, sort_keys=True)

    assert "sk-super-secret" not in serialized
    assert "hunter2" not in serialized
    assert "request-token" not in serialized
    assert "secret-token-value" not in serialized
    assert "api_key" not in serialized
    assert "password" not in serialized
    assert '"token"' not in serialized
    assert manifest["model_runtime"]["model_kwargs"] == {"public_label": "kept"}
    assert manifest["request"]["notes"] == "[REDACTED]"
    assert manifest["redaction"]["redacted_field_count"] >= 4
    assert verify_benchmark_reproducibility_manifest(manifest)["ok"] is True
