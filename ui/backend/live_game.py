"""Live game session primitives for the UI backend."""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from app.util.json import to_jsonable
from app.util.time import BEIJING_TZ, beijing_now, beijing_now_iso
from ui.backend.schemas import GameStartRequest, HumanActionRequest
from ui.backend.serializers import (
    _engine_events,
    _normalize_decision,
    _normalize_event,
    _pending_action_payload,
    _recorder_decisions,
    _review_live_result,
    _role_label,
    _ui_pending_action,
    _vote_tally,
    _waiting_for_pending,
)
from ui.backend.sse import _event_id

_log = logging.getLogger(__name__)

LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS = 180.0
LIVE_GAME_TERMINAL_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


def _parse_heartbeat(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=BEIJING_TZ)
    return parsed.astimezone(BEIJING_TZ)


def live_game_heartbeat_timed_out(
    last_heartbeat_at: str | None,
    *,
    now: datetime | None = None,
    timeout_seconds: float = LIVE_GAME_HEARTBEAT_TIMEOUT_SECONDS,
) -> bool:
    heartbeat = _parse_heartbeat(last_heartbeat_at)
    if heartbeat is None:
        return True
    current = now or beijing_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=BEIJING_TZ)
    return (current.astimezone(BEIJING_TZ) - heartbeat).total_seconds() > timeout_seconds


class BroadcastEventSink:
    """Per-game synchronous event broadcaster for live SSE subscribers."""

    def __init__(self, *, max_queue_size: int = 512, max_backlog: int = 2048) -> None:
        self.max_queue_size = max_queue_size
        self.max_backlog = max_backlog
        self.backlog: list[dict[str, Any]] = []
        self.subscribers: set[asyncio.Queue] = set()
        self.closed = False
        self.terminal_payload: dict[str, Any] | None = None
        self.terminal_envelope: dict[str, Any] | None = None
        self.next_event_id = 1
        self.on_activity: Callable[[], None] | None = None

    def record_event(self, entry: Any) -> None:
        payload = _normalize_event(entry.to_dict() if hasattr(entry, "to_dict") else entry)
        self._publish("log", payload, store=True)

    def publish(self, event: str, payload: Any) -> None:
        self._publish(event, payload, store=False)

    def record_decision(self, decision: Any) -> None:
        payload = _normalize_decision(
            decision.to_dict() if hasattr(decision, "to_dict") else decision,
            self.next_event_id,
        )
        self._publish("decision", payload, store=True)

    def close(self, payload: dict[str, Any], *, touch: bool = True) -> None:
        if self.closed:
            return
        self.closed = True
        self.terminal_payload = payload
        self.terminal_envelope = self._publish("done", payload, store=False, touch=touch)

    def subscribe(self, *, last_event_id: int | None = None) -> asyncio.Queue:
        self.touch()
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.max_queue_size)
        self.subscribers.add(queue)
        cursor = last_event_id or 0
        for envelope in self.backlog:
            if _event_id(envelope) > cursor:
                self._put(queue, envelope)
        if self.closed and self.terminal_envelope is not None and _event_id(self.terminal_envelope) > cursor:
            self._put(queue, self.terminal_envelope)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.subscribers.discard(queue)

    def _broadcast(self, envelope: dict[str, Any]) -> None:
        for queue in list(self.subscribers):
            self._put(queue, envelope)

    def touch(self) -> None:
        if self.on_activity is None:
            return
        try:
            self.on_activity()
        except Exception:
            _log.warning("live event activity callback failed", exc_info=True)

    def _publish(self, event: str, payload: Any, *, store: bool, touch: bool = True) -> dict[str, Any]:
        if touch:
            self.touch()
        envelope = {
            "id": self.next_event_id,
            "event": event,
            "payload": to_jsonable(payload),
        }
        self.next_event_id += 1
        if store:
            self.backlog.append(envelope)
            if len(self.backlog) > self.max_backlog:
                del self.backlog[: len(self.backlog) - self.max_backlog]
        self._broadcast(envelope)
        return envelope

    def _put(self, queue: asyncio.Queue, envelope: dict[str, Any]) -> None:
        try:
            queue.put_nowait(envelope)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                queue.put_nowait(envelope)
            except asyncio.QueueFull:
                self.unsubscribe(queue)


