"""Benchmark snapshot payload, export, and compare helpers."""

from __future__ import annotations

from typing import Any

from app.lib.benchmark_release_gate import evaluate_benchmark_release_gate
from ui.backend.errors import domain_error_detail
from ui.backend.schemas import BenchmarkSnapshotRequest
from ui.backend.services.benchmark_payload_utils import (
    first_text as _first_text,
    json_clone as _json_clone,
)
from ui.backend.services.benchmark_snapshot_common import (
    _benchmark_snapshot_int,
    _default_benchmark_snapshot_title as _default_benchmark_snapshot_title,
    _leaderboard_metric,
    _leaderboard_score,
    _leaderboard_subject_key,
    _stable_json_text,
    _stable_payload_hash as _stable_payload_hash,
    _text_content_hash as _text_content_hash,
)
from ui.backend.services.benchmark_snapshot_exports import (
    _benchmark_snapshot_csv as _benchmark_snapshot_csv,
    _benchmark_snapshot_markdown as _benchmark_snapshot_markdown,
)
from ui.backend.services.benchmark_snapshot_filters import (
    _benchmark_snapshot_source_filter_summary as _benchmark_snapshot_source_filter_summary,
    _filter_benchmark_snapshot_rows as _filter_benchmark_snapshot_rows,
)


def _benchmark_snapshot_source_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    linked_run_ids: set[str] = set()
    linked_report_ids: set[str] = set()
    linked_result_batch_ids: set[str] = set()
    rankable_count = 0

    def add_string(target: set[str], value: Any) -> None:
        text = str(value or "").strip()
        if text:
            target.add(text)

    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("rankable") is not False:
            rankable_count += 1
        for key in ("batch_id", "run_id", "source_run_id"):
            add_string(linked_run_ids, row.get(key))
        for key in ("report_id", "source_report_id"):
            add_string(linked_report_ids, row.get(key))
        add_string(linked_result_batch_ids, row.get("result_batch_id"))

    for run_id in linked_run_ids:
        linked_report_ids.add(f"benchmark_report:{run_id}")

    row_count = len(rows)
    return {
        "row_count": row_count,
        "rankable_count": rankable_count,
        "unrankable_count": row_count - rankable_count,
        "linked_run_ids": sorted(linked_run_ids),
        "linked_report_ids": sorted(linked_report_ids),
        "linked_result_batch_ids": sorted(linked_result_batch_ids),
        "source_run_count": len(linked_run_ids),
        "source_report_count": len(linked_report_ids),
        "source_result_batch_count": len(linked_result_batch_ids),
    }

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

def _benchmark_snapshot_string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item or "").strip()})
    text = str(value or "").strip()
    return [text] if text else []

