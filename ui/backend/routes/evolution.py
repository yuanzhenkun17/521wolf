"""Evolution routes for the UI backend."""

from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.util.time import beijing_now_iso
from ui.backend.constants import MANUAL_STOP_REASON
from ui.backend.evolution_actions import (
    _promote_evolution_run,
    _reject_evolution_run,
    accept_evolution_proposal,
    apply_accepted_evolution_proposals,
    reject_evolution_proposal,
)
from ui.backend.schemas import (
    EvolutionActionRequest,
    EvolutionProposalRejectRequest,
    EvolutionStartRequest,
    automatic_evolution_request,
)
from ui.backend.serializers import (
    _evolution_batch_summary,
    _evolution_games_for_query,
    _evolution_run_summary,
    _evolution_sse_event,
    _normalize_decision,
    _normalize_event,
    _sample_game_archive_payload,
)
from ui.backend.sse import _sse, stream_task_event_log_sse, task_event_log_matches_entity
from ui.backend.task_state import (
    _background_source,
    _filter_values,
    _history_query_requested,
    _history_time_key,
    _last_event_id_from_request,
    _match_filter,
    _pagination,
    _set_task_contract,
)

_TERMINAL_SSE_STATUSES = {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}
_TERMINAL_TASK_STATUSES = {"reviewing", "promoted", "rejected", "failed", "completed", "cancelled", "interrupted"}


def _proposal_run(store: Any, run_id: str) -> dict[str, Any]:
    run = store.evolution_runs.get(run_id)
    if run is not None:
        return run
    if run_id in store.evolution_batches:
        raise HTTPException(status_code=400, detail="batch does not support proposals; select a child run")
    raise HTTPException(status_code=404, detail="run not found")


def _proposal_pairs(run: dict[str, Any]) -> list[dict[str, Any]]:
    battle = run.get("battle_result") if isinstance(run.get("battle_result"), dict) else {}
    for value in (
        run.get("paired_seed_pairs"),
        run.get("paired_seed_battle_table"),
        run.get("battle_pairs"),
        battle.get("paired_seed_pairs"),
        battle.get("paired_seed_battle_table"),
        battle.get("battle_pairs"),
    ):
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _proposal_payload(run: dict[str, Any], *, action: dict[str, Any] | None = None) -> dict[str, Any]:
    summary = _evolution_run_summary(run)
    pairs = _proposal_pairs(run)
    payload: dict[str, Any] = {
        "kind": "role_evolution_proposals",
        "schema_version": 1,
        "run_id": run.get("run_id"),
        "role": run.get("role"),
        "proposals": [dict(item) for item in run.get("proposals", []) or [] if isinstance(item, dict)],
        "proposal_review": summary.get("proposal_review", {}),
        "gate_report": summary.get("gate_report", {}),
        "promotion_gate": summary.get("promotion_gate", {}),
        "paired_seed_summary": summary.get("paired_seed_summary", {}),
        "paired_seed_pairs": pairs,
        "paired_seed_battle_table": pairs,
        "paired_seeds": pairs,
        "battle_pairs": pairs,
        "run": summary,
    }
    if action is not None:
        payload["action"] = action
    return payload


def _persist_proposal_mutation(store: Any, run: dict[str, Any]) -> None:
    store._touch_background_task(run)
    store._persist_background_tasks()


