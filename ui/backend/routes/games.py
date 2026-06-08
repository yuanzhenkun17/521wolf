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
    def get_game(game_id: str, advance: int = Query(default=0)) -> dict[str, Any]:
        game = store.get_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        return _player_view_snapshot(game)

    @api.get("/api/games/{game_id}/archive")
    def get_game_archive(game_id: str) -> dict[str, Any]:
        game = store.get_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        view_game = _player_view_snapshot(game)
        return _archive_payload(game_id, view_game)

    @api.get("/api/games/{game_id}/review")
    def get_game_review(game_id: str) -> dict[str, Any]:
        game = store.get_game(game_id)
        if game is None:
            raise HTTPException(status_code=404, detail="game not found")
        view_game = _player_view_snapshot(game)
        return view_game.get("review") or {
            "game_id": game_id,
            "winner": view_game.get("winner"),
            "review_status": "暂无复盘报告",
            "notes": [],
        }

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
