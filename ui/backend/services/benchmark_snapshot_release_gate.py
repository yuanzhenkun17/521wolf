"""Benchmark snapshot release gate helpers."""

from __future__ import annotations

from typing import Any

from app.lib.benchmark_release_gate import evaluate_benchmark_release_gate
from ui.backend.errors import domain_error_detail
from ui.backend.schemas import BenchmarkSnapshotRequest
from ui.backend.services.benchmark_payload_utils import (
    first_text as _first_text,
    json_clone as _json_clone,
)


def _benchmark_snapshot_release_gate_error(
    rows: list[dict[str, Any]],
    *,
    scope: str,
    evaluation_set_id: str,
    seed_set_id: Any,
    benchmark_config_hash: Any,
    target_role: str | None,
) -> str | None:
    requested_seed = str(seed_set_id or "").strip()
    requested_hash = str(benchmark_config_hash or "").strip()
    if not requested_seed:
        return "seed_set_id is required for benchmark snapshots"
    if not requested_hash:
        return "benchmark_config_hash is required for benchmark snapshots"

    requested_role = str(target_role or "").strip().lower()
    requested_eval = str(evaluation_set_id or "").strip()
    for row in rows:
        if not isinstance(row, dict):
            return "snapshot rows must be structured objects"
        summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
        row_scope = str(row.get("scope") or summary.get("scope") or "").strip().lower()
        if not row_scope:
            return "snapshot rows must include scope"
        if row_scope != scope:
            return "snapshot boundary mismatch: rows do not match requested scope"
        row_eval = str(row.get("evaluation_set_id") or summary.get("evaluation_set_id") or "").strip()
        if not row_eval or row_eval != requested_eval:
            return "snapshot boundary mismatch: rows do not match requested evaluation_set_id"
        row_seed = str(row.get("seed_set_id") or summary.get("seed_set_id") or "").strip()
        if not row_seed:
            return "snapshot rows must include seed_set_id"
        if row_seed != requested_seed:
            return "snapshot boundary mismatch: rows do not match requested seed_set_id"
        if scope == "role_version":
            row_role = str(row.get("target_role") or summary.get("target_role") or "").strip().lower()
            if not row_role or row_role != requested_role:
                return "snapshot boundary mismatch: rows do not match requested target_role"
        if scope == "model":
            row_model_id = str(row.get("model_id") or summary.get("model_id") or "").strip()
            row_model_hash = str(row.get("model_config_hash") or summary.get("model_config_hash") or "").strip()
            if not row_model_id:
                return "snapshot model rows must include model_id"
            if not row_model_hash:
                return "snapshot model rows must include model_config_hash"
        row_hash = str(
            row.get("benchmark_config_hash")
            or row.get("config_hash")
            or summary.get("benchmark_config_hash")
            or summary.get("config_hash")
            or ""
        ).strip()
        if not row_hash:
            return "snapshot rows must include benchmark_config_hash"
        if row_hash != requested_hash:
            return "snapshot boundary mismatch: rows do not match requested benchmark_config_hash"
        source_run = _first_text(
            row.get("source_run_id"),
            row.get("run_id"),
            row.get("batch_id"),
            summary.get("source_run_id"),
            summary.get("run_id"),
            summary.get("batch_id"),
        )
        result_source = _first_text(
            row.get("result_batch_id"),
            summary.get("result_batch_id"),
        )
        report_source = _first_text(
            row.get("report_id"),
            row.get("source_report_id"),
            summary.get("report_id"),
            summary.get("source_report_id"),
        )
        if not source_run:
            return "snapshot rows must include source_run_id"
        if not report_source:
            return "snapshot rows must include report_id"
        if not result_source:
            return "snapshot rows must include result_batch_id"
    return None


