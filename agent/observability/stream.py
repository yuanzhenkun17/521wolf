"""Debug WebSocket stream — real-time decision push to frontend.

A single module-level ``DecisionBroadcaster`` is activated per game.
The agent runtime pushes lightweight decision summaries after each
``trace_recorder.record(ctx)``; the FastAPI WebSocket endpoint relays
them to the frontend debug panel.
"""

from __future__ import annotations

import asyncio
from typing import Any

from agent.runtime.context import AgentContext


class DecisionBroadcaster:
    """Holds subscriber queues and fans out decision dicts."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._queues.discard(q)

    def broadcast(self, data: dict[str, Any]) -> None:
        for q in tuple(self._queues):
            q.put_nowait(data)


_active: DecisionBroadcaster | None = None


def set_broadcaster(bc: DecisionBroadcaster | None) -> None:
    global _active
    _active = bc


def get_broadcaster() -> DecisionBroadcaster | None:
    return _active


def stream_decision(ctx: AgentContext) -> dict[str, Any]:
    """Build a lightweight decision dict suitable for WebSocket push.

    Kept small on purpose — full trace is available via /api/games/{id}/archive.
    """
    return {
        "player_id": ctx.player_id,
        "role": ctx.role,
        "day": ctx.request.observation.day,
        "phase": ctx.request.phase.value,
        "action_type": ctx.request.action_type.value,
        "source": ctx.source,
        "confidence": round(ctx.confidence, 3),
        "target": ctx.response.target if ctx.response else None,
        "choice": ctx.response.choice if ctx.response else None,
        "public_text": (ctx.response.text or "") if ctx.response else "",
        "selected_skills": ctx.selected_skills,
        "errors": ctx.errors,
        "tot_enabled": ctx.tot_enabled,
        "tot_judge_reason": ctx.tot_judge_reason,
        "policy_adjustments": ctx.policy_adjustments,
    }