def _benchmark_snapshot_summary_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    derived = _benchmark_snapshot_source_summary(rows) if rows else {}
    summary = dict(snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {})
    for key in (
        "row_count",
        "rankable_count",
        "unrankable_count",
        "linked_run_ids",
        "linked_report_ids",
        "linked_result_batch_ids",
        "source_run_count",
        "source_report_count",
        "source_result_batch_count",
    ):
        if key not in summary and key in derived:
            summary[key] = _json_clone(derived[key])
    row_count = _benchmark_snapshot_int(snapshot.get("row_count"), summary.get("row_count"), derived.get("row_count"))
    rankable_count = _benchmark_snapshot_int(snapshot.get("rankable_count"), summary.get("rankable_count"), derived.get("rankable_count"))
    unrankable_count = _benchmark_snapshot_int(
        snapshot.get("unrankable_count"),
        summary.get("unrankable_count"),
        derived.get("unrankable_count"),
        default=max(row_count - rankable_count, 0),
    )
    linked_run_ids = _benchmark_snapshot_string_list(
        snapshot.get("linked_run_ids") or summary.get("linked_run_ids") or derived.get("linked_run_ids")
    )
    linked_report_ids = _benchmark_snapshot_string_list(
        snapshot.get("linked_report_ids") or summary.get("linked_report_ids") or derived.get("linked_report_ids")
    )
    linked_result_batch_ids = _benchmark_snapshot_string_list(
        snapshot.get("linked_result_batch_ids")
        or summary.get("linked_result_batch_ids")
        or derived.get("linked_result_batch_ids")
    )
    source_run_count = _benchmark_snapshot_int(
        snapshot.get("source_run_count"),
        summary.get("source_run_count"),
        derived.get("source_run_count"),
        default=len(linked_run_ids),
    )
    source_report_count = _benchmark_snapshot_int(
        snapshot.get("source_report_count"),
        summary.get("source_report_count"),
        derived.get("source_report_count"),
        default=len(linked_report_ids),
    )
    source_result_batch_count = _benchmark_snapshot_int(
        snapshot.get("source_result_batch_count"),
        summary.get("source_result_batch_count"),
        derived.get("source_result_batch_count"),
        default=len(linked_result_batch_ids),
    )
    summary.update(
        {
            "row_count": row_count,
            "rankable_count": rankable_count,
            "unrankable_count": unrankable_count,
            "linked_run_ids": linked_run_ids,
            "linked_report_ids": linked_report_ids,
            "linked_result_batch_ids": linked_result_batch_ids,
            "source_run_count": source_run_count,
            "source_report_count": source_report_count,
            "source_result_batch_count": source_result_batch_count,
        }
    )
    release_gate = snapshot.get("release_gate")
    if not isinstance(release_gate, dict):
        release_gate = summary.get("release_gate") if isinstance(summary.get("release_gate"), dict) else {}
    release_gate = _json_clone(release_gate or {})
    if release_gate:
        gate_summary = release_gate.get("summary") if isinstance(release_gate.get("summary"), dict) else {}
        summary.update(
            {
                "release_gate_ok": bool(release_gate.get("ok")),
                "release_gate_blocker_count": _benchmark_snapshot_int(
                    summary.get("release_gate_blocker_count"),
                    gate_summary.get("blocker_count"),
                    len(release_gate.get("blockers") or []),
                ),
                "release_gate_warning_count": _benchmark_snapshot_int(
                    summary.get("release_gate_warning_count"),
                    gate_summary.get("warning_count"),
                    len(release_gate.get("warnings") or []),
                ),
                "release_gate": release_gate,
            }
        )
    release_manifest = _benchmark_snapshot_release_manifest(snapshot, summary=summary)
    return {
        "kind": "benchmark_leaderboard_snapshot",
        "schema_version": int(snapshot.get("schema_version") or 1),
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "title": str(snapshot.get("title") or ""),
        "release_notes": str(snapshot.get("release_notes") or ""),
        "scope": snapshot.get("scope"),
        "benchmark_id": snapshot.get("benchmark_id"),
        "benchmark_version": snapshot.get("benchmark_version"),
        "evaluation_set_id": snapshot.get("evaluation_set_id"),
        "seed_set_id": snapshot.get("seed_set_id"),
        "benchmark_config_hash": snapshot.get("benchmark_config_hash"),
        "target_role": snapshot.get("target_role"),
        "source_filter": _json_clone(snapshot.get("source_filter") or {}),
        "view_config": _json_clone(snapshot.get("view_config") or {}),
        "summary": _json_clone(summary),
        "row_count": row_count,
        "rankable_count": rankable_count,
        "unrankable_count": unrankable_count,
        "linked_run_ids": linked_run_ids,
        "linked_report_ids": linked_report_ids,
        "linked_result_batch_ids": linked_result_batch_ids,
        "source_run_count": source_run_count,
        "source_report_count": source_report_count,
        "source_result_batch_count": source_result_batch_count,
        "release_gate": release_gate,
        "release_manifest": release_manifest,
        "content_hash": snapshot.get("content_hash"),
        "created_at": snapshot.get("created_at"),
    }

