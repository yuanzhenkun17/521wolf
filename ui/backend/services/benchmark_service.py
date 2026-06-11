"""Benchmark service facade for the UI backend."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import HTTPException

from app.util.time import beijing_now_iso
from ui.backend.preflight import require_runtime_ready
from ui.backend.services.benchmark_catalog_service import BenchmarkCatalogService
from ui.backend.services.benchmark_leaderboard_service import BenchmarkLeaderboardService
from ui.backend.services.benchmark_report_service import BenchmarkReportService
from ui.backend.services.benchmark_run_service import BenchmarkRunService
from ui.backend.services.benchmark_snapshot_service import BenchmarkSnapshotService
from ui.backend.schemas import (
    BenchmarkLifecycleRequest,
    BenchmarkRequest,
    BenchmarkSnapshotRequest,
    BenchmarkViewRequest,
)
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.evolution_serializers import _evolution_batch_summary
from ui.backend.services.task_service import BackgroundTaskServiceProtocol
from ui.backend.sse import _sse, stream_task_event_log_sse, task_event_log_matches_entity
from ui.backend.task_state import _set_task_contract

_TERMINAL_BENCHMARK_SSE_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


class BenchmarkServiceContextProtocol(Protocol):
    """Context capabilities required by ``BenchmarkService``."""

    paths: object
    evolution_batches: dict[str, dict[str, Any]]

    @property
    def task_service(self) -> BackgroundTaskServiceProtocol:
        ...


class BenchmarkService:
    """Compatibility facade for benchmark-facing ``BackendStore`` methods."""

    def __init__(self, context: BenchmarkServiceContextProtocol) -> None:
        self._context = context
        self._catalog = BenchmarkCatalogService(context)
        self._leaderboards = BenchmarkLeaderboardService(context)
        self._reports = BenchmarkReportService(context)
        self._runs = BenchmarkRunService(context, catalog=self._catalog)
        self._snapshots = BenchmarkSnapshotService(context)

    @property
    def context(self) -> BenchmarkServiceContextProtocol:
        return self._context

    @property
    def _tasks(self) -> BackgroundTaskServiceProtocol:
        return self._context.task_service

    def load_role_leaderboard_rows(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        return self._leaderboards.load_role_leaderboard_rows(role, evaluation_set_id=evaluation_set_id)

    def load_leaderboard_rows(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[Any]:
        return self._leaderboards.load_leaderboard_rows(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            limit=limit,
        )

    def load_role_leaderboard_rows_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> list[Any]:
        return self._leaderboards.load_role_leaderboard_rows_for_roles(
            roles,
            evaluation_set_id=evaluation_set_id,
        )

    def persist_benchmark_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshots.persist_benchmark_snapshot(snapshot)

    def load_benchmark_snapshot_summaries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self._snapshots.load_benchmark_snapshot_summaries(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            limit=limit,
        )

    def load_benchmark_snapshot_detail(self, snapshot_id: str) -> dict[str, Any] | None:
        return self._snapshots.load_benchmark_snapshot_detail(snapshot_id)

    def persist_benchmark_saved_view(self, view: dict[str, Any]) -> None:
        self._snapshots.persist_benchmark_saved_view(view)

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
        return self._snapshots.load_benchmark_saved_views(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            view_key=view_key,
            limit=limit,
        )

    def delete_benchmark_saved_view(self, view_key: str) -> bool:
        return self._snapshots.delete_benchmark_saved_view(view_key)

    @staticmethod
    def sse_event(status: Any) -> str:
        status_text = str(status or "").lower()
        if status_text in _TERMINAL_BENCHMARK_SSE_STATUSES:
            return status_text
        return "progress"

    @classmethod
    def task_event_name(cls, item: dict[str, Any]) -> str:
        event_name = str(item.get("event") or cls.sse_event(item.get("status")))
        if event_name == "progress":
            return cls.sse_event(item.get("status"))
        return event_name

    def _batch(self, batch_id: str) -> dict[str, Any]:
        self._refresh_background_tasks()
        batch = self._context.evolution_batches.get(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return batch

    def _refresh_background_tasks(self) -> None:
        task_service = getattr(self._context, "task_service", None)
        load_background_tasks = getattr(task_service, "load_background_tasks", None)
        if callable(load_background_tasks):
            load_background_tasks()

    def benchmark_specs_payload(self) -> dict[str, Any]:
        return {"kind": "benchmark_specs", "schema_version": 1, "items": self.list_benchmark_specs()}

    def stop_benchmark(self, batch_id: str) -> dict[str, Any]:
        batch = self._batch(batch_id)
        batch["status"] = "failed"
        batch["stop_requested"] = True
        _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
        batch["finished_at"] = beijing_now_iso()
        batch["error"] = batch.get("error") or MANUAL_STOP_REASON
        self._tasks.mark_benchmark_stage(
            batch,
            "stopped",
            status="failed",
            percent=self._tasks.task_progress_percent(batch),
            completed_roles=int(batch.get("progress", {}).get("completed_roles", 0)) if isinstance(batch.get("progress"), dict) else 0,
            role_count=len(batch.get("roles", []) or []),
            diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
        )
        self._request_queue_cancel(batch, fallback_task_id=batch_id)
        self._tasks.persist_background_tasks()
        return batch

    def _request_queue_cancel(self, batch: dict[str, Any], *, fallback_task_id: str) -> None:
        cancel_task = getattr(self._tasks, "cancel_task", None)
        if not callable(cancel_task):
            return
        task_id = str(batch.get("task_id") or batch.get("queue_task_id") or fallback_task_id or "").strip()
        if not task_id:
            return
        try:
            cancel_task(task_id)
        except Exception:  # noqa: BLE001 - legacy stop must remain best-effort when queue storage is unavailable
            return

    def stream_benchmark_events(self, batch_id: str, last_event_id: int) -> AsyncIterator[str]:
        batch = self._batch(batch_id)
        task_event_log = self._tasks.task_event_log

        async def stream() -> AsyncIterator[str]:
            if task_event_log_matches_entity(
                task_event_log,
                batch_id,
                batch,
                terminal_statuses=_TERMINAL_BENCHMARK_SSE_STATUSES,
            ):
                async for frame in stream_task_event_log_sse(
                    task_event_log,
                    batch_id,
                    after_event_id=last_event_id,
                    ping_payload=lambda: {"batch_id": batch_id, "status": batch.get("status")},
                    event_name=self.task_event_name,
                    terminal_statuses=_TERMINAL_BENCHMARK_SSE_STATUSES,
                ):
                    yield frame
                return
            if last_event_id < 1:
                yield _sse(self.sse_event(batch.get("status")), _evolution_batch_summary(batch), event_id=1)

        return stream()

    def leaderboard_scores_for_role(
        self,
        role: str,
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, Any]]:
        return self._leaderboards.leaderboard_scores_for_role(role, evaluation_set_id=evaluation_set_id)

    def leaderboard_entries(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._leaderboards.leaderboard_entries(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            limit=limit,
        )

    def model_leaderboard_entries(
        self,
        *,
        evaluation_set_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        return self._leaderboards.model_leaderboard_entries(evaluation_set_id=evaluation_set_id, limit=limit)

    def leaderboard_unrankable_evidence(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        limit: int = 100,
        rows: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        return self._leaderboards.leaderboard_unrankable_evidence(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            limit=limit,
            rows=rows,
        )

    def leaderboard_compare(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        target_role: str | None = None,
        baseline_subject_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._leaderboards.leaderboard_compare(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            target_role=target_role,
            baseline_subject_id=baseline_subject_id,
            limit=limit,
        )

    def leaderboard_scores_for_roles(
        self,
        roles: list[str],
        *,
        evaluation_set_id: str | None = None,
    ) -> dict[str, dict[str, dict[str, Any]]]:
        return self._leaderboards.leaderboard_scores_for_roles(roles, evaluation_set_id=evaluation_set_id)

    def list_benchmark_specs(self) -> list[dict[str, Any]]:
        return self._catalog.list_benchmark_specs()

    def get_benchmark_spec_summary(self, benchmark_id: str) -> dict[str, Any]:
        return self._catalog.get_benchmark_spec_summary(benchmark_id)

    def update_benchmark_lifecycle(
        self,
        benchmark_id: str,
        request: BenchmarkLifecycleRequest,
    ) -> dict[str, Any]:
        return self._catalog.update_benchmark_lifecycle(benchmark_id, request)

    def list_benchmark_seed_sets(self) -> dict[str, Any]:
        return self._catalog.list_benchmark_seed_sets()

    def get_benchmark_seed_set(self, seed_set_id: str) -> dict[str, Any]:
        return self._catalog.get_benchmark_seed_set(seed_set_id)

    def benchmark_spec_with_lifecycle(self, benchmark_id: str) -> tuple[Any, dict[str, Any] | None]:
        return self._catalog.benchmark_spec_with_lifecycle(benchmark_id)

    def resolve_benchmark_spec(self, request: BenchmarkRequest) -> tuple[Any, Any]:
        return self._catalog.resolve_benchmark_spec(request)

    def benchmark_summary(self, spec: Any, seed_set: Any | None = None) -> dict[str, Any]:
        return self._catalog.benchmark_summary(spec, seed_set)

    def benchmark_metadata(self, spec: Any, seed_set: Any | None = None) -> dict[str, Any]:
        return self._catalog.benchmark_metadata(spec, seed_set)

    def plan_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        return self._runs.plan_benchmark(request)

    def queue_benchmark(self, request: BenchmarkRequest) -> dict[str, Any]:
        return self._runs.queue_benchmark(request)

    def queue_benchmark_task(self, batch: dict[str, Any], request: BenchmarkRequest) -> dict[str, Any]:
        return self._runs.queue_benchmark_task(batch, request)

    async def run_queued_benchmark(self, batch_id: str, request: BenchmarkRequest, **kwargs: Any) -> None:
        await self._runs.run_queued_benchmark(batch_id, request, **kwargs)

    def task_executors(self) -> dict[str, Any]:
        return {"benchmark_batch": self.execute_benchmark_task}

    def execute_benchmark_task(self, task: dict[str, Any], context: Any) -> dict[str, Any]:
        payload = task.get("payload") if isinstance(task.get("payload"), dict) else {}
        batch_id = str(payload.get("batch_id") or task.get("task_id") or "")
        request_payload = payload.get("request") if isinstance(payload.get("request"), dict) else {}
        request = BenchmarkRequest.model_validate(request_payload)
        asyncio.run(
            require_runtime_ready(
                self._context,
                scope="benchmark_start",
                model_scope="benchmark",
                model_profile_id=request.model_profile_id,
            )
        )
        self.restore_benchmark_task_snapshot(
            payload=payload,
            batch_id=batch_id,
        )

        def progress_sink(progress: dict[str, Any]) -> None:
            payload = dict(progress)
            payload.setdefault("stage", "benchmark_running")
            payload["batch_id"] = batch_id
            context.heartbeat(progress=payload)

        context.heartbeat(progress={"stage": "benchmark_running", "batch_id": batch_id})
        asyncio.run(
            self.run_queued_benchmark(
                batch_id,
                request,
                cancel_check=context.cancel_requested,
                progress_sink=progress_sink,
            )
        )
        batch = self._context.evolution_batches.get(batch_id, {})
        artifacts = self.persist_benchmark_task_artifacts(batch_id)
        return {
            "batch_id": batch_id,
            "status": batch.get("status"),
            "artifact_ids": [artifact["artifact_id"] for artifact in artifacts],
        }

    def restore_benchmark_task_snapshot(
        self,
        *,
        payload: dict[str, Any],
        batch_id: str,
    ) -> dict[str, Any]:
        if not batch_id:
            raise RuntimeError("benchmark task is missing batch_id")
        snapshot = payload.get("snapshot") if isinstance(payload.get("snapshot"), dict) else {}
        batch_snapshot = snapshot.get("batch") if isinstance(snapshot.get("batch"), dict) else {}
        if batch_id not in self._context.evolution_batches and batch_snapshot:
            self._context.evolution_batches[batch_id] = dict(batch_snapshot)
        if batch_id not in self._context.evolution_batches:
            self._tasks.load_background_tasks()
        batch = self._context.evolution_batches.get(batch_id)
        if not isinstance(batch, dict):
            raise RuntimeError(f"benchmark batch snapshot not found: {batch_id}")
        batch["task_id"] = batch_id
        batch["task_queue_status"] = "running"
        self._tasks.persist_background_tasks()
        return batch

    def persist_benchmark_task_artifacts(self, batch_id: str) -> list[dict[str, Any]]:
        batch = self._context.evolution_batches.get(batch_id)
        if not isinstance(batch, dict) or batch.get("status") != "completed":
            return []
        artifacts: list[dict[str, Any]] = []
        report = self.benchmark_batch_report(batch_id, format="json")
        artifacts.append(
            self._tasks.put_task_json_artifact(
                task_id=batch_id,
                name="benchmark-report.json",
                payload=report,
                artifact_type="benchmark_report",
                metadata={"format": "json", "report_id": report.get("report_id")},
            )
        )
        manifest = report.get("reproducibility_manifest")
        if isinstance(manifest, dict):
            artifacts.append(
                self._tasks.put_task_json_artifact(
                    task_id=batch_id,
                    name="reproducibility-manifest.json",
                    payload=manifest,
                    artifact_type="benchmark_reproducibility_manifest",
                    metadata={"format": "json", "report_id": report.get("report_id")},
                )
            )
        for format_name, content_type, filename in (
            ("markdown", "text/markdown", "benchmark-report.md"),
            ("csv", "text/csv", "benchmark-report.csv"),
        ):
            exported = self.benchmark_batch_report(batch_id, format=format_name)
            content = str(exported.get("content") or "")
            artifacts.append(
                self._tasks.put_task_bytes_artifact(
                    task_id=batch_id,
                    name=filename,
                    data=content.encode("utf-8"),
                    artifact_type=f"benchmark_report_{format_name}",
                    content_type=content_type,
                    metadata={"format": format_name, "report_id": report.get("report_id")},
                )
            )
        return artifacts

    def benchmark_model_runtime(self, request: BenchmarkRequest | None = None) -> dict[str, Any]:
        return self._runs.benchmark_model_runtime(request)

    def benchmark_run_plan(self, request: BenchmarkRequest) -> dict[str, Any]:
        return self._runs.benchmark_run_plan(request)

    def validate_benchmark_target_versions(
        self,
        roles: list[str],
        request: BenchmarkRequest,
        *,
        target_type: str,
    ) -> None:
        self._runs.validate_benchmark_target_versions(roles, request, target_type=target_type)

    def benchmark_batch_config(
        self,
        batch_id: str,
        role: str | None,
        request: BenchmarkRequest,
        index: int,
    ) -> dict[str, Any]:
        return self._runs.benchmark_batch_config(batch_id, role, request, index)

    def benchmark_roles(self, request: BenchmarkRequest, spec: Any | None) -> list[str]:
        return self._runs.benchmark_roles(request, spec)

    def benchmark_request_config(self, request: BenchmarkRequest, spec: Any | None = None) -> dict[str, Any]:
        return self._runs.benchmark_request_config(request, spec)

    def benchmark_batch_detail(self, batch_id: str) -> dict[str, Any]:
        self._refresh_background_tasks()
        return self._reports.benchmark_batch_detail(batch_id)

    def benchmark_batch_games(
        self,
        batch_id: str,
        *,
        result_batch_id: str | None = None,
        target_role: str | None = None,
        status: str | None = None,
        seed: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._refresh_background_tasks()
        return self._reports.benchmark_batch_games(
            batch_id,
            result_batch_id=result_batch_id,
            target_role=target_role,
            status=status,
            seed=seed,
            limit=limit,
            offset=offset,
        )

    def benchmark_batch_diagnostics(
        self,
        batch_id: str,
        *,
        target_role: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
    ) -> dict[str, Any]:
        self._refresh_background_tasks()
        return self._reports.benchmark_batch_diagnostics(
            batch_id,
            target_role=target_role,
            kind=kind,
            level=level,
            status=status,
            stage=stage,
            seed=seed,
        )

    def benchmark_batch_report(self, batch_id: str, *, format: str = "json") -> dict[str, Any]:
        self._refresh_background_tasks()
        return self._reports.benchmark_batch_report(batch_id, format=format)

    def benchmark_reports(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._refresh_background_tasks()
        return self._reports.benchmark_reports(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            model_id=model_id,
            model_config_hash=model_config_hash,
            status=status,
            limit=limit,
            offset=offset,
        )

    def benchmark_diagnostics(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        model_id: str | None = None,
        model_config_hash: str | None = None,
        kind: str | None = None,
        level: str | None = None,
        status: str | None = None,
        stage: str | None = None,
        seed: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        self._refresh_background_tasks()
        return self._reports.benchmark_diagnostics(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            model_id=model_id,
            model_config_hash=model_config_hash,
            kind=kind,
            level=level,
            status=status,
            stage=stage,
            seed=seed,
            limit=limit,
            offset=offset,
        )

    def create_benchmark_snapshot(self, request: BenchmarkSnapshotRequest) -> dict[str, Any]:
        return self._snapshots.create_benchmark_snapshot(request)

    def list_benchmark_snapshots(
        self,
        *,
        scope: str | None = None,
        evaluation_set_id: str | None = None,
        benchmark_id: str | None = None,
        target_role: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        return self._snapshots.list_benchmark_snapshots(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            limit=limit,
        )

    def get_benchmark_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        return self._snapshots.get_benchmark_snapshot(snapshot_id)

    def benchmark_snapshot_export(self, snapshot_id: str, *, format: str = "json") -> dict[str, Any]:
        return self._snapshots.benchmark_snapshot_export(snapshot_id, format=format)

    def benchmark_snapshot_compare(
        self,
        snapshot_id: str,
        *,
        against_snapshot_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._snapshots.benchmark_snapshot_compare(
            snapshot_id,
            against_snapshot_id=against_snapshot_id,
            limit=limit,
        )

    def save_benchmark_view(self, request: BenchmarkViewRequest) -> dict[str, Any]:
        return self._snapshots.save_benchmark_view(request)

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
        return self._snapshots.list_benchmark_views(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            view_key=view_key,
            limit=limit,
        )

    def get_benchmark_view(self, view_key: str) -> dict[str, Any]:
        return self._snapshots.get_benchmark_view(view_key)

    def delete_benchmark_view(self, view_key: str) -> dict[str, Any]:
        return self._snapshots.delete_benchmark_view(view_key)
