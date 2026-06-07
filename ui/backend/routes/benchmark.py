"""Benchmark routes for the UI backend."""

from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.util.time import beijing_now_iso
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.evolution_serializers import _evolution_batch_summary
from ui.backend.schemas import BenchmarkRequest
from ui.backend.sse import _sse, stream_task_event_log_sse
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

    @api.post("/api/benchmark/batch/{batch_id}/stop")
    def stop_benchmark(batch_id: str) -> dict[str, Any]:
        batch = store.evolution_batches.get(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="batch not found")
        batch["status"] = "failed"
        batch["stop_requested"] = True
        _set_task_contract(batch, stop_requested=True, cancelled=True, interrupted=False, failed=False)
        batch["finished_at"] = batch.get("finished_at") or beijing_now_iso()
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
            if store.task_event_log.has_events(batch_id):
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