def _benchmark_snapshot_release_gate(
    rows: list[dict[str, Any]],
    *,
    request: BenchmarkSnapshotRequest,
    scope: str,
    evaluation_set_id: str,
    seed_set_id: Any,
    benchmark_config_hash: Any,
    target_role: str | None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config_payload = _json_clone(config or {})
    legacy_error = _benchmark_snapshot_release_gate_error(
        rows,
        scope=scope,
        evaluation_set_id=evaluation_set_id,
        seed_set_id=seed_set_id,
        benchmark_config_hash=benchmark_config_hash,
        target_role=target_role,
    )
    request_payload = {
        "scope": scope,
        "benchmark_id": request.benchmark_id,
        "benchmark_version": request.benchmark_version,
        "evaluation_set_id": evaluation_set_id,
        "seed_set_id": seed_set_id,
        "benchmark_config_hash": benchmark_config_hash,
        "target_role": target_role,
        "source_filter": _json_clone(request.source_filter),
        "view_config": _json_clone(request.view_config),
        "rows": rows,
    }
    gate = evaluate_benchmark_release_gate(
        request=request_payload,
        rows=rows,
        config=config_payload,
    )
    if legacy_error:
        legacy_issue = {
            "code": _benchmark_snapshot_release_gate_legacy_code(legacy_error),
            "severity": "error",
            "message": legacy_error,
            "evidence": {
                "scope": scope,
                "evaluation_set_id": evaluation_set_id,
                "seed_set_id": seed_set_id,
                "benchmark_config_hash": benchmark_config_hash,
                "target_role": target_role,
            },
            "affected_ids": [
                str(value)
                for value in (request.benchmark_id, evaluation_set_id, seed_set_id, target_role)
                if str(value or "").strip()
            ],
        }
        blockers = [legacy_issue, *[dict(item) for item in gate.get("blockers") or [] if isinstance(item, dict)]]
        gate = {
            **gate,
            "ok": False,
            "blockers": blockers,
        }
    summary = dict(gate.get("summary") if isinstance(gate.get("summary"), dict) else {})
    summary.update(
        {
            "blocker_count": len(gate.get("blockers") or []),
            "warning_count": len(gate.get("warnings") or []),
        }
    )
    gate["summary"] = summary
    return _json_clone(gate)


def _benchmark_snapshot_release_gate_legacy_code(message: str) -> str:
    text = str(message or "").lower()
    if "seed_set_id" in text:
        return "seed_set_id_missing_or_mismatch"
    if "benchmark_config_hash" in text or "config_hash" in text:
        return "benchmark_config_hash_missing_or_mismatch"
    if "source_run_id" in text:
        return "source_run_id_missing"
    if "report_id" in text:
        return "report_id_missing"
    if "result_batch_id" in text:
        return "result_batch_id_missing"
    if "model_config_hash" in text:
        return "model_config_hash_missing"
    if "model_id" in text:
        return "model_id_missing"
    if "scope" in text:
        return "scope_missing_or_mismatch"
    if "target_role" in text:
        return "target_role_missing_or_mismatch"
    if "evaluation_set_id" in text:
        return "evaluation_set_id_missing_or_mismatch"
    return "snapshot_release_gate_failed"


def _benchmark_snapshot_release_gate_error_detail(release_gate: dict[str, Any]) -> dict[str, Any]:
    blockers = [dict(item) for item in release_gate.get("blockers") or [] if isinstance(item, dict)]
    warnings = [dict(item) for item in release_gate.get("warnings") or [] if isinstance(item, dict)]
    first_blocker = blockers[0] if blockers else {}
    message = str(first_blocker.get("message") or "benchmark snapshot release gate failed")
    return domain_error_detail(
        code="benchmark_snapshot_release_gate_failed",
        message=message,
        detail=message,
        diagnostics=[
            {
                "kind": "benchmark_snapshot_release_gate_failed",
                "release_gate_ok": bool(release_gate.get("ok")),
                "blockers": blockers,
                "warnings": warnings,
                "summary": _json_clone(release_gate.get("summary") or {}),
            }
        ],
    )