def _benchmark_snapshot_release_manifest(snapshot: dict[str, Any], *, summary: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = str(snapshot.get("snapshot_id") or "")
    linked_run_ids = _benchmark_snapshot_string_list(summary.get("linked_run_ids") or snapshot.get("linked_run_ids"))
    linked_report_ids = _benchmark_snapshot_string_list(summary.get("linked_report_ids") or snapshot.get("linked_report_ids"))
    linked_result_batch_ids = _benchmark_snapshot_string_list(
        summary.get("linked_result_batch_ids") or snapshot.get("linked_result_batch_ids")
    )
    release_gate = summary.get("release_gate") if isinstance(summary.get("release_gate"), dict) else {}
    gate_summary = release_gate.get("summary") if isinstance(release_gate.get("summary"), dict) else {}
    return {
        "schema_version": 1,
        "snapshot_id": snapshot_id,
        "content_hash": snapshot.get("content_hash"),
        "created_at": snapshot.get("created_at"),
        "boundaries": {
            "scope": snapshot.get("scope"),
            "benchmark_id": snapshot.get("benchmark_id"),
            "benchmark_version": snapshot.get("benchmark_version"),
            "evaluation_set_id": snapshot.get("evaluation_set_id"),
            "seed_set_id": snapshot.get("seed_set_id"),
            "benchmark_config_hash": snapshot.get("benchmark_config_hash"),
            "target_role": snapshot.get("target_role"),
        },
        "release_gate": {
            "ok": bool(release_gate.get("ok")) if release_gate else None,
            "blocker_count": _benchmark_snapshot_int(
                summary.get("release_gate_blocker_count"),
                gate_summary.get("blocker_count"),
                len(release_gate.get("blockers") or []),
            ),
            "warning_count": _benchmark_snapshot_int(
                summary.get("release_gate_warning_count"),
                gate_summary.get("warning_count"),
                len(release_gate.get("warnings") or []),
            ),
            "thresholds": _json_clone(gate_summary.get("thresholds") or {}),
            "suite_lifecycle": _json_clone(gate_summary.get("suite_lifecycle") or {}),
            "diagnostics": _json_clone(gate_summary.get("diagnostics") or {}),
        },
        "source": {
            "row_count": summary.get("row_count", 0),
            "rankable_count": summary.get("rankable_count", 0),
            "unrankable_count": summary.get("unrankable_count", 0),
            "source_filter_applied": _json_clone(summary.get("source_filter_applied") or {}),
            "linked_run_ids": linked_run_ids,
            "linked_report_ids": linked_report_ids,
            "linked_result_batch_ids": linked_result_batch_ids,
        },
        "artifacts": {
            "snapshot": f"/api/benchmark/snapshots/{snapshot_id}",
            "exports": {
                "json": f"/api/benchmark/snapshots/{snapshot_id}/export?format=json",
                "markdown": f"/api/benchmark/snapshots/{snapshot_id}/export?format=markdown",
                "csv": f"/api/benchmark/snapshots/{snapshot_id}/export?format=csv",
            },
            "reports": linked_report_ids,
            "runs": linked_run_ids,
            "result_batches": linked_result_batch_ids,
        },
    }

def _benchmark_snapshot_detail_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _benchmark_snapshot_summary_payload(snapshot)
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    payload["rows"] = _json_clone(rows)
    return payload

def _benchmark_snapshot_compare_payload(
    snapshot: dict[str, Any],
    current_rows: list[dict[str, Any]],
    frozen_rows: list[dict[str, Any]],
    *,
    scope: str,
    evaluation_set_id: str | None,
    target_role: str | None,
    compare_mode: str = "current_vs_snapshot",
    against_snapshot: dict[str, Any] | None = None,
    initial_boundary_warnings: list[str] | None = None,
) -> dict[str, Any]:
    current_by_key = _benchmark_snapshot_row_map(current_rows)
    frozen_by_key = _benchmark_snapshot_row_map(frozen_rows)
    changed: list[dict[str, Any]] = []
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    boundary_warnings: set[str] = set(initial_boundary_warnings or [])

    for key, current in current_by_key.items():
        frozen = frozen_by_key.get(key)
        if frozen is None:
            row = _benchmark_snapshot_member_row(current, key, snapshot, scope=scope, target_role=target_role)
            added.append(row)
            boundary_warnings.update(row.get("boundary_warnings") or [])
            continue
        row = _benchmark_snapshot_changed_row(current, frozen, key, snapshot, scope=scope, target_role=target_role)
        boundary_warnings.update(row.get("boundary_warnings") or [])
        if _benchmark_snapshot_row_changed(row):
            changed.append(row)

    for key, frozen in frozen_by_key.items():
        if key in current_by_key:
            continue
        row = _benchmark_snapshot_member_row(frozen, key, snapshot, scope=scope, target_role=target_role)
        removed.append(row)
        boundary_warnings.update(row.get("boundary_warnings") or [])

    changed.sort(
        key=lambda row: (
            abs(float(row.get("score_delta") or 0)),
            abs(float(row.get("win_rate_delta") or 0)),
            str(row.get("key") or ""),
        ),
        reverse=True,
    )
    added.sort(key=lambda row: (-_leaderboard_score(row, scope=scope), str(row.get("key") or "")))
    removed.sort(key=lambda row: (-_leaderboard_score(row, scope=scope), str(row.get("key") or "")))
    if not current_rows:
        boundary_warnings.add("empty_current_leaderboard")
    summary = {
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "compare_mode": compare_mode,
        "scope": scope,
        "evaluation_set_id": evaluation_set_id,
        "target_role": target_role,
        "current_row_count": len(current_rows),
        "snapshot_row_count": len(frozen_rows),
        "changed_count": len(changed),
        "added_count": len(added),
        "removed_count": len(removed),
        "boundary_warning_count": len(boundary_warnings),
        "rankable_current_count": sum(1 for row in current_rows if row.get("rankable") is not False),
        "rankable_snapshot_count": sum(1 for row in frozen_rows if row.get("rankable") is not False),
    }
    if against_snapshot is not None:
        summary["against_snapshot_id"] = str(against_snapshot.get("snapshot_id") or "")
    return {
        "kind": "benchmark_snapshot_compare",
        "schema_version": 1,
        "compare_mode": compare_mode,
        "snapshot": _benchmark_snapshot_summary_payload(snapshot),
        **({"against_snapshot": _benchmark_snapshot_summary_payload(against_snapshot)} if against_snapshot is not None else {}),
        "current": {
            "scope": scope,
            "evaluation_set_id": evaluation_set_id,
            "target_role": target_role,
            **({"snapshot_id": str(against_snapshot.get("snapshot_id") or "")} if against_snapshot is not None else {}),
            "row_count": len(current_rows),
            "rows": [_benchmark_snapshot_member_row(row, _benchmark_snapshot_row_key(row), snapshot, scope=scope, target_role=target_role) for row in current_rows],
        },
        "frozen": {
            "row_count": len(frozen_rows),
            "rows": [_benchmark_snapshot_member_row(row, _benchmark_snapshot_row_key(row), snapshot, scope=scope, target_role=target_role) for row in frozen_rows],
        },
        "summary": summary,
        "changed": changed,
        "added": added,
        "removed": removed,
        "boundary_warnings": sorted(boundary_warnings),
    }

def _benchmark_snapshot_row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    mapped: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        key = _benchmark_snapshot_row_key(row) or f"row-{index}"
        if key not in mapped:
            mapped[key] = row
    return mapped

def _benchmark_snapshot_row_key(row: dict[str, Any] | None) -> str:
    return _leaderboard_subject_key(row)

def _benchmark_snapshot_member_row(
    row: dict[str, Any],
    key: str,
    snapshot: dict[str, Any],
    *,
    scope: str,
    target_role: str | None,
) -> dict[str, Any]:
    payload = dict(row)
    payload["key"] = key or _benchmark_snapshot_row_key(row)
    payload["boundary_warnings"] = _benchmark_snapshot_boundary_warnings(
        row,
        snapshot,
        scope=scope,
        target_role=target_role,
    )
    return payload

def _benchmark_snapshot_changed_row(
    current: dict[str, Any],
    frozen: dict[str, Any],
    key: str,
    snapshot: dict[str, Any],
    *,
    scope: str,
    target_role: str | None,
) -> dict[str, Any]:
    score_delta = _leaderboard_score(current, scope=scope) - _leaderboard_score(frozen, scope=scope)
    win_rate_delta = _leaderboard_metric(current, "target_side_win_rate") - _leaderboard_metric(frozen, "target_side_win_rate")
    games_delta = int(_leaderboard_metric(current, "games_played", "game_count", "total_games")) - int(
        _leaderboard_metric(frozen, "games_played", "game_count", "total_games")
    )
    rankable_changed = (current.get("rankable") is not False) != (frozen.get("rankable") is not False)
    boundary_warnings = _benchmark_snapshot_boundary_warnings(current, snapshot, scope=scope, target_role=target_role)
    if boundary_warnings:
        change = "incomparable"
    elif score_delta > 0:
        change = "improvement"
    elif score_delta < 0:
        change = "regression"
    elif win_rate_delta or games_delta or rankable_changed:
        change = "changed"
    else:
        change = "stable"
    return {
        "key": key,
        "current": _benchmark_snapshot_member_row(current, key, snapshot, scope=scope, target_role=target_role),
        "snapshot": _benchmark_snapshot_member_row(frozen, key, snapshot, scope=scope, target_role=target_role),
        "score_delta": score_delta,
        "scoreDelta": score_delta,
        "win_rate_delta": win_rate_delta,
        "winRateDelta": win_rate_delta,
        "games_delta": games_delta,
        "gamesDelta": games_delta,
        "rankable_changed": rankable_changed,
        "rankableChanged": rankable_changed,
        "boundary_warnings": boundary_warnings,
        "change": change,
    }

def _benchmark_snapshot_row_changed(row: dict[str, Any]) -> bool:
    return (
        abs(float(row.get("score_delta") or 0)) > 0.000001
        or abs(float(row.get("win_rate_delta") or 0)) > 0.000001
        or int(row.get("games_delta") or 0) != 0
        or bool(row.get("rankable_changed"))
        or bool(row.get("boundary_warnings"))
    )

def _benchmark_snapshot_pair_boundary_warnings(
    snapshot: dict[str, Any],
    against_snapshot: dict[str, Any],
    *,
    scope: str,
    target_role: str | None,
) -> list[str]:
    warnings: list[str] = []
    against_scope = str(against_snapshot.get("scope") or "").strip().lower()
    if against_scope and against_scope != scope:
        warnings.append("scope_mismatch")
    for key, warning in [
        ("evaluation_set_id", "evaluation_set_mismatch"),
        ("seed_set_id", "seed_set_mismatch"),
        ("benchmark_config_hash", "benchmark_config_hash_mismatch"),
        ("benchmark_id", "benchmark_id_mismatch"),
    ]:
        left = str(snapshot.get(key) or "").strip()
        right = str(against_snapshot.get(key) or "").strip()
        if left and right and left != right:
            warnings.append(warning)
    against_role = str(against_snapshot.get("target_role") or "").strip().lower()
    if scope == "role_version" and target_role and against_role and against_role != target_role:
        warnings.append("target_role_mismatch")
    if _stable_json_text(snapshot.get("source_filter") or {}) != _stable_json_text(against_snapshot.get("source_filter") or {}):
        warnings.append("source_filter_mismatch")
    return sorted(set(warnings))

def _benchmark_snapshot_boundary_warnings(
    row: dict[str, Any],
    snapshot: dict[str, Any],
    *,
    scope: str,
    target_role: str | None,
) -> list[str]:
    warnings: list[str] = []
    row_scope = str(row.get("scope") or "").strip().lower()
    if row_scope and row_scope != scope:
        warnings.append("scope_mismatch")
    row_eval = str(row.get("evaluation_set_id") or "").strip()
    snapshot_eval = str(snapshot.get("evaluation_set_id") or "").strip()
    if row_eval and snapshot_eval and row_eval != snapshot_eval:
        warnings.append("evaluation_set_mismatch")
    row_seed = str(row.get("seed_set_id") or "").strip()
    snapshot_seed = str(snapshot.get("seed_set_id") or "").strip()
    if row_seed and snapshot_seed and row_seed != snapshot_seed:
        warnings.append("seed_set_mismatch")
    row_hash = str(row.get("benchmark_config_hash") or row.get("config_hash") or "").strip()
    snapshot_hash = str(snapshot.get("benchmark_config_hash") or "").strip()
    if row_hash and snapshot_hash and row_hash != snapshot_hash:
        warnings.append("benchmark_config_hash_mismatch")
    row_role = str(row.get("target_role") or "").strip().lower()
    if scope == "role_version" and target_role and row_role and row_role != target_role:
        warnings.append("target_role_mismatch")
    return warnings

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
