from __future__ import annotations

import asyncio
from collections import deque
from typing import Protocol

from engine.models import ActionRequest, ActionResponse


class PlayerAgent(Protocol):
    async def act(self, request: ActionRequest) -> ActionResponse:
        """Return the player's response for a requested action."""


class HumanPlayer:
    """Player agent that waits for human input via submit()."""

    def __init__(self, player_id: int):
        self.player_id = player_id
        self._pending: asyncio.Future[ActionResponse] | None = None
        self._current_request: ActionRequest | None = None

    async def act(self, request: ActionRequest) -> ActionResponse:
        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()
        self._current_request = request
        try:
            return await self._pending
        finally:
            self._pending = None
            self._current_request = None

    def submit(self, response: ActionResponse) -> bool:
        """Submit the human's response. Returns True if accepted."""
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(response)
            return True
        return False

    @property
    def is_waiting(self) -> bool:
        return self._pending is not None and not self._pending.done()

    @property
    def current_request(self) -> ActionRequest | None:
        return self._current_request


class ScriptedAgent:
    """Small deterministic agent for tests and local rule simulations."""

    def __init__(self, responses=None, default: ActionResponse | None = None):
        self._responses = deque(responses or [])
        self.default = default
        self.requests: list[ActionRequest] = []

    def push(self, response: ActionResponse) -> None:
        self._responses.append(response)

    async def act(self, request: ActionRequest) -> ActionResponse:
        self.requests.append(request)
        if self._responses:
            return self._responses.popleft()
        if self.default is not None:
            return self.default
        return ActionResponse(request.action_type)
