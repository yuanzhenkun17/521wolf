"""Lifecycle coordinator for UI backend live game sessions."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from typing import Any

from fastapi import HTTPException

from app.util.json import to_jsonable
from app.util.time import beijing_now_iso
from ui.backend.live_game import (
    LIVE_GAME_TERMINAL_STATUSES,
    BroadcastEventSink,
    LiveGameSession,
    live_game_heartbeat_timed_out,
)
from ui.backend.preflight import require_runtime_ready
from ui.backend.schemas import GameStartRequest


class _FanoutSink:
    def __init__(self, *sinks: Any) -> None:
        self._sinks = [sink for sink in sinks if sink is not None]

    def record_event(self, entry: Any) -> None:
        for sink in self._sinks:
            record = getattr(sink, "record_event", None)
            if callable(record):
                record(entry)

    def record_decision(self, decision: Any) -> None:
        for sink in self._sinks:
            record = getattr(sink, "record_decision", None)
            if callable(record):
                record(decision)


class LiveGameLifecycleCoordinator:
    """Owns live game start, stop, watchdog, and terminal persistence policy."""

    def __init__(self, store: Any) -> None:
        self._store = store

    async def start_game(self, request: GameStartRequest) -> dict[str, Any]:
        await require_runtime_ready(self._store, scope="game_start")
        game_id = f"ui_{uuid.uuid4().hex[:12]}"
        skill_dir = self._store.skill_dir_for_request(request)
        return await self.start_live_game(game_id=game_id, request=request, skill_dir=skill_dir)

    async def start_live_game(self, *, game_id: str, request: GameStartRequest, skill_dir: str | None) -> dict[str, Any]:
        store = self._store
        store._clear_game_deleted(game_id)
        human_player_id = request.human_player_id
        if human_player_id is not None and (human_player_id < 1 or human_player_id > request.player_count):
            raise HTTPException(status_code=400, detail="human_player_id must be a valid player seat")
        try:
            model_runtime = store.settings_model_runtime_for_scope(
                "game_decision",
                model_profile_id=request.model_profile_id,
            )
            runtime_model = store.model_for_run(
                scope="game_decision",
                model_profile_id=request.model_profile_id,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "game_model_profile_invalid",
                    "message": "游戏模型 Profile 不可用。",
                    "detail": str(exc),
                    "model_profile_id": request.model_profile_id,
                },
            ) from exc

        from app.lib.game import create_agents, create_engine
        from app.lib.store import AgentDecisionRecorder
        from engine import STANDARD_12, GameLogger, assign_roles

        config = replace(STANDARD_12, max_days=request.max_days, enable_sheriff=request.enable_sheriff)
        roles = assign_roles(config, seed=request.seed)
        run_metadata = {
            "mode": "play" if human_player_id is not None else "watch",
            "source_run_id": game_id,
            "ruleset_version": "werewolf_12p_v1",
        }
        if isinstance(model_runtime, dict) and model_runtime:
            run_metadata["model_id"] = model_runtime.get("model_id")
            run_metadata["model_config_hash"] = model_runtime.get("model_config_hash")
            run_metadata["model_runtime"] = to_jsonable(dict(model_runtime.get("model_runtime") or model_runtime))
        persistence = store._create_game_persistence(game_id, run_metadata=run_metadata)
        event_sink = BroadcastEventSink()
        db_event_sink = persistence.create_event_sink()
        db_decision_sink = persistence.create_decision_sink()
        recorder = AgentDecisionRecorder(sink=_FanoutSink(event_sink, db_decision_sink))
        agents = create_agents(
            roles,
            client=runtime_model,
            decision_recorder=recorder,
            game_id=game_id,
            skill_dir=skill_dir,
            human_player_id=human_player_id,
            paths=store.paths,
        )
        logger = GameLogger(sink=_FanoutSink(event_sink, db_event_sink))
        engine = create_engine(
            roles,
            agents,
            seed=request.seed or 0,
            max_days=request.max_days,
            enable_sheriff=request.enable_sheriff,
            logger=logger,
        )
        session = LiveGameSession(
            game_id=game_id,
            request=request,
            engine=engine,
            recorder=recorder,
            human=agents.get(human_player_id) if human_player_id is not None else None,
            event_sink=event_sink,
            skill_dir=skill_dir,
            model_runtime=model_runtime,
        )
        setattr(session, "persistence", persistence)
        self.persist_start(session)
        store.live_sessions[game_id] = session
        session.task = asyncio.create_task(self.run_live_session(game_id))
        snapshot = session.snapshot()
        store.games[game_id] = snapshot
        store.invalidate_game_history_index()
        return snapshot

    async def run_live_session(self, game_id: str) -> None:
        store = self._store
        session = store.live_sessions.get(game_id)
        if session is None:
            return
        try:
            await session.run()
            if store._is_game_deleted(game_id):
                return
            snapshot = session.snapshot()
            store.games[game_id] = snapshot
            self.persist_session(session, snapshot)
        finally:
            if store.live_sessions.get(game_id) is session and session.status in LIVE_GAME_TERMINAL_STATUSES:
                store.live_sessions.pop(game_id, None)

    def check_watchdog(self, *, timeout_seconds: float | None = None) -> list[dict[str, Any]]:
        store = self._store
        resolved_timeout = (
            timeout_seconds if timeout_seconds is not None else store._live_game_heartbeat_timeout_seconds()
        )
        interrupted: list[dict[str, Any]] = []
        for game_id, session in list(store.live_sessions.items()):
            status = str(getattr(session, "status", "") or "").lower()
            if status in LIVE_GAME_TERMINAL_STATUSES:
                continue
            if not hasattr(session, "mark_interrupted"):
                continue
            if not live_game_heartbeat_timed_out(
                getattr(session, "last_heartbeat_at", None),
                timeout_seconds=resolved_timeout,
            ):
                continue
            if self.live_session_waiting_for_human_within_timeout(session):
                continue
            session.mark_interrupted(
                "live game heartbeat timed out",
                stage="live_game.watchdog",
                kind="live_game_interrupted",
                timeout_seconds=resolved_timeout,
            )
            snapshot = session.snapshot()
            store.games[game_id] = snapshot
            try:
                self.persist_session(session, snapshot)
            except Exception:
                # Keep the interrupted state visible even if final persistence fails.
                pass
            store.live_sessions.pop(game_id, None)
            interrupted.append(snapshot)
        if interrupted:
            store.invalidate_game_history_index()
        return interrupted

    def live_session_waiting_for_human_within_timeout(self, session: Any) -> bool:
        human = getattr(session, "human", None)
        if human is None:
            return False
        try:
            is_waiting = bool(getattr(human, "is_waiting", False))
        except Exception:
            return False
        if not is_waiting:
            return False
        try:
            human_timeout = float(getattr(human, "timeout_seconds"))
        except (TypeError, ValueError):
            return False
        return not live_game_heartbeat_timed_out(
            getattr(session, "last_heartbeat_at", None),
            timeout_seconds=human_timeout,
        )

    def stop_game(self, game_id: str) -> dict[str, Any]:
        store = self._store
        live = store.live_sessions.get(game_id)
        if live is not None:
            live.cancel()
            snapshot = live.snapshot()
            store.games[game_id] = snapshot
            if live.task is None or live.task.done():
                self.persist_session(live, snapshot)
            return snapshot
        game = store.get_game(game_id)
        if game is None:
            now = beijing_now_iso()
            return {
                "game_id": game_id,
                "status": "cancelled",
                "stop_requested": True,
                "cancelled": True,
                "interrupted": False,
                "failed": False,
                "cancelled_at": now,
                "finished_at": now,
                "error": "cancelled",
                "players": [],
                "logs": [],
                "decisions": [],
            }
        now = beijing_now_iso()
        stopped = {
            **game,
            "status": "cancelled",
            "stop_requested": True,
            "cancelled": True,
            "interrupted": False,
            "failed": False,
            "cancelled_at": game.get("cancelled_at") or now,
            "finished_at": game.get("finished_at") or now,
            "error": game.get("error") or "cancelled",
        }
        store.games[game_id] = stopped
        store._persist_snapshot_to_pg(stopped)
        return stopped

    def persist_start(self, session: LiveGameSession) -> None:
        self._store._persist_snapshot_to_pg(
            session.snapshot(),
            persistence=getattr(session, "persistence", None),
        )

    def persist_session(self, session: LiveGameSession, snapshot: dict[str, Any] | None = None) -> None:
        store = self._store
        snapshot = snapshot or session.snapshot()
        terminal = str(snapshot.get("status") or session.status or "").lower() in LIVE_GAME_TERMINAL_STATUSES
        if terminal:
            with session.persist_lock:
                if session.files_written:
                    return
                session.files_written = True
        try:
            store._persist_snapshot_to_pg(
                snapshot,
                persistence=getattr(session, "persistence", None),
            )
            if terminal:
                persistence = getattr(session, "persistence", None)
                close = getattr(persistence, "close", None)
                if callable(close):
                    close()
        except Exception:
            if terminal:
                with session.persist_lock:
                    session.files_written = False
            raise
        finally:
            store.invalidate_game_history_index()


__all__ = ["LiveGameLifecycleCoordinator"]