@dataclass
class LiveGameSession:
    game_id: str
    request: GameStartRequest
    engine: Any
    recorder: Any
    human: Any | None
    event_sink: BroadcastEventSink
    skill_dir: str | None = None
    task: asyncio.Task | None = None
    status: str = "running"
    winner: str | None = None
    review: dict[str, Any] | None = None
    error: str | None = None
    started_at: str = field(default_factory=beijing_now_iso)
    finished_at: str | None = None
    files_written: bool = False
    stop_requested: bool = False
    cancelled: bool = False
    cancelled_at: str | None = None
    interrupted: bool = False
    interrupted_at: str | None = None
    last_heartbeat_at: str = field(default_factory=beijing_now_iso)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    persist_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.event_sink.on_activity = self.heartbeat

    def heartbeat(self, *, timestamp: str | None = None) -> str:
        self.last_heartbeat_at = timestamp or beijing_now_iso()
        return self.last_heartbeat_at

    async def run(self) -> None:
        self.heartbeat()
        try:
            winner = await self.engine.run_until_finished()
            self.winner = winner.value if hasattr(winner, "value") else str(winner)
            self.status = "completed"
        except asyncio.CancelledError:
            if self.interrupted or self.status == "interrupted":
                self.status = "interrupted"
                self.interrupted = True
                self.error = self.error or "interrupted"
            else:
                self.status = "cancelled"
                self.error = "cancelled"
                self.stop_requested = True
                self.cancelled = True
                self.cancelled_at = self.cancelled_at or beijing_now_iso()
        except Exception as exc:  # pragma: no cover - defensive runtime failure path
            self.status = "failed"
            self.error = str(exc)
            self.winner = "error"
            self.heartbeat()
            self.diagnostics.append(
                {
                    "kind": "live_game_error",
                    "stage": "live_session.run",
                    "message": str(exc),
                    "exception_type": type(exc).__name__,
                    "at": beijing_now_iso(),
                }
            )
        finally:
            if not self.interrupted:
                self.heartbeat()
            self.finished_at = self.finished_at or beijing_now_iso()
            if self.winner is None and getattr(self.engine.state, "winner", None) is not None:
                self.winner = self.engine.state.winner.value
            self.review = _review_live_result(self)
            self.event_sink.close(self.snapshot(), touch=not self.interrupted)

    def cancel(self) -> None:
        now = beijing_now_iso()
        self.heartbeat(timestamp=now)
        self.stop_requested = True
        self.cancelled = True
        self.status = "cancelled"
        self.error = "cancelled"
        self.cancelled_at = self.cancelled_at or now
        self.finished_at = self.finished_at or now
        try:
            self.event_sink.close(self.snapshot())
        except Exception:
            _log.warning("failed to close event sink for %s", self.game_id, exc_info=True)
        if self.task is not None and not self.task.done():
            self.task.cancel()

    def mark_interrupted(
        self,
        reason: str,
        *,
        stage: str = "live_game.watchdog",
        kind: str = "live_game_interrupted",
        timeout_seconds: float | None = None,
    ) -> None:
        if self.status in LIVE_GAME_TERMINAL_STATUSES and self.status != "interrupted":
            return
        now = beijing_now_iso()
        last_heartbeat_at = self.last_heartbeat_at
        self.status = "interrupted"
        self.interrupted = True
        self.cancelled = False
        self.stop_requested = False
        self.error = self.error or reason
        self.interrupted_at = self.interrupted_at or now
        self.finished_at = self.finished_at or now
        self._append_diagnostic(
            {
                "kind": kind,
                "stage": stage,
                "message": reason,
                "last_heartbeat_at": last_heartbeat_at,
                "timeout_seconds": timeout_seconds,
                "at": self.interrupted_at,
            }
        )
        try:
            self.event_sink.close(self.snapshot(), touch=False)
        except Exception:
            _log.warning("failed to close interrupted event sink for %s", self.game_id, exc_info=True)
        if self.task is not None and not self.task.done():
            self.task.cancel()

    def _append_diagnostic(self, diagnostic: dict[str, Any]) -> None:
        item = {key: value for key, value in diagnostic.items() if value is not None}
        identity = (item.get("kind"), item.get("stage"), item.get("message"))
        for existing in self.diagnostics:
            if not isinstance(existing, dict):
                continue
            if (existing.get("kind"), existing.get("stage"), existing.get("message")) == identity:
                return
        self.diagnostics.append(item)

    def submit(self, request: HumanActionRequest) -> bool:
        self.heartbeat()
        if self.human is None:
            return False
        current = self.human.current_request
        if current is None:
            return False
        action_type = request.action_type or current.action_type.value
        if action_type != current.action_type.value:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail=f"Expected action_type {current.action_type.value}")

        from app.lib.store import DecisionRecord
        from engine import ActionResponse

        response = ActionResponse(
            current.action_type,
            target=request.target,
            choice=request.choice,
            text=request.text,
        )
        decision = DecisionRecord(
            action_type=current.action_type,
            day=current.observation.day,
            phase=current.phase.value if hasattr(current.phase, "value") else str(current.phase),
            player_id=current.player_id,
            role=current.observation.self_role.value,
            candidates=list(current.candidates),
            selected_target=request.target,
            selected_choice=request.choice,
            public_text=request.text,
            private_reasoning="human input",
            confidence=1.0,
            source="human",  # type: ignore[arg-type]
        )
        response.decision_id = decision.decision_id
        accepted = self.human.submit(response)
        if accepted:
            self.heartbeat()
            self.recorder.record(decision)
        return accepted

    def pending_action(self) -> dict[str, Any] | None:
        if self.human is None:
            return None
        current = self.human.current_request
        if current is None or not self.human.is_waiting:
            return None
        return _pending_action_payload(current)

    def result(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "seed": self.request.seed,
            "winner": self.winner,
            "player_roles": {pid: state.role.value for pid, state in self.engine.state.players.items()},
            "events": _engine_events(self.engine),
            "decisions": _recorder_decisions(self.recorder),
            "status": self.status,
            "stop_requested": self.stop_requested,
            "cancelled": self.cancelled,
            "interrupted": self.interrupted,
            "failed": self.status == "failed",
            "cancelled_at": self.cancelled_at,
            "interrupted_at": self.interrupted_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "review": self.review,
            "diagnostics": list(self.diagnostics),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }

    def snapshot(self) -> dict[str, Any]:
        pending = self.pending_action()
        events = [_normalize_event(e) for e in _engine_events(self.engine)]
        decisions = [_normalize_decision(d, index) for index, d in enumerate(_recorder_decisions(self.recorder), start=1)]
        players = []
        for player_id, player in sorted(self.engine.state.players.items()):
            players.append(
                {
                    "id": player_id,
                    "seat": player_id,
                    "name": f"{player_id}号",
                    "role": player.role.value,
                    "role_hint": _role_label(player.role.value),
                    "team": player.team.value,
                    "alive": player.alive,
                    "is_sheriff": player_id == self.engine.state.sheriff_id,
                    "is_human": player_id == self.request.human_player_id,
                    "role_state": to_jsonable(player.role_state),
                }
            )
        phase = self.engine.state.phase.value if hasattr(self.engine.state.phase, "value") else str(self.engine.state.phase)
        role_counts = dict(Counter(player["role"] for player in players))
        waiting_for = _waiting_for_pending(pending)
        return {
            "game_id": self.game_id,
            "log_name": self.game_id,
            "status": self.status,
            "stop_requested": self.stop_requested,
            "cancelled": self.cancelled,
            "interrupted": self.interrupted,
            "failed": self.status == "failed",
            "cancelled_at": self.cancelled_at,
            "interrupted_at": self.interrupted_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "mode": "play" if self.request.human_player_id is not None else "watch",
            "winner": self.winner,
            "seed": self.request.seed,
            "max_days": self.request.max_days,
            "enable_sheriff": self.request.enable_sheriff,
            "skill_dir": self.skill_dir,
            "human_player_id": self.request.human_player_id,
            "player_count": len(players),
            "day": self.engine.state.day,
            "phase": phase,
            "sheriff_id": self.engine.state.sheriff_id,
            "players": players,
            "logs": events,
            "events": events,
            "decisions": decisions,
            "review": self.review,
            "diagnostics": list(self.diagnostics),
            "waiting_for": waiting_for,
            "pending_action": _ui_pending_action(pending),
            "pending_human_action": pending,
            "current_speaker_id": pending.get("player_id") if pending and waiting_for == "speech" else None,
            "vote_tally": _vote_tally(
                decisions,
                current_day=self.engine.state.day,
                current_phase=phase,
                pending_action=pending,
            ),
            "role_counts": role_counts,
            "role_skill_dirs": dict(self.request.role_versions),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "config": {
                "seed": self.request.seed,
                "max_days": self.request.max_days,
                "enable_sheriff": self.request.enable_sheriff,
                "skill_dir": self.skill_dir,
                "role_versions": dict(self.request.role_versions),
                "role_skill_dirs": dict(self.request.role_versions),
                "player_count": self.request.player_count,
                "human_player_id": self.request.human_player_id,
            },
            "error": self.error,
        }
