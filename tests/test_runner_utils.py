"""Tests for ui.backend.runner_utils — shared runner utilities."""

import asyncio
import unittest

from ui.backend.runner_utils import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RETRY_WAIT_BASE,
    RunnerStatus,
    retry_on_rate_limit,
    sse_events_stream,
)


class RunnerStatusTests(unittest.TestCase):
    """Tests for the RunnerStatus enum."""

    def test_queued_value(self):
        self.assertEqual(RunnerStatus.QUEUED.value, "queued")

    def test_running_value(self):
        self.assertEqual(RunnerStatus.RUNNING.value, "running")

    def test_completed_value(self):
        self.assertEqual(RunnerStatus.COMPLETED.value, "completed")

    def test_failed_value(self):
        self.assertEqual(RunnerStatus.FAILED.value, "failed")

    def test_paused_value(self):
        self.assertEqual(RunnerStatus.PAUSED.value, "paused")

    def test_rate_limited_value(self):
        self.assertEqual(RunnerStatus.RATE_LIMITED.value, "rate_limited")

    def test_active_statuses_contains_queued_running_rate_limited(self):
        active = RunnerStatus.active_statuses()
        self.assertIn("queued", active)
        self.assertIn("running", active)
        self.assertIn("rate_limited", active)
        self.assertEqual(len(active), 3)

    def test_terminal_statuses_contains_completed_failed(self):
        terminal = RunnerStatus.terminal_statuses()
        self.assertIn("completed", terminal)
        self.assertIn("failed", terminal)
        self.assertEqual(len(terminal), 2)

    def test_active_and_terminal_are_disjoint(self):
        active = RunnerStatus.active_statuses()
        terminal = RunnerStatus.terminal_statuses()
        self.assertEqual(set(active) & set(terminal), set())

    def test_runner_status_is_str_enum(self):
        """RunnerStatus values should behave as strings."""
        self.assertIsInstance(RunnerStatus.QUEUED, str)
        self.assertEqual(RunnerStatus.QUEUED, "queued")


class DefaultRetryParamsTests(unittest.TestCase):
    """Tests for the default retry constants."""

    def test_default_max_retries_is_5(self):
        self.assertEqual(DEFAULT_MAX_RETRIES, 5)

    def test_default_retry_wait_base_is_30(self):
        self.assertEqual(DEFAULT_RETRY_WAIT_BASE, 30)


class RetryOnRateLimitTests(unittest.TestCase):
    """Tests for the retry_on_rate_limit async helper."""

    def test_returns_result_on_success(self):
        async def successful_fn():
            return 42

        result = asyncio.run(retry_on_rate_limit(successful_fn, max_retries=3))
        self.assertEqual(result, 42)

    def test_raises_non_rate_limit_error_immediately(self):
        class CustomError(Exception):
            pass

        async def failing_fn():
            raise CustomError("not a rate limit error")

        with self.assertRaises(CustomError):
            asyncio.run(retry_on_rate_limit(failing_fn, max_retries=3))

    def test_retries_on_rate_limit_error(self):
        """retry_on_rate_limit should retry on 429 errors and succeed on second attempt."""
        call_count = 0

        async def eventually_successful_fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("429 rate limit exceeded")
            return "success"

        result = asyncio.run(
            retry_on_rate_limit(eventually_successful_fn, max_retries=3, wait_base=0)
        )
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 2)

    def test_exhausts_retries_on_persistent_rate_limit(self):
        """After max_retries, the last rate-limit error should be raised."""
        async def always_rate_limited():
            raise Exception("429 rate limit exceeded")

        with self.assertRaises(Exception) as ctx:
            asyncio.run(
                retry_on_rate_limit(always_rate_limited, max_retries=2, wait_base=0)
            )
        self.assertIn("429", str(ctx.exception))

    def test_on_rate_limited_callback_is_called(self):
        """The on_rate_limited callback should be invoked between retries."""
        callback_calls = []

        def on_rate_limited_cb(run_id, attempt, max_retries):
            callback_calls.append((run_id, attempt, max_retries))

        call_count = 0

        async def eventually_ok():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("429 too many requests")
            return "ok"

        result = asyncio.run(
            retry_on_rate_limit(
                eventually_ok,
                max_retries=3,
                wait_base=0,
                run_id="test_run",
                on_rate_limited=on_rate_limited_cb,
            )
        )
        self.assertEqual(result, "ok")
        self.assertEqual(len(callback_calls), 1)
        self.assertEqual(callback_calls[0][0], "test_run")

    def test_on_final_failure_callback_on_non_rate_limit_error(self):
        """on_final_failure should be called when a non-rate-limit error occurs."""
        failure_calls = []

        def on_final_failure_cb(run_id, exc):
            failure_calls.append((run_id, str(exc)))

        async def bad_fn():
            raise RuntimeError("permanent failure")

        with self.assertRaises(RuntimeError):
            asyncio.run(
                retry_on_rate_limit(
                    bad_fn,
                    max_retries=3,
                    run_id="test_run",
                    on_final_failure=on_final_failure_cb,
                )
            )
        self.assertEqual(len(failure_calls), 1)
        self.assertEqual(failure_calls[0][0], "test_run")

    def test_async_callback_is_awaited(self):
        """Async on_rate_limited and on_final_failure callbacks should be awaited."""
        awaited = []

        async def async_rate_limited_cb(run_id, attempt, max_retries):
            awaited.append("rate_limited")

        async def async_final_failure_cb(run_id, exc):
            awaited.append("final_failure")

        call_count = 0

        async def retry_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("429 rate limit")
            return "ok"

        result = asyncio.run(
            retry_on_rate_limit(
                retry_once,
                max_retries=3,
                wait_base=0,
                on_rate_limited=async_rate_limited_cb,
                on_final_failure=async_final_failure_cb,
            )
        )
        self.assertEqual(result, "ok")
        self.assertIn("rate_limited", awaited)
        self.assertNotIn("final_failure", awaited)  # No final failure in this case


