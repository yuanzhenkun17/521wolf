"""Evolution routes for the UI backend."""

from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ui.backend.schemas import (
    EvolutionActionRequest,
    EvolutionProposalRejectRequest,
    EvolutionStartRequest,
    automatic_evolution_request,
)
from ui.backend.serializers import (
    _evolution_batch_summary,
    _evolution_run_summary,
    _evolution_sse_event,
)
from ui.backend.services import EvolutionService
from ui.backend.sse import _sse, stream_task_event_log_sse, task_event_log_matches_entity
from ui.backend.task_state import (
    _history_query_requested,
    _last_event_id_from_request,
)

_TERMINAL_SSE_STATUSES = {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}


def register_evolution_routes(api: FastAPI, store: Any) -> None:
    service = EvolutionService(store)

    @api.post("/api/evolution-runs")
    async def start_evolution(request: EvolutionStartRequest, background_tasks: BackgroundTasks) -> dict[str, Any]:
        request = automatic_evolution_request(request)
        queued = store.queue_evolution(request)
        if queued.get("batch_id"):
            background_tasks.add_task(store.run_queued_evolution_batch, queued["batch_id"], request)
        else:
            background_tasks.add_task(store.run_queued_evolution, queued["run_id"], request)
        return queued

    @api.get("/api/evolution-runs")
    def list_evolution_runs(
        request: Request,
        limit: int | None = Query(default=None, ge=0, le=1000),
        offset: int = Query(default=0, ge=0),
        source: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return service.list_runs(
            history_requested=_history_query_requested(request),
            limit=limit,
            offset=offset,
            source=source,
            status=status,
        )

    @api.get("/api/evolution-runs/{run_id}")
    def get_evolution_run(run_id: str) -> dict[str, Any]:
        return service.get_run(run_id)

    @api.post("/api/evolution-runs/{run_id}/actions")
    def evolution_action(run_id: str, request: EvolutionActionRequest) -> dict[str, Any]:
        return service.run_action(run_id, request.action)

    @api.get("/api/evolution-runs/{run_id}/proposals")
    def evolution_proposals(run_id: str) -> dict[str, Any]:
        return service.proposals(run_id)

    @api.get("/api/evolution-runs/{run_id}/trust-bundle")
    def evolution_trust_bundle(run_id: str) -> dict[str, Any]:
        return service.trust_bundle_payload(run_id)

    @api.post("/api/evolution-runs/{run_id}/proposals/{proposal_id}/accept")
    def accept_evolution_run_proposal(run_id: str, proposal_id: str) -> dict[str, Any]:
        return service.accept_proposal(run_id, proposal_id)

    @api.post("/api/evolution-runs/{run_id}/proposals/{proposal_id}/reject")
    def reject_evolution_run_proposal(
        run_id: str,
        proposal_id: str,
        request: EvolutionProposalRejectRequest,
    ) -> dict[str, Any]:
        return service.reject_proposal(run_id, proposal_id, reason=request.reason, tags=request.tags)

    @api.post("/api/evolution-runs/{run_id}/proposals/apply-accepted")
    def apply_accepted_evolution_run_proposals(run_id: str) -> dict[str, Any]:
        return service.apply_accepted_proposals(run_id)

    @api.get("/api/evolution-runs/{run_id}/diff")
    def evolution_diff(run_id: str) -> dict[str, Any]:
        return service.diff(run_id)

    @api.get("/api/evolution-runs/{run_id}/games")
    def evolution_games(
        run_id: str,
        request: Request,
        phase: str = "training",
        side: str | None = None,
        limit: int | None = Query(default=None, ge=0, le=1000),
        offset: int = Query(default=0, ge=0),
        status: str | None = Query(default=None),
    ) -> dict[str, Any]:
        return service.games(
            run_id,
            phase=phase,
            side=side,
            limit=limit,
            offset=offset,
            status=status,
            paginate=any(key in request.query_params for key in ("limit", "offset", "status")),
        )

    @api.get("/api/evolution-runs/{run_id}/games/{game_id}/{detail_type}")
    def evolution_game_detail(
        run_id: str,
        game_id: str,
        detail_type: str,
        phase: str = "training",
        side: str | None = None,
    ) -> dict[str, Any]:
        return service.game_detail(run_id, game_id, detail_type, phase=phase, side=side)

    @api.get("/api/evolution-runs/{run_id}/events")
    def evolution_events(run_id: str, request: Request) -> StreamingResponse:
        entity = store.evolution_runs.get(run_id) or store.evolution_batches.get(run_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="run not found")
        last_event_id = _last_event_id_from_request(request)

        async def stream() -> AsyncIterator[str]:
            if task_event_log_matches_entity(
                store.task_event_log,
                run_id,
                entity,
                terminal_statuses=_TERMINAL_SSE_STATUSES,
            ):
                async for frame in stream_task_event_log_sse(
                    store.task_event_log,
                    run_id,
                    after_event_id=last_event_id,
                    ping_payload=lambda: {"run_id": run_id, "status": entity.get("status")},
                    event_name=lambda item: str(item.get("event") or _evolution_sse_event(item.get("status"))),
                    terminal_statuses=_TERMINAL_SSE_STATUSES,
                ):
                    yield frame
                return
            payload = (
                _evolution_run_summary(entity)
                if entity.get("run_id")
                else _evolution_batch_summary(entity)
            )
            if last_event_id < 1:
                yield _sse(_evolution_sse_event(entity.get("status")), payload, event_id=1)

        return StreamingResponse(stream(), media_type="text/event-stream")
