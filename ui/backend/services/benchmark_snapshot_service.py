"""Benchmark snapshot, saved-view, and export service helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import uuid

from typing import Any, Protocol

from fastapi import HTTPException

from app.lib.benchmark_release_gate import evaluate_benchmark_release_gate
from app.util.time import beijing_now_iso
from storage.benchmark.saved_view_repo import (
    BenchmarkSavedViewRepository,
    delete_benchmark_saved_view,
    persist_benchmark_saved_view,
)
from storage.benchmark.snapshot_repo import (
    BenchmarkSnapshotRepository,
    persist_benchmark_snapshot,
)
from ui.backend.errors import domain_error_detail
from ui.backend.schemas import BenchmarkSnapshotRequest, BenchmarkViewRequest

_log = logging.getLogger(__name__)


class BenchmarkSnapshotServiceContextProtocol(Protocol):
    """Context capabilities required by ``BenchmarkSnapshotService``."""

    paths: object
    benchmark_leaderboard_snapshots: dict[str, dict[str, Any]]
    benchmark_saved_views: dict[str, dict[str, Any]]

    def leaderboard_entries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        ...

    def get_benchmark_spec_summary(self, benchmark_id: str) -> dict[str, Any]:
        ...

class BenchmarkSnapshotService:
    """Facade and persistence helper for benchmark release artifacts."""

    def __init__(self, context: BenchmarkSnapshotServiceContextProtocol) -> None:
        self._context = context

    def _open_connection(self) -> Any:
        from app.lib.score import open_eval_connection

        return open_eval_connection(getattr(self._context, "paths", None))

    def persist_benchmark_snapshot(self, snapshot: dict[str, Any]) -> None:
        persist_benchmark_snapshot(self._open_connection, snapshot)

    def load_benchmark_snapshot_summaries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkSnapshotRepository(conn).list(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark leaderboard snapshots failed", exc_info=True)
            rows = [
                _benchmark_snapshot_summary_payload(snapshot)
                for snapshot in getattr(self._context, "benchmark_leaderboard_snapshots", {}).values()
            ]
            return _filter_benchmark_snapshot_cache(
                rows,
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                limit=limit,
            )
        finally:
            if conn is not None:
                conn.close()

    def load_benchmark_snapshot_detail(self, snapshot_id: str) -> dict[str, Any] | None:
        conn = None
        try:
            conn = self._open_connection()
            snapshot = BenchmarkSnapshotRepository(conn).get(snapshot_id)
            if snapshot is None:
                return getattr(self._context, "benchmark_leaderboard_snapshots", {}).get(snapshot_id)
            return snapshot
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark leaderboard snapshot detail failed", exc_info=True)
            return getattr(self._context, "benchmark_leaderboard_snapshots", {}).get(snapshot_id)
        finally:
            if conn is not None:
                conn.close()

    def persist_benchmark_saved_view(self, view: dict[str, Any]) -> None:
        persist_benchmark_saved_view(self._open_connection, view)

    def load_benchmark_saved_views(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        conn = None
        try:
            conn = self._open_connection()
            return BenchmarkSavedViewRepository(conn).list(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                view_key=view_key,
                limit=limit,
            )
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark saved views failed", exc_info=True)
            rows = [
                _benchmark_view_payload(view)
                for view in getattr(self._context, "benchmark_saved_views", {}).values()
            ]
            return _filter_benchmark_view_cache(
                rows,
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                view_key=view_key,
                limit=limit,
            )
        finally:
            if conn is not None:
                conn.close()

    def delete_benchmark_saved_view(self, view_key: str) -> bool:
        return delete_benchmark_saved_view(self._open_connection, view_key)

    def create_benchmark_snapshot(self, request: BenchmarkSnapshotRequest) -> dict[str, Any]:
        """Freeze the current leaderboard rows into an immutable release snapshot."""
        scope = str(request.scope or "").strip().lower()
        if scope not in {"role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported benchmark snapshot scope")
        evaluation_set_id = str(request.evaluation_set_id or "").strip()
        if not evaluation_set_id:
            raise HTTPException(status_code=422, detail="evaluation_set_id is required")
        target_role = str(request.target_role or "").strip().lower() or None
        if scope == "role_version" and not target_role:
            raise HTTPException(status_code=422, detail="target_role is required for role_version snapshots")

        rows = self._context.leaderboard_entries(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role if scope == "role_version" else None,
            limit=request.limit,
        )
        rows = _filter_benchmark_snapshot_rows(rows, request.source_filter)
        if not rows:
            raise HTTPException(status_code=422, detail="cannot snapshot empty leaderboard")

        now = beijing_now_iso()
        frozen_rows = [_json_clone(row) for row in rows]
        release_gate = _benchmark_snapshot_release_gate(
            frozen_rows,
            request=request,
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            seed_set_id=request.seed_set_id,
            benchmark_config_hash=request.benchmark_config_hash,
            target_role=target_role,
            config=self._benchmark_snapshot_release_gate_config(request),
        )
        if not release_gate.get("ok"):
            raise HTTPException(status_code=422, detail=_benchmark_snapshot_release_gate_error_detail(release_gate))
        rankable_count = sum(1 for row in frozen_rows if row.get("rankable") is not False)
        summary = {
            "row_count": len(frozen_rows),
            "rankable_count": rankable_count,
            "unrankable_count": len(frozen_rows) - rankable_count,
            "scope": scope,
            "evaluation_set_id": evaluation_set_id,
            "target_role": target_role,
            "source_filter_applied": _benchmark_snapshot_source_filter_summary(request.source_filter),
            "release_gate_ok": bool(release_gate.get("ok")),
            "release_gate_blocker_count": len(release_gate.get("blockers") or []),
            "release_gate_warning_count": len(release_gate.get("warnings") or []),
            "release_gate": _json_clone(release_gate),
        }
        source_summary = _benchmark_snapshot_source_summary(frozen_rows)
        summary.update(source_summary)
        content_payload = {
            "scope": scope,
            "benchmark_id": request.benchmark_id,
            "benchmark_version": request.benchmark_version,
            "evaluation_set_id": evaluation_set_id,
            "seed_set_id": request.seed_set_id,
            "benchmark_config_hash": request.benchmark_config_hash,
            "target_role": target_role,
            "source_filter": request.source_filter,
            "view_config": request.view_config,
            "rows": frozen_rows,
            "summary": summary,
            "release_gate": release_gate,
            **source_summary,
        }
        content_hash = _stable_payload_hash(content_payload)
        snapshot_id = f"bench_snap_{uuid.uuid4().hex[:10]}"
        snapshot = {
            "kind": "benchmark_leaderboard_snapshot",
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "title": str(request.title or "").strip() or _default_benchmark_snapshot_title(scope, evaluation_set_id, target_role),
            "release_notes": str(request.release_notes or ""),
            "scope": scope,
            "benchmark_id": request.benchmark_id,
            "benchmark_version": request.benchmark_version,
            "evaluation_set_id": evaluation_set_id,
            "seed_set_id": request.seed_set_id,
            "benchmark_config_hash": request.benchmark_config_hash,
            "target_role": target_role,
            "source_filter": _json_clone(request.source_filter),
            "view_config": _json_clone(request.view_config),
            "rows": frozen_rows,
            "summary": summary,
            "release_gate": release_gate,
            "row_count": len(frozen_rows),
            **source_summary,
            "content_hash": content_hash,
            "created_at": now,
        }
        self._context.benchmark_leaderboard_snapshots[snapshot_id] = _json_clone(snapshot)
        try:
            self.persist_benchmark_snapshot(snapshot)
        except Exception:  # noqa: BLE001 - keep API usable if snapshot persistence is temporarily unavailable
            _log.warning("persist benchmark leaderboard snapshot failed", exc_info=True)
        return _benchmark_snapshot_detail_payload(snapshot)

    def _benchmark_snapshot_release_gate_config(self, request: BenchmarkSnapshotRequest) -> dict[str, Any]:
        benchmark_id = str(request.benchmark_id or "").strip()
        if not benchmark_id:
            return {"thresholds": {"require_suite_lifecycle": False}}
        try:
            summary = self._context.get_benchmark_spec_summary(benchmark_id)
        except HTTPException:
            return {
                "benchmark_id": benchmark_id,
                "benchmark_config_hash": request.benchmark_config_hash,
                "thresholds": {"require_suite_lifecycle": False},
            }
        return {
            **summary,
            "suite": _json_clone(summary),
            "benchmark_id": benchmark_id,
            "benchmark_config_hash": request.benchmark_config_hash or summary.get("config_hash"),
        }

    def list_benchmark_snapshots(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return benchmark leaderboard snapshot summaries without frozen rows."""
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope and normalized_scope not in {"role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported benchmark snapshot scope")
        normalized_target_role = str(target_role or "").strip().lower()
        snapshots = self._load_benchmark_snapshot_summaries(
            scope=normalized_scope or None,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=normalized_target_role or None,
            limit=limit,
        )
        return {
            "kind": "benchmark_leaderboard_snapshots",
            "schema_version": 1,
            "scope": normalized_scope or None,
            "evaluation_set_id": evaluation_set_id,
            "benchmark_id": benchmark_id,
            "target_role": normalized_target_role or None,
            "items": snapshots,
        }

    def get_benchmark_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Return one frozen benchmark leaderboard snapshot with copied rows."""
        normalized_id = str(snapshot_id or "").strip()
        if not normalized_id:
            raise HTTPException(status_code=404, detail="benchmark snapshot not found")
        snapshot = self._load_benchmark_snapshot_detail(normalized_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="benchmark snapshot not found")
        return _benchmark_snapshot_detail_payload(snapshot)

    def benchmark_snapshot_export(self, snapshot_id: str, *, format: str = "json") -> dict[str, Any]:
        """Return an immutable snapshot export payload for release/audit workflows."""
        snapshot = self.get_benchmark_snapshot(snapshot_id)
        normalized_format = str(format or "json").strip().lower()
        if normalized_format == "json":
            content = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True)
        elif normalized_format == "markdown":
            content = _benchmark_snapshot_markdown(snapshot)
        elif normalized_format == "csv":
            content = _benchmark_snapshot_csv(snapshot)
        else:
            raise HTTPException(status_code=422, detail="unsupported benchmark snapshot export format")
        export_content_hash = _text_content_hash(content)
        return {
            "kind": "benchmark_leaderboard_snapshot_export",
            "schema_version": 1,
            "snapshot_id": snapshot["snapshot_id"],
            "format": normalized_format,
            "content": content,
            "content_hash": snapshot.get("content_hash"),
            "export_content_hash": export_content_hash,
            "artifact_hash": export_content_hash,
            "release_gate": _json_clone(snapshot.get("release_gate") or {}),
            "release_manifest": _json_clone(snapshot.get("release_manifest") or {}),
            "snapshot": snapshot,
        }

    def benchmark_snapshot_compare(
        self,
        snapshot_id: str,
        *,
        against_snapshot_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Compare the current leaderboard or another frozen release snapshot against one snapshot."""
        normalized_id = str(snapshot_id or "").strip()
        if not normalized_id:
            raise HTTPException(status_code=404, detail="benchmark snapshot not found")
        snapshot = self._load_benchmark_snapshot_detail(normalized_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="benchmark snapshot not found")
        scope = str(snapshot.get("scope") or "").strip().lower() or "role_version"
        if scope not in {"role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported benchmark snapshot scope")
        evaluation_set_id = str(snapshot.get("evaluation_set_id") or "").strip() or None
        target_role = str(snapshot.get("target_role") or "").strip().lower() or None
        frozen_rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
        normalized_against_id = str(against_snapshot_id or "").strip()
        against_snapshot: dict[str, Any] | None = None
        if normalized_against_id:
            against_snapshot = self._load_benchmark_snapshot_detail(normalized_against_id)
            if against_snapshot is None:
                raise HTTPException(status_code=404, detail="benchmark snapshot not found")
            current_rows = against_snapshot.get("rows") if isinstance(against_snapshot.get("rows"), list) else []
            current_rows = current_rows[:limit]
            compare_mode = "snapshot_to_snapshot"
            initial_warnings = _benchmark_snapshot_pair_boundary_warnings(
                snapshot,
                against_snapshot,
                scope=scope,
                target_role=target_role,
            )
        else:
            current_rows = self._context.leaderboard_entries(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                target_role=target_role if scope == "role_version" else None,
                limit=limit,
            )
            current_rows = _filter_benchmark_snapshot_rows(current_rows, snapshot.get("source_filter"))
            compare_mode = "current_vs_snapshot"
            initial_warnings = []
        compare = _benchmark_snapshot_compare_payload(
            snapshot,
            current_rows,
            frozen_rows,
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            compare_mode=compare_mode,
            against_snapshot=against_snapshot,
            initial_boundary_warnings=initial_warnings,
        )
        return compare

    def save_benchmark_view(self, request: BenchmarkViewRequest) -> dict[str, Any]:
        """Persist a reusable benchmark leaderboard/table view."""
        view_key = str(request.view_key or "").strip()
        if not view_key:
            raise HTTPException(status_code=422, detail="view_key is required")
        now = beijing_now_iso()
        existing = self._context.benchmark_saved_views.get(view_key) or {}
        created_at = existing.get("created_at") or now
        view = {
            "kind": "benchmark_saved_view",
            "schema_version": 1,
            "view_key": view_key,
            "name": str(request.name or "").strip() or "Default view",
            "scope": request.scope,
            "benchmark_id": request.benchmark_id,
            "evaluation_set_id": request.evaluation_set_id,
            "target_role": request.target_role,
            "view_config": _json_clone(request.view_config),
            "created_at": created_at,
            "updated_at": now,
        }
        self._context.benchmark_saved_views[view_key] = _json_clone(view)
        try:
            self.persist_benchmark_saved_view(view)
        except Exception:  # noqa: BLE001 - saved views remain usable in memory
            _log.warning("persist benchmark saved view failed", exc_info=True)
        return _benchmark_view_payload(view)

    def list_benchmark_views(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return saved benchmark table/filter views."""
        normalized_scope = str(scope or "").strip().lower()
        if normalized_scope and normalized_scope not in {"role_version", "model"}:
            raise HTTPException(status_code=422, detail="unsupported benchmark view scope")
        normalized_target_role = str(target_role or "").strip().lower()
        rows = self._load_benchmark_saved_views(
            scope=normalized_scope or None,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=normalized_target_role or None,
            view_key=view_key,
            limit=limit,
        )
        return {
            "kind": "benchmark_saved_views",
            "schema_version": 1,
            "scope": normalized_scope or None,
            "evaluation_set_id": evaluation_set_id,
            "benchmark_id": benchmark_id,
            "target_role": normalized_target_role or None,
            "items": rows,
        }

    def get_benchmark_view(self, view_key: str) -> dict[str, Any]:
        """Return one saved benchmark view."""
        normalized_key = str(view_key or "").strip()
        if not normalized_key:
            raise HTTPException(status_code=404, detail="benchmark view not found")
        rows = self._load_benchmark_saved_views(view_key=normalized_key, limit=1)
        if not rows:
            raise HTTPException(status_code=404, detail="benchmark view not found")
        return rows[0]

    def delete_benchmark_view(self, view_key: str) -> dict[str, Any]:
        """Delete a saved benchmark view."""
        normalized_key = str(view_key or "").strip()
        if not normalized_key:
            raise HTTPException(status_code=404, detail="benchmark view not found")
        existed = normalized_key in self._context.benchmark_saved_views
        self._context.benchmark_saved_views.pop(normalized_key, None)
        try:
            existed = self.delete_benchmark_saved_view(normalized_key) or existed
        except Exception:  # noqa: BLE001 - cache delete still applies
            _log.warning("delete benchmark saved view failed", exc_info=True)
        if not existed:
            raise HTTPException(status_code=404, detail="benchmark view not found")
        return {
            "kind": "benchmark_saved_view_deleted",
            "schema_version": 1,
            "view_key": normalized_key,
            "deleted": True,
        }

    def _persist_benchmark_leaderboard_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.persist_benchmark_snapshot(snapshot)

    def _load_benchmark_snapshot_summaries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            snapshots = self.load_benchmark_snapshot_summaries(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                limit=limit,
            )
            rows = [_benchmark_snapshot_summary_payload(snapshot) for snapshot in snapshots]
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark leaderboard snapshots failed", exc_info=True)
            rows = [
                _benchmark_snapshot_summary_payload(snapshot)
                for snapshot in self._context.benchmark_leaderboard_snapshots.values()
            ]
            rows = _filter_benchmark_snapshot_cache(
                rows,
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                limit=limit,
            )
        return rows

    def _load_benchmark_snapshot_detail(self, snapshot_id: str) -> dict[str, Any] | None:
        try:
            snapshot = self.load_benchmark_snapshot_detail(snapshot_id)
            if snapshot is None:
                return self._context.benchmark_leaderboard_snapshots.get(snapshot_id)
            return snapshot
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark leaderboard snapshot detail failed", exc_info=True)
            return self._context.benchmark_leaderboard_snapshots.get(snapshot_id)

    def _persist_benchmark_saved_view(self, view: dict[str, Any]) -> None:
        self.persist_benchmark_saved_view(view)

    def _load_benchmark_saved_views(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        view_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        try:
            views = self.load_benchmark_saved_views(
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                view_key=view_key,
                limit=limit,
            )
            rows = [_benchmark_view_payload(view) for view in views]
        except Exception:  # noqa: BLE001 - fallback to process cache when storage is unavailable
            _log.warning("load benchmark saved views failed", exc_info=True)
            rows = [
                _benchmark_view_payload(view)
                for view in self._context.benchmark_saved_views.values()
            ]
            rows = _filter_benchmark_view_cache(
                rows,
                scope=scope,
                evaluation_set_id=evaluation_set_id,
                benchmark_id=benchmark_id,
                target_role=target_role,
                view_key=view_key,
                limit=limit,
            )
        return rows

    def _delete_benchmark_saved_view(self, view_key: str) -> bool:
        return self.delete_benchmark_saved_view(view_key)

def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _leaderboard_subject_key(row: dict[str, Any] | None) -> str:
    if not row:
        return ""
    for key in ("subject_id", "hash", "model_config_hash", "target_version_id", "model_id"):
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return ""

def _first_int(*values: Any, default: int = 0) -> int:
    for value in values:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            continue
        return number
    return default

def _first_float(*values: Any, default: float = 0.0) -> float:
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if number == number:
            return number
    return default

def _leaderboard_metric(row: dict[str, Any] | None, *keys: str) -> float:
    if not row:
        return 0.0
    for key in keys:
        try:
            value = float(row.get(key))
        except (TypeError, ValueError):
            continue
        if value == value:
            return value
    return 0.0

def _leaderboard_score(row: dict[str, Any] | None, *, scope: str | None) -> float:
    if scope == "model":
        return _leaderboard_metric(row, "strength_score", "avg_role_score", "target_role_role_weighted_score")
    return _leaderboard_metric(row, "avg_role_score", "target_role_role_weighted_score", "strength_score")

def _stable_payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

def _default_benchmark_snapshot_title(scope: str, evaluation_set_id: str, target_role: str | None) -> str:
    subject = "model" if scope == "model" else (target_role or "role-version")
    return f"{evaluation_set_id} / {subject}"

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

def _stable_json_text(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)

def _markdown_value(value: Any) -> str:
    return str(value if value is not None else "--").replace("\n", " ").replace("|", "\\|")

def _csv_value(value: Any) -> str:
    text = str(value if value is not None else "")
    if any(char in text for char in [",", "\"", "\n", "\r"]):
        return '"' + text.replace('"', '""') + '"'
    return text

def _text_content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"

def _benchmark_snapshot_filter_values(value: Any) -> set[str] | None:
    if value in (None, "", [], (), set()):
        return None
    if isinstance(value, (list, tuple, set)):
        values = {str(item).strip().lower() for item in value if str(item or "").strip()}
        return values or None
    text = str(value or "").strip()
    if not text:
        return None
    return {part.strip().lower() for part in text.split(",") if part.strip()} or None

def _benchmark_snapshot_row_field(row: dict[str, Any], key: str) -> Any:
    summary = row.get("summary") if isinstance(row.get("summary"), dict) else {}
    aliases = {
        "source_run_id": ("source_run_id", "run_id", "batch_id"),
        "batch_id": ("batch_id", "source_run_id", "run_id"),
        "report_id": ("report_id", "source_report_id"),
        "source_report_id": ("source_report_id", "report_id"),
        "result_batch_id": ("result_batch_id",),
        "subject_id": ("subject_id", "hash", "model_config_hash", "model_id", "target_version_id"),
    }
    for candidate in aliases.get(key, (key,)):
        value = row.get(candidate)
        if value not in (None, ""):
            return value
        value = summary.get(candidate)
        if value not in (None, ""):
            return value
    return None

def _benchmark_snapshot_rankable_matches(row: dict[str, Any], allowed: set[str] | None) -> bool:
    if not allowed or allowed & {"all", "any", "*"}:
        return True
    is_rankable = row.get("rankable") is not False
    if allowed & {"rankable", "true", "1", "yes"}:
        return is_rankable
    if allowed & {"unrankable", "false", "0", "no"}:
        return not is_rankable
    return True

def _benchmark_snapshot_row_matches_source_filter(row: dict[str, Any], source_filter: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    for raw_key, raw_value in source_filter.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        allowed = _benchmark_snapshot_filter_values(raw_value)
        if allowed is None:
            continue
        if key == "rankable":
            if not _benchmark_snapshot_rankable_matches(row, allowed):
                return False
            continue
        value = _benchmark_snapshot_row_field(row, key)
        if str(value or "").strip().lower() not in allowed:
            return False
    return True

def _filter_benchmark_snapshot_rows(rows: list[dict[str, Any]], source_filter: Any) -> list[dict[str, Any]]:
    if not isinstance(source_filter, dict) or not source_filter:
        return rows
    return [row for row in rows if _benchmark_snapshot_row_matches_source_filter(row, source_filter)]

def _benchmark_snapshot_source_filter_summary(source_filter: Any) -> dict[str, Any]:
    if not isinstance(source_filter, dict):
        return {}
    return {
        key: _json_clone(value)
        for key, value in source_filter.items()
        if str(key or "").strip() and value not in (None, "", [], (), set())
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

def _benchmark_snapshot_int(*values: Any, default: int = 0) -> int:
    for value in values:
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return default

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

def _benchmark_snapshot_release_gate_export_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    release_gate = snapshot.get("release_gate") if isinstance(snapshot.get("release_gate"), dict) else {}
    if not release_gate and isinstance(summary.get("release_gate"), dict):
        release_gate = summary["release_gate"]
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    manifest_gate = manifest.get("release_gate") if isinstance(manifest.get("release_gate"), dict) else {}
    gate_summary = release_gate.get("summary") if isinstance(release_gate.get("summary"), dict) else {}
    ok_value = release_gate.get("ok")
    if not isinstance(ok_value, bool):
        ok_value = manifest_gate.get("ok") if isinstance(manifest_gate.get("ok"), bool) else None
    blocker_count = _benchmark_snapshot_int(
        summary.get("release_gate_blocker_count"),
        gate_summary.get("blocker_count"),
        manifest_gate.get("blocker_count"),
        len(release_gate.get("blockers") or []),
    )
    warning_count = _benchmark_snapshot_int(
        summary.get("release_gate_warning_count"),
        gate_summary.get("warning_count"),
        manifest_gate.get("warning_count"),
        len(release_gate.get("warnings") or []),
    )
    return {
        "ok": ok_value,
        "label": "通过" if ok_value is True else ("阻断" if ok_value is False else "未上报"),
        "blocker_count": blocker_count,
        "warning_count": warning_count,
        "thresholds": _json_clone(gate_summary.get("thresholds") or manifest_gate.get("thresholds") or {}),
        "suite_lifecycle": _json_clone(
            gate_summary.get("suite_lifecycle") or manifest_gate.get("suite_lifecycle") or {}
        ),
    }

def _benchmark_snapshot_detail_payload(snapshot: dict[str, Any]) -> dict[str, Any]:
    payload = _benchmark_snapshot_summary_payload(snapshot)
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    payload["rows"] = _json_clone(rows)
    return payload

def _benchmark_snapshot_markdown(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    release_gate = _benchmark_snapshot_release_gate_export_summary(snapshot)
    thresholds = release_gate["thresholds"]
    lifecycle = release_gate["suite_lifecycle"]
    rows = snapshot.get("rows") if isinstance(snapshot.get("rows"), list) else []
    lines = [
        f"# 榜单快照：{_markdown_value(snapshot.get('title'))}",
        "",
        "## 快照头",
        f"- 快照 ID: {_markdown_value(snapshot.get('snapshot_id'))}",
        f"- 范围: {_markdown_value(snapshot.get('scope'))}",
        f"- 套件: {_markdown_value(snapshot.get('benchmark_id'))} v{_markdown_value(snapshot.get('benchmark_version'))}",
        f"- 评测集: {_markdown_value(snapshot.get('evaluation_set_id'))}",
        f"- 种子集: {_markdown_value(snapshot.get('seed_set_id'))}",
        f"- Config Hash: {_markdown_value(snapshot.get('benchmark_config_hash'))}",
        f"- 目标角色: {_markdown_value(snapshot.get('target_role'))}",
        f"- 内容 Hash: {_markdown_value(snapshot.get('content_hash'))}",
        f"- 创建时间: {_markdown_value(snapshot.get('created_at'))}",
        f"- 发布门禁: {release_gate['label']} / 阻断 {release_gate['blocker_count']} / 警告 {release_gate['warning_count']}",
        f"- 套件状态: {_markdown_value(lifecycle.get('status') or '未上报')} / launchable={_markdown_value(lifecycle.get('launchable'))}",
        f"- 门禁阈值: sample={_markdown_value(thresholds.get('min_sample_size'))}, completed={_markdown_value(thresholds.get('min_completed_games'))}, paired={_markdown_value(thresholds.get('min_paired_overlap'))}",
        "",
        "## 发布说明",
        _markdown_value(snapshot.get("release_notes") or "未填写"),
        "",
        "## 摘要",
        f"- 行数: {summary.get('row_count', snapshot.get('row_count', 0))}",
        f"- 可入榜: {summary.get('rankable_count', snapshot.get('rankable_count', 0))}",
        f"- 未入榜: {summary.get('unrankable_count', snapshot.get('unrankable_count', 0))}",
        f"- 来源运行: {summary.get('source_run_count', snapshot.get('source_run_count', 0))}",
        f"- 来源报告: {summary.get('source_report_count', snapshot.get('source_report_count', 0))}",
        f"- 来源过滤: {_markdown_value(source.get('source_filter_applied') or summary.get('source_filter_applied') or {})}",
        "",
        "## 冻结行",
    ]
    for index, row in enumerate(rows[:100], start=1):
        if not isinstance(row, dict):
            continue
        score = _leaderboard_score(row, scope=str(snapshot.get("scope") or "role_version"))
        win_rate = _leaderboard_metric(row, "target_side_win_rate")
        lines.append(
            f"- {index}. {_markdown_value(row.get('subject_id') or row.get('hash'))}: "
            f"分数 {score:.4f} / 胜率 {win_rate:.4f} / "
            f"{'可入榜' if row.get('rankable') is not False else '未入榜'} / "
            f"运行 {_markdown_value(row.get('source_run_id') or row.get('batch_id'))} / "
            f"报告 {_markdown_value(row.get('report_id'))}"
        )
    if len(rows) > 100:
        lines.append(f"- 另有 {len(rows) - 100} 行未在 Markdown 预览中展开。")
    if not rows:
        lines.append("- 无冻结行")
    return "\n".join(lines)

def _benchmark_snapshot_csv(snapshot: dict[str, Any]) -> str:
    summary = snapshot.get("summary") if isinstance(snapshot.get("summary"), dict) else {}
    manifest = snapshot.get("release_manifest") if isinstance(snapshot.get("release_manifest"), dict) else {}
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    release_gate = _benchmark_snapshot_release_gate_export_summary(snapshot)
    thresholds = release_gate["thresholds"]
    lifecycle = release_gate["suite_lifecycle"]
    rows: list[list[Any]] = [
        ["区段", "标签", "值", "详情"],
        ["快照头", "快照 ID", snapshot.get("snapshot_id"), ""],
        ["快照头", "标题", snapshot.get("title"), ""],
        ["快照头", "范围", snapshot.get("scope"), ""],
        ["快照头", "套件", snapshot.get("benchmark_id"), snapshot.get("benchmark_version")],
        ["快照头", "评测集", snapshot.get("evaluation_set_id"), ""],
        ["快照头", "种子集", snapshot.get("seed_set_id"), ""],
        ["快照头", "Config Hash", snapshot.get("benchmark_config_hash"), ""],
        ["快照头", "内容 Hash", snapshot.get("content_hash"), ""],
        ["发布门禁", "状态", release_gate["label"], f"阻断 {release_gate['blocker_count']} / 警告 {release_gate['warning_count']}"],
        ["发布门禁", "套件状态", lifecycle.get("status") or "未上报", f"launchable={lifecycle.get('launchable')}"],
        [
            "发布门禁",
            "阈值",
            json.dumps(thresholds, ensure_ascii=False),
            "min_sample_size / min_completed_games / min_paired_overlap",
        ],
        ["发布说明", "说明", snapshot.get("release_notes"), ""],
        ["摘要", "行数", summary.get("row_count", snapshot.get("row_count", 0)), ""],
        ["摘要", "可入榜", summary.get("rankable_count", snapshot.get("rankable_count", 0)), ""],
        ["摘要", "未入榜", summary.get("unrankable_count", snapshot.get("unrankable_count", 0)), ""],
        ["摘要", "来源运行", summary.get("source_run_count", snapshot.get("source_run_count", 0)), ""],
        ["摘要", "来源报告", summary.get("source_report_count", snapshot.get("source_report_count", 0)), ""],
        ["摘要", "来源过滤", json.dumps(source.get("source_filter_applied") or summary.get("source_filter_applied") or {}, ensure_ascii=False), ""],
    ]
    scope = str(snapshot.get("scope") or "role_version")
    for row in snapshot.get("rows", []) or []:
        if not isinstance(row, dict):
            continue
        subject = row.get("subject_id") or row.get("hash") or row.get("model_config_hash") or row.get("model_id")
        rows.append([
            "冻结行",
            subject,
            _leaderboard_score(row, scope=scope),
            (
                f"胜率 {row.get('target_side_win_rate', '')} / "
                f"入榜 {row.get('rankable') is not False} / "
                f"运行 {row.get('source_run_id') or row.get('batch_id') or ''} / "
                f"报告 {row.get('report_id') or ''}"
            ),
        ])
    return "\n".join(",".join(_csv_value(value) for value in row) for row in rows)

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
