from __future__ import annotations

from collections import deque
from typing import Protocol

from engine.models import ActionRequest, ActionResponse


class PlayerAgent(Protocol):
    async def act(self, request: ActionRequest) -> ActionResponse:
        """Return the player's response for a requested action."""


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

