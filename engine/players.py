from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Protocol

from engine.models import ActionRequest, ActionResponse

_log = logging.getLogger(__name__)


class PlayerAgent(Protocol):
    async def act(self, request: ActionRequest) -> ActionResponse:
        """Return the player's response for a requested action."""


class HumanPlayer:
    """Player agent that waits for human input via submit().

    Parameters
    ----------
    player_id:
        Seat number of this player.
    timeout_seconds:
        Maximum seconds to wait for the human's response.
        After timeout, a minimal fallback response is returned so the
        game can continue.  The ``ask()`` retry mechanism in
        ``engine.actions`` provides a second chance; if that also
        times out, ``ask()`` uses its own default action (typically
        abstain / skip).
    """

    DEFAULT_TIMEOUT = 300  # 5 minutes

    def __init__(self, player_id: int, *, timeout_seconds: float | None = None):
        self.player_id = player_id
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else self.DEFAULT_TIMEOUT
        self._pending: asyncio.Future[ActionResponse] | None = None
        self._current_request: ActionRequest | None = None
        self._timed_out_count: int = 0

    async def act(self, request: ActionRequest) -> ActionResponse:
        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()
        self._current_request = request
        try:
            return await asyncio.wait_for(self._pending, timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            self._timed_out_count += 1
            _log.warning(
                "HumanPlayer %d timed out after %.0fs for %s (timeout #%d)",
                self.player_id,
                self.timeout_seconds,
                request.action_type.value,
                self._timed_out_count,
            )
            return ActionResponse(
                action_type=request.action_type,
                text="(操作超时)",
            )
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

    @property
    def timed_out_count(self) -> int:
        """Number of times this player has timed out in total."""
        return self._timed_out_count


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