class SSEEventsStreamTests(unittest.TestCase):
    """Tests for the sse_events_stream helper."""

    def test_yields_events_until_terminal(self):
        """sse_events_stream should yield events until a terminal event arrives."""
        events = [
            {"kind": "progress", "payload": {"step": 1}},
            {"kind": "progress", "payload": {"step": 2}},
            {"kind": "failed", "payload": {"error": "boom"}},
        ]

        def subscribe_fn(entity_id):
            queue = asyncio.Queue()
            for event in events:
                queue.put_nowait(event)
            return queue

        def unsubscribe_fn(entity_id, queue):
            pass

        result = asyncio.run(
            self._collect_sse(subscribe_fn, unsubscribe_fn, "run_1")
        )
        # Should have 3 events: 2 "progress" + 1 "failed"
        self.assertEqual(len(result), 3)
        self.assertIn("event: progress", result[0])
        self.assertIn("event: progress", result[1])
        self.assertIn("event: failed", result[2])

    def test_unsubscribe_called_on_completion(self):
        """unsubscribe_fn should be called when the stream ends."""
        unsubscribed = []

        def subscribe_fn(entity_id):
            queue = asyncio.Queue()
            queue.put_nowait({"kind": "failed", "payload": {"error": "done"}})
            return queue

        def unsubscribe_fn(entity_id, queue):
            unsubscribed.append((entity_id, queue))

        asyncio.run(
            self._collect_sse(subscribe_fn, unsubscribe_fn, "run_1")
        )
        self.assertEqual(len(unsubscribed), 1)
        self.assertEqual(unsubscribed[0][0], "run_1")

    def test_custom_terminal_kinds(self):
        """Custom terminal_kinds should control when the stream ends."""
        events = [
            {"kind": "completed", "payload": {"status": "done"}},
        ]

        def subscribe_fn(entity_id):
            queue = asyncio.Queue()
            for event in events:
                queue.put_nowait(event)
            return queue

        def unsubscribe_fn(entity_id, queue):
            pass

        result = asyncio.run(
            self._collect_sse(
                subscribe_fn, unsubscribe_fn, "run_1",
                terminal_kinds={"completed"},
            )
        )
        self.assertEqual(len(result), 1)
        self.assertIn("event: completed", result[0])

    async def _collect_sse(self, subscribe_fn, unsubscribe_fn, entity_id,
                           terminal_kinds=None):
        """Collect all SSE events into a list of strings."""
        collected = []
        stream = sse_events_stream(
            subscribe_fn, unsubscribe_fn, entity_id, terminal_kinds
        )
        async for event in stream:
            collected.append(event)
        return collected


class IsRateLimitErrorIntegrationTests(unittest.TestCase):
    """Tests that runner_utils re-exports is_rate_limit_error correctly."""

    def test_is_rate_limit_error_importable_from_runner_utils(self):
        from ui.backend.runner_utils import is_rate_limit_error

        self.assertTrue(is_rate_limit_error(Exception("429 rate limit")))
        self.assertFalse(is_rate_limit_error(Exception("network error")))


if __name__ == "__main__":
    unittest.main()