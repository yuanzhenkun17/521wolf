from __future__ import annotations

import asyncio
import time
import unittest

from agent.runtime.model import AsyncRateLimiter, limit_model_adapter, rate_limit_model_adapter


class _SlowModel:
    def __init__(self) -> None:
        self.active = 0
        self.max_active = 0

    async def complete(self, messages: list[dict[str, str]], *, name: str = "") -> str:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return "ok"


class TestModelLimits(unittest.IsolatedAsyncioTestCase):
    async def test_limited_model_adapter_bounds_concurrency(self):
        model = _SlowModel()
        limited = limit_model_adapter(model, asyncio.Semaphore(2))

        await asyncio.gather(*(
            limited.complete([{"role": "user", "content": str(i)}])
            for i in range(8)
        ))

        self.assertLessEqual(model.max_active, 2)

    async def test_rate_limited_model_adapter_spaces_requests(self):
        model = _SlowModel()
        limited = rate_limit_model_adapter(model, AsyncRateLimiter(6000))

        start = time.monotonic()
        await asyncio.gather(*(
            limited.complete([{"role": "user", "content": str(i)}])
            for i in range(3)
        ))
        elapsed = time.monotonic() - start

        self.assertGreaterEqual(elapsed, 0.015)


if __name__ == "__main__":
    unittest.main()
