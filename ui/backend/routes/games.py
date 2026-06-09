"""Game routes for the UI backend."""

from __future__ import annotations

from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ui.backend.schemas import GameStartRequest, HumanActionRequest
from ui.backend.serializers import _archive_payload, _player_view_snapshot, _player_view_sse_payload
from ui.backend.sse import sse_after_cursor, stream_queue_sse
from ui.backend.task_state import (
    _filter_values,
    _history_query_requested,
    _last_event_id_from_request,
)


_HISTORY_SOURCE_LABELS = {"normal": "人机/玩家", "benchmark": "评测", "evolution": "进化"}
_HISTORY_SOURCE_PHASE_LABELS = {"training": "训练", "battle": "对战", "baseline": "基线", "candidate": "候选"}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _clean_role_versions(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(role): str(version)
        for role, version in value.items()
        if role is not None and version is not None and str(version) != ""
    }


def _history_evidence_source(payload: dict[str, Any]) -> dict[str, Any]:
    existing = payload.get("evidence_source") if isinstance(payload.get("evidence_source"), dict) else {}
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    source = str(_first_present(
        existing.get("log_source"),
        payload.get("log_source"),
        config.get("log_source"),
        "normal",
    ))
    source_phase = _first_present(existing.get("source_phase"), payload.get("source_phase"), config.get("source_phase"))
    role_versions = _clean_role_versions(
        _first_present(
            existing.get("role_versions"),
            payload.get("role_versions"),
            config.get("role_versions"),
            payload.get("role_skill_dirs"),
            config.get("role_skill_dirs"),
        )
    )
    return {
        "log_source": source,
        "log_source_label": _first_present(
            existing.get("log_source_label"),
            payload.get("log_source_label"),
            config.get("log_source_label"),
            _HISTORY_SOURCE_LABELS.get(source),
            source,
        ),
        "source_run_id": _first_present(existing.get("source_run_id"), payload.get("source_run_id"), config.get("source_run_id")),
        "source_phase": source_phase,
        "source_phase_label": _first_present(
            existing.get("source_phase_label"),
            payload.get("source_phase_label"),
            config.get("source_phase_label"),
            _HISTORY_SOURCE_PHASE_LABELS.get(str(source_phase or "")),
        ),
        "seed": _first_present(existing.get("seed"), payload.get("seed"), config.get("seed")),
        "role_versions": role_versions,
    }


def _history_detail_payload(game: dict[str, Any]) -> dict[str, Any]:
    payload = dict(game)
    logs = payload.get("logs") if isinstance(payload.get("logs"), list) else payload.get("events")
    if isinstance(logs, list):
        payload["logs"] = logs
        payload["event_count"] = payload.get("event_count", len(logs))
    decisions = payload.get("decisions")
    if isinstance(decisions, list):
        payload["decision_count"] = payload.get("decision_count", len(decisions))
    payload.pop("events", None)
    context = _history_evidence_source(payload)
    payload["evidence_source"] = context
    for key in ("log_source", "log_source_label", "source_run_id", "source_phase", "source_phase_label", "seed"):
        if payload.get(key) is None or payload.get(key) == "":
            payload[key] = context[key]
    if not isinstance(payload.get("role_versions"), dict) or not payload.get("role_versions"):
        payload["role_versions"] = dict(context["role_versions"])
    payload["detail_view"] = "history"
    return payload


