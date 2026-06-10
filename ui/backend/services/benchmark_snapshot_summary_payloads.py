"""Benchmark snapshot summary and detail payload helpers."""

from __future__ import annotations

from typing import Any

from ui.backend.services.benchmark_payload_utils import json_clone as _json_clone
from ui.backend.services.benchmark_snapshot_common import _benchmark_snapshot_int


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


def _benchmark_snapshot_string_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return sorted({str(item).strip() for item in value if str(item or "").strip()})
    text = str(value or "").strip()
    return [text] if text else []
