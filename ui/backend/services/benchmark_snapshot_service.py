"""Benchmark snapshot, saved-view, and export service helpers."""

from __future__ import annotations

import logging
import json
import uuid

from typing import Any, Protocol

from fastapi import HTTPException

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
from ui.backend.schemas import BenchmarkSnapshotRequest, BenchmarkViewRequest
from ui.backend.services.benchmark_payload_utils import json_clone as _json_clone
from ui.backend.services.benchmark_snapshot_payloads import (
    _benchmark_snapshot_compare_payload,
    _benchmark_snapshot_csv,
    _benchmark_snapshot_detail_payload,
    _benchmark_snapshot_markdown,
    _benchmark_snapshot_pair_boundary_warnings,
    _benchmark_snapshot_release_gate,
    _benchmark_snapshot_release_gate_error_detail,
    _benchmark_snapshot_source_filter_summary,
    _benchmark_snapshot_source_summary,
    _benchmark_snapshot_summary_payload,
    _benchmark_view_payload,
    _default_benchmark_snapshot_title,
    _filter_benchmark_snapshot_cache,
    _filter_benchmark_snapshot_rows,
    _filter_benchmark_view_cache,
    _stable_payload_hash,
    _text_content_hash,
)
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