def register_game_routes(api: FastAPI, store: Any) -> None:
    @api.post("/api/games")
    async def start_game(request: GameStartRequest) -> dict[str, Any]:
        return _player_view_snapshot(await store.start_game(request))

    @api.get("/api/games")
    def list_games(
        request: Request,
        limit: int | None = Query(default=None, ge=0, le=1000),
        offset: int = Query(default=0, ge=0),
        source: str | None = Query(default=None),
        status: str | None = Query(default=None),
    ) -> dict[str, Any]:
        if not _history_query_requested(request):
            return {"games": store.list_games()}
        return store.query_game_history(
            sources=_filter_values(source),
            statuses=_filter_values(status),
            limit=limit,
            offset=offset,
        )

    @api.get("/api/games/{game_id}")
    def get_game(
        game_id: str,
        advance: int = Query(default=0),
        view: str | None = Query(default=None),
    ) -> dict[str, Any]:
        del advance
        normalized_view = str(view or "").lower()
        if normalized_view == "history-shell":
            shell = store.get_game_history_shell(game_id)
            if shell is None:
                raise HTTPException(status_code=404, detail="game not found")
            return shell
        game = store.get_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        view_game = _player_view_snapshot(game)
        if normalized_view == "history":
            return _history_detail_payload(view_game)
        return view_game

    @api.get("/api/games/{game_id}/phase")
    def get_game_phase_detail(
        game_id: str,
        day: int = Query(default=1, ge=1),
        phase: str = Query(default="setup"),
        log_offset: int = Query(default=0, ge=0),
        log_limit: int | None = Query(default=300, ge=1, le=1000),
        decision_offset: int = Query(default=0, ge=0),
        decision_limit: int | None = Query(default=200, ge=1, le=500),
    ) -> dict[str, Any]:
        detail = store.get_game_phase_detail(
            game_id,
            day=day,
            phase=phase,
            log_offset=log_offset,
            log_limit=log_limit,
            decision_offset=decision_offset,
            decision_limit=decision_limit,
        )
        if detail is None:
            raise HTTPException(status_code=404, detail="game not found")
        return detail

    @api.get("/api/games/{game_id}/flow-data")
    def get_game_flow_data(game_id: str) -> dict[str, Any]:
        detail = store.get_game_flow_data(game_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="game not found")
        return detail

    @api.get("/api/games/{game_id}/replay")
    def get_game_replay(
        game_id: str,
        cursor: int = Query(default=0, ge=0),
        limit: int | None = Query(default=500, ge=1, le=2000),
    ) -> dict[str, Any]:
        detail = store.get_game_replay(game_id, cursor=cursor, limit=limit)
        if detail is None:
            raise HTTPException(status_code=404, detail="game not found")
        return detail

    @api.delete("/api/games/{game_id}")
    def delete_game(game_id: str, force: bool = Query(default=False)) -> dict[str, Any]:
        return store.delete_game(game_id, force=force)

    @api.get("/api/games/{game_id}/archive")
    def get_game_archive(game_id: str) -> dict[str, Any]:
        game = store.get_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        view_game = _player_view_snapshot(game)
        return _archive_payload(game_id, view_game)

    @api.get("/api/games/{game_id}/review")
    def get_game_review(game_id: str) -> dict[str, Any]:
        review = store.get_game_review(game_id)
        if review is None:
            raise HTTPException(status_code=404, detail="game not found")
        return review

    @api.get("/api/games/{game_id}/human-action")
    def get_human_action(game_id: str) -> dict[str, Any] | None:
        pending = store.get_human_action(game_id)
        game = store.get_game(game_id)
        if pending is None:
            pending = game.get("pending_human_action") if game else None
        if pending is None:
            return None
        if game is None:
            return pending
        view_game = _player_view_snapshot({**game, "pending_human_action": pending})
        return view_game.get("pending_human_action")

    @api.post("/api/games/{game_id}/action")
    def submit_human_action(game_id: str, request: HumanActionRequest) -> dict[str, Any]:
        return _player_view_snapshot(store.submit_human_action(game_id, request))

    @api.post("/api/games/{game_id}/stop")
    def stop_game(game_id: str) -> dict[str, Any]:
        return _player_view_snapshot(store.stop_game(game_id))

    @api.get("/api/games/{game_id}/events")
    def game_events(game_id: str, request: Request) -> StreamingResponse:
        game = store.get_game(game_id)
        session = store.live_sessions.get(game_id)
        if session is None and game is None:
            raise HTTPException(status_code=404, detail="game not found")
        last_event_id = _last_event_id_from_request(request)

        async def stream() -> AsyncIterator[str]:
            if session is None:
                event_id = 0
                view_game = _player_view_snapshot(game)
                for event in game.get("events", []):
                    event_id += 1
                    payload = _player_view_sse_payload("log", event, game)
                    if payload is None:
                        continue
                    frame = sse_after_cursor("log", payload, event_id=event_id, last_event_id=last_event_id)
                    if frame is not None:
                        yield frame
                for decision in game.get("decisions", []):
                    event_id += 1
                    payload = _player_view_sse_payload("decision", decision, game)
                    if payload is None:
                        continue
                    frame = sse_after_cursor("decision", payload, event_id=event_id, last_event_id=last_event_id)
                    if frame is not None:
                        yield frame
                event_id += 1
                frame = sse_after_cursor("done", view_game, event_id=event_id, last_event_id=last_event_id)
                if frame is not None:
                    yield frame
                return

            queue = session.event_sink.subscribe(last_event_id=last_event_id)
            try:
                async for frame in stream_queue_sse(
                    queue,
                    ping_payload=lambda: {
                        "game_id": game_id,
                        "status": session.status,
                        "last_heartbeat_at": session.last_heartbeat_at,
                    },
                    event_name=lambda envelope: str(envelope.get("event") or "message"),
                    payload=lambda envelope: _player_view_sse_payload(
                        str(envelope.get("event") or "message"),
                        envelope.get("payload"),
                        session.snapshot(),
                    ),
                    terminal=lambda _envelope, event_name: event_name == "done",
                    skip_none_payload=True,
                ):
                    yield frame
            finally:
                session.event_sink.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream")