def register_evolution_routes(api: FastAPI, store: Any) -> None:
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
        runs = [_evolution_run_summary(run) for run in store.evolution_runs.values()]
        batches = [_evolution_batch_summary(batch) for batch in store.evolution_batches.values()]
        runs.sort(key=_history_time_key, reverse=True)
        batches.sort(key=_history_time_key, reverse=True)
        if source:
            sources = _filter_values(source)
            if sources is not None and "evolution" not in sources:
                runs = []
            if sources is not None:
                batches = [batch for batch in batches if _background_source(batch) in sources]
        statuses = _filter_values(status)
        if statuses is not None:
            runs = [run for run in runs if _match_filter(run.get("status"), statuses)]
            batches = [batch for batch in batches if _match_filter(batch.get("status"), statuses)]
        payload = {
            "kind": "evolution_runs",
            "schema_version": 1,
            "runs": runs,
            "batches": batches,
        }
        if not _history_query_requested(request):
            return payload
        combined: list[tuple[str, dict[str, Any]]] = [
            *[("run", run) for run in runs],
            *[("batch", batch) for batch in batches],
        ]
        combined.sort(key=lambda item: _history_time_key(item[1]), reverse=True)
        page, pagination = _pagination([item for _, item in combined], limit=limit, offset=offset)
        page_ids = {
            str(item.get("run_id") or item.get("batch_id"))
            for item in page
        }
        payload["runs"] = [run for run in runs if str(run.get("run_id")) in page_ids]
        payload["batches"] = [batch for batch in batches if str(batch.get("batch_id")) in page_ids]
        payload["pagination"] = pagination
        return payload

    @api.get("/api/evolution-runs/{run_id}")
    def get_evolution_run(run_id: str) -> dict[str, Any]:
        run = store.evolution_runs.get(run_id)
        if run is not None:
            return run
        batch = store.evolution_batches.get(run_id)
        if batch is not None:
            return _evolution_batch_summary(batch)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @api.post("/api/evolution-runs/{run_id}/actions")
    def evolution_action(run_id: str, request: EvolutionActionRequest) -> dict[str, Any]:
        entity = store.evolution_runs.get(run_id) or store.evolution_batches.get(run_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="run not found")
        action = request.action.lower()
        if action == "promote":
            if "role" not in entity:
                raise HTTPException(status_code=400, detail="batch does not support promote; select a child run")
            _promote_evolution_run(store, entity)
            entity["status"] = "promoted"
        elif action == "reject":
            if "role" not in entity:
                raise HTTPException(status_code=400, detail="batch does not support reject; select a child run")
            _reject_evolution_run(store, entity)
            entity["status"] = "rejected"
        elif action in {"stop", "terminate"}:
            if hasattr(store, "_mark_evolution_stopped"):
                store._mark_evolution_stopped(entity)
                if entity.get("kind") == "role_evolution_batch":
                    for child_id in list(entity.get("runs", []) or []):
                        child = store.evolution_runs.get(str(child_id))
                        if child is None:
                            continue
                        if str(child.get("status") or "").lower() not in _TERMINAL_TASK_STATUSES:
                            store._mark_evolution_stopped(child)
                    store._refresh_evolution_batch(entity.get("batch_id"))
            else:
                entity["status"] = "failed"
                entity["error"] = entity.get("error") or MANUAL_STOP_REASON
                _set_task_contract(entity, stop_requested=True, cancelled=True, interrupted=False, failed=False)
        elif action == "resume":
            entity["status"] = "reviewing"
            _set_task_contract(entity, stop_requested=False, cancelled=False, interrupted=False, failed=False)
        store._touch_background_task(entity)
        if entity.get("status") in {"failed", "promoted", "rejected", "reviewing"}:
            entity["finished_at"] = entity.get("finished_at") or beijing_now_iso()
        store._persist_background_tasks()
        return entity

    @api.get("/api/evolution-runs/{run_id}/proposals")
    def evolution_proposals(run_id: str) -> dict[str, Any]:
        run = _proposal_run(store, run_id)
        return _proposal_payload(run)

    @api.post("/api/evolution-runs/{run_id}/proposals/{proposal_id}/accept")
    def accept_evolution_run_proposal(run_id: str, proposal_id: str) -> dict[str, Any]:
        run = _proposal_run(store, run_id)
        action = accept_evolution_proposal(store, run, proposal_id)
        _persist_proposal_mutation(store, run)
        return _proposal_payload(run, action=action)

    @api.post("/api/evolution-runs/{run_id}/proposals/{proposal_id}/reject")
    def reject_evolution_run_proposal(
        run_id: str,
        proposal_id: str,
        request: EvolutionProposalRejectRequest,
    ) -> dict[str, Any]:
        run = _proposal_run(store, run_id)
        action = reject_evolution_proposal(
            store,
            run,
            proposal_id,
            reason=request.reason,
            tags=request.tags,
        )
        _persist_proposal_mutation(store, run)
        return _proposal_payload(run, action=action)

    @api.post("/api/evolution-runs/{run_id}/proposals/apply-accepted")
    def apply_accepted_evolution_run_proposals(run_id: str) -> dict[str, Any]:
        run = _proposal_run(store, run_id)
        action = apply_accepted_evolution_proposals(store, run)
        _persist_proposal_mutation(store, run)
        return _proposal_payload(run, action=action)

    @api.get("/api/evolution-runs/{run_id}/diff")
    def evolution_diff(run_id: str) -> dict[str, Any]:
        run = store.evolution_runs.get(run_id)
        if run is None:
            if run_id in store.evolution_batches:
                raise HTTPException(status_code=400, detail="batch does not support diff; select a child run")
            raise HTTPException(status_code=404, detail="run not found")
        return {"kind": "role_evolution_diff", "schema_version": 1, "run_id": run_id, "diffs": run.get("diff", [])}

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
        run = store.evolution_runs.get(run_id)
        if run is None:
            if run_id in store.evolution_batches:
                raise HTTPException(status_code=400, detail="batch does not support games; select a child run")
            raise HTTPException(status_code=404, detail="run not found")
        games = _evolution_games_for_query(run, phase=phase, side=side)
        statuses = _filter_values(status)
        if statuses is not None:
            games = [game for game in games if _match_filter(game.get("status", "completed"), statuses)]
        payload = {
            "kind": "role_evolution_games",
            "schema_version": 1,
            "run_id": run_id,
            "phase": phase,
            "side": side,
            "games": games,
        }
        if not any(key in request.query_params for key in ("limit", "offset", "status")):
            return payload
        page, pagination = _pagination(games, limit=limit, offset=offset)
        payload["games"] = page
        payload["pagination"] = pagination
        return payload

    @api.get("/api/evolution-runs/{run_id}/games/{game_id}/{detail_type}")
    def evolution_game_detail(
        run_id: str,
        game_id: str,
        detail_type: str,
        phase: str = "training",
        side: str | None = None,
    ) -> dict[str, Any]:
        run = store.evolution_runs.get(run_id)
        if run is None:
            if run_id in store.evolution_batches:
                raise HTTPException(status_code=400, detail="batch does not support game details; select a child run")
            raise HTTPException(status_code=404, detail="run not found")
        games = _evolution_games_for_query(run, phase=phase, side=side, include_details=True)
        game = next((item for item in games if item.get("game_id") == game_id or item.get("id") == game_id), None)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        if detail_type == "archive":
            return _sample_game_archive_payload(run_id, game_id, game, phase=phase, side=side)
        if detail_type == "decisions":
            return {
                "run_id": run_id,
                "game_id": game_id,
                "decisions": [
                    _normalize_decision(decision, index)
                    for index, decision in enumerate(game.get("decisions", []) or [], start=1)
                ],
            }
        if detail_type == "events":
            return {"run_id": run_id, "game_id": game_id, "events": [_normalize_event(event) for event in game.get("events", []) or []]}
        raise HTTPException(status_code=404, detail="detail type not found")

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
