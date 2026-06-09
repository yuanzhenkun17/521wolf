"""Benchmark routes for the UI backend."""

from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.util.time import beijing_now_iso
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.evolution_serializers import _evolution_batch_summary
from ui.backend.schemas import BenchmarkLifecycleRequest, BenchmarkRequest, BenchmarkSnapshotRequest, BenchmarkViewRequest
from ui.backend.sse import _sse, stream_task_event_log_sse, task_event_log_matches_entity
from ui.backend.task_state import _last_event_id_from_request, _set_task_contract

_TERMINAL_BENCHMARK_SSE_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


def _benchmark_sse_event(status: Any) -> str:
    status_text = str(status or "").lower()
    if status_text in _TERMINAL_BENCHMARK_SSE_STATUSES:
        return status_text
    return "progress"


def _benchmark_task_event_name(item: dict[str, Any]) -> str:
    event_name = str(item.get("event") or _benchmark_sse_event(item.get("status")))
    if event_name == "progress":
        return _benchmark_sse_event(item.get("status"))
    return event_name


def register_benchmark_routes(api: FastAPI, store: Any) -> None:
    @api.get("/api/benchmarks")
    def list_benchmarks() -> dict[str, Any]:
        return {"kind": "benchmark_specs", "schema_version": 1, "items": store.list_benchmark_specs()}

    @api.get("/api/benchmarks/{benchmark_id}")
    def get_benchmark(benchmark_id: str) -> dict[str, Any]:
        return store.get_benchmark_spec_summary(benchmark_id)

    @api.patch("/api/benchmarks/{benchmark_id}/lifecycle")
    def update_benchmark_lifecycle(benchmark_id: str, request: BenchmarkLifecycleRequest) -> dict[str, Any]:
        return store.update_benchmark_lifecycle(benchmark_id, request)

    @api.get("/api/benchmark/seed-sets")
    def list_benchmark_seed_sets() -> dict[str, Any]:
        return store.list_benchmark_seed_sets()

    @api.get("/api/benchmark/seed-sets/{seed_set_id}")
    def get_benchmark_seed_set(seed_set_id: str) -> dict[str, Any]:
        return store.get_benchmark_seed_set(seed_set_id)

    @api.post("/api/benchmark/plan")
    def plan_benchmark(request: BenchmarkRequest) -> dict[str, Any]:
        return store.plan_benchmark(request)

    @api.post("/api/benchmark/snapshots")
    def create_benchmark_snapshot(request: BenchmarkSnapshotRequest) -> dict[str, Any]:
        return store.create_benchmark_snapshot(request)

    @api.get("/api/benchmark/snapshots")
    def list_benchmark_snapshots(
        scope: str | None = Query(default=None),
        evaluation_set_id: str | None = Query(default=None),
        benchmark_id: str | None = Query(default=None),
        target_role: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        return store.list_benchmark_snapshots(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            limit=limit,
        )

    @api.get("/api/benchmark/snapshots/{snapshot_id}")
    def get_benchmark_snapshot(snapshot_id: str) -> dict[str, Any]:
        return store.get_benchmark_snapshot(snapshot_id)

    @api.get("/api/benchmark/snapshots/{snapshot_id}/export")
    def export_benchmark_snapshot(
        snapshot_id: str,
        format: str = Query(default="json"),
    ) -> dict[str, Any]:
        return store.benchmark_snapshot_export(snapshot_id, format=format)

    @api.get("/api/benchmark/snapshots/{snapshot_id}/compare")
    def compare_benchmark_snapshot(
        snapshot_id: str,
        against_snapshot_id: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        return store.benchmark_snapshot_compare(snapshot_id, against_snapshot_id=against_snapshot_id, limit=limit)

    @api.post("/api/benchmark/views")
    def save_benchmark_view(request: BenchmarkViewRequest) -> dict[str, Any]:
        return store.save_benchmark_view(request)

    @api.get("/api/benchmark/views")
    def list_benchmark_views(
        scope: str | None = Query(default=None),
        evaluation_set_id: str | None = Query(default=None),
        benchmark_id: str | None = Query(default=None),
        target_role: str | None = Query(default=None),
        view_key: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        return store.list_benchmark_views(
            scope=scope,
            evaluation_set_id=evaluation_set_id,
            benchmark_id=benchmark_id,
            target_role=target_role,
            view_key=view_key,
            limit=limit,
        )

    @api.get("/api/benchmark/views/{view_key}")
    def get_benchmark_view(view_key: str) -> dict[str, Any]:
        return store.get_benchmark_view(view_key)

    @api.delete("/api/benchmark/views/{view_key}")
    def delete_benchmark_view(view_key: str) -> dict[str, Any]:
        return store.delete_benchmark_view(view_key)

    @api.post("/api/benchmark")
    async def start_benchmark(request: BenchmarkRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        batch = store.queue_benchmark(request)
        background_tasks.add_task(store.run_queued_benchmark, batch["batch_id"], request)
        return batch

    @api.post("/api/benchmark/batch")
    async def start_benchmark_batch(request: BenchmarkRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        batch = store.queue_benchmark(request)
        background_tasks.add_task(store.run_queued_benchmark, batch["batch_id"], request)
        return batch

    @api.get("/api/benchmark/batch/{batch_id}")
    def benchmark_batch_detail(batch_id: str) -> dict[str, Any]:
        return store.benchmark_batch_detail(batch_id)

    @api.get("/api/benchmark/batch/{batch_id}/games")
    def benchmark_batch_games(
        batch_id: str,
        result_batch_id: str | None = Query(default=None),
        target_role: str | None = Query(default=None),
        status: str | None = Query(default=None),
        seed: str | None = Query(default=None),
        limit: int | None = Query(default=None, ge=0, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return store.benchmark_batch_games(
            batch_id,
            result_batch_id=result_batch_id,
            target_role=target_role,
            status=status,
            seed=seed,
            limit=limit,
            offset=offset,
        )

    @api.get("/api/benchmark/batch/{batch_id}/diagnostics")
    def benchmark_batch_diagnostics(
        batch_id: str,
        target_role: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        level: str | None = Query(default=None),
        status: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        seed: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return store.benchmark_batch_diagnostics(
            batch_id,
            target_role=target_role,
            kind=kind,
            level=level,
            status=status,
            stage=stage,
            seed=seed,
        )

    @api.get("/api/benchmark/batch/{batch_id}/report")
    def benchmark_batch_report(
        batch_id: str,
        format: str = Query(default="json"),
    ) -> dict[str, Any]:
        return store.benchmark_batch_report(batch_id, format=format)

    @api.get("/api/benchmark/reports")
    def benchmark_reports(
        scope: str | None = Query(default=None),
        evaluation_set_id: str | None = Query(default=None),
        benchmark_id: str | None = Query(default=None),
        target_role: str | None = Query(default=None),
        model_id: str | None = Query(default=None),
        model_config_hash: str | None = Query(default=None),
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return store.benchmark_reports(
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

    @api.get("/api/benchmark/diagnostics")
    def benchmark_diagnostics(
        scope: str | None = Query(default=None),
        evaluation_set_id: str | None = Query(default=None),
        benchmark_id: str | None = Query(default=None),
        target_role: str | None = Query(default=None),
        model_id: str | None = Query(default=None),
        model_config_hash: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        level: str | None = Query(default=None),
        status: str | None = Query(default=None),
        stage: str | None = Query(default=None),
        seed: str | None = Query(default=None),
        limit: int = Query(default=200, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        return store.benchmark_diagnostics(
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

    @api.post("/api/benchmark/batch/{batch_id}/stop")
    def stop_benchmark(batch_id: str) -> dict[str, Any]:
        batch = store.evolution_batches.get(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="batch not found")
        batch["status"] = "failed"
        batch["stop_requested"] = True
        _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
        batch["finished_at"] = beijing_now_iso()
        batch["error"] = batch.get("error") or MANUAL_STOP_REASON
        store._mark_benchmark_stage(
            batch,
            "stopped",
            status="failed",
            percent=store._task_progress_percent(batch),
            completed_roles=int(batch.get("progress", {}).get("completed_roles", 0)) if isinstance(batch.get("progress"), dict) else 0,
            role_count=len(batch.get("roles", []) or []),
            diagnostic={"kind": "benchmark_stopped", "message": batch["error"]},
        )
        store._persist_background_tasks()
        return batch

    @api.get("/api/benchmark/batch/{batch_id}/events")
    def benchmark_events(batch_id: str, request: Request) -> StreamingResponse:
        batch = store.evolution_batches.get(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="batch not found")
        last_event_id = _last_event_id_from_request(request)

        async def stream() -> AsyncIterator[str]:
            if task_event_log_matches_entity(
                store.task_event_log,
                batch_id,
                batch,
                terminal_statuses=_TERMINAL_BENCHMARK_SSE_STATUSES,
            ):
                async for frame in stream_task_event_log_sse(
                    store.task_event_log,
                    batch_id,
                    after_event_id=last_event_id,
                    ping_payload=lambda: {"batch_id": batch_id, "status": batch.get("status")},
                    event_name=_benchmark_task_event_name,
                    terminal_statuses=_TERMINAL_BENCHMARK_SSE_STATUSES,
                ):
                    yield frame
                return
            if last_event_id < 1:
                yield _sse(_benchmark_sse_event(batch.get("status")), _evolution_batch_summary(batch), event_id=1)

        return StreamingResponse(stream(), media_type="text/event-stream")
