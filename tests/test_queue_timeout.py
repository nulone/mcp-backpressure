"""
Tests for queue timeout behavior.

Verifies INV-05: Queue timeout → removes item from queue
"""

import asyncio
import time

import pytest

from mcp_backpressure import BackpressureMiddleware, OverloadError
from tests.conftest import BarrierTool


@pytest.fixture
def middleware():
    """Create middleware with short timeout for testing."""
    return BackpressureMiddleware(
        max_concurrent=2, queue_size=3, queue_timeout=0.5  # 500ms timeout
    )


@pytest.mark.asyncio
async def test_queue_timeout_rejects_with_correct_reason(
    middleware: BackpressureMiddleware,
):
    """
    Test that requests waiting in queue longer than queue_timeout are rejected
    with reason='queue_timeout'.
    """
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Fill active slots (will block at barrier)
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)

    # Now launch a request that will queue
    queued_task = asyncio.create_task(make_request())

    # Wait a moment for it to enter queue
    await asyncio.sleep(0.1)
    assert middleware.queued == 1

    # Wait for timeout (500ms + margin)
    await asyncio.sleep(0.6)

    # The queued task should have timed out
    try:
        result = await queued_task
        pytest.fail(f"Expected OverloadError but got result: {result}")
    except OverloadError as e:
        assert e.reason == "queue_timeout", f"Expected 'queue_timeout', got '{e.reason}'"
        assert e.code == -32001
        assert e.message == "SERVER_OVERLOADED"
        assert e.queue_timeout_ms == 500

    # Verify queued count decremented
    assert middleware.queued == 0, f"Expected queued=0, got {middleware.queued}"

    # Cleanup
    barrier_tool.release()
    for task in active_tasks:
        try:
            await task
        except Exception:
            pass

    metrics = middleware.get_metrics()
    assert metrics.active == 0
    assert metrics.queued == 0


@pytest.mark.asyncio
async def test_queue_timeout_removes_from_queue():
    """
    Test INV-05: Queue timeout → removes item from queue.

    Verify that queued counter decrements when timeout occurs.
    """
    mw = BackpressureMiddleware(max_concurrent=1, queue_size=5, queue_timeout=0.3)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active slot
    active_task = asyncio.create_task(make_request())
    await barrier_tool.wait_entered_at_least(1, timeout=2.0)

    # Queue 3 requests
    queued_tasks = [asyncio.create_task(make_request()) for _ in range(3)]
    await asyncio.sleep(0.1)

    # Verify queued
    assert mw.queued == 3

    # Wait for timeouts
    await asyncio.sleep(0.4)

    # All queued should have timed out
    for task in queued_tasks:
        try:
            await task
            pytest.fail("Expected OverloadError")
        except OverloadError as e:
            assert e.reason == "queue_timeout"

    # Verify queue is empty
    assert mw.queued == 0

    # Cleanup
    barrier_tool.release()
    try:
        await active_task
    except Exception:
        pass

    metrics = mw.get_metrics()
    assert metrics.active == 0
    assert metrics.queued == 0


@pytest.mark.asyncio
async def test_queue_timeout_uses_monotonic_time():
    """
    Test that queue timeout uses monotonic time (not affected by system time changes).

    We can't actually change system time in tests, but we verify timeout accuracy.
    """
    mw = BackpressureMiddleware(max_concurrent=1, queue_size=2, queue_timeout=0.4)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active
    active_task = asyncio.create_task(make_request())
    await barrier_tool.wait_entered_at_least(1, timeout=2.0)

    # Queue one request and measure timeout
    start = time.monotonic()
    queued_task = asyncio.create_task(make_request())

    await asyncio.sleep(0.1)
    assert mw.queued == 1

    try:
        await queued_task
        pytest.fail("Expected OverloadError")
    except OverloadError as e:
        elapsed = time.monotonic() - start
        assert e.reason == "queue_timeout"
        # Should timeout around 400ms (±100ms margin)
        assert 0.3 < elapsed < 0.6, f"Timeout took {elapsed:.3f}s, expected ~0.4s"

    # Cleanup
    barrier_tool.release()
    try:
        await active_task
    except Exception:
        pass


@pytest.mark.asyncio
async def test_multiple_requests_timeout_independently():
    """
    Test that multiple queued requests timeout independently based on enqueue time.
    """
    mw = BackpressureMiddleware(max_concurrent=1, queue_size=5, queue_timeout=0.5)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active
    active_task = asyncio.create_task(make_request())
    await barrier_tool.wait_entered_at_least(1, timeout=2.0)

    # Queue requests with staggered timing
    task1 = asyncio.create_task(make_request())
    await asyncio.sleep(0.2)

    task2 = asyncio.create_task(make_request())
    await asyncio.sleep(0.1)

    # task1 should timeout first (enqueued earlier)
    await asyncio.sleep(0.3)  # Total: task1=500ms, task2=400ms

    # task1 should have timed out
    try:
        await task1
        pytest.fail("Expected task1 to timeout")
    except OverloadError as e:
        assert e.reason == "queue_timeout"

    # task2 may or may not have timed out yet (depends on exact timing)

    # Cleanup
    barrier_tool.release()
    for task in [active_task, task2]:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_queue_timeout_before_execution():
    """
    Test that timeout can occur before request gets to execute.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=10, queue_timeout=0.2)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active slots
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)

    # Queue many requests (they'll all timeout before active slots free)
    queued_tasks = [asyncio.create_task(make_request()) for _ in range(5)]

    # Wait for all to queue
    await asyncio.sleep(0.1)
    assert mw.queued == 5

    # Wait for timeouts (don't release barrier)
    await asyncio.sleep(0.3)

    # All queued should have timed out
    timeout_count = 0
    for task in queued_tasks:
        try:
            await task
        except OverloadError as e:
            if e.reason == "queue_timeout":
                timeout_count += 1

    assert timeout_count == 5, f"Expected 5 timeouts, got {timeout_count}"
    assert mw.queued == 0

    # Cleanup
    barrier_tool.release()
    for task in active_tasks:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_queue_timeout_error_payload():
    """
    Verify error payload for queue_timeout has all required fields.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=3, queue_timeout=0.3)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)

    # Queue one
    queued_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.1)

    # Wait for timeout
    await asyncio.sleep(0.3)

    try:
        await queued_task
        pytest.fail("Expected OverloadError")
    except OverloadError as e:
        # Verify all fields
        assert e.reason == "queue_timeout"
        assert e.code == -32001
        assert e.message == "SERVER_OVERLOADED"
        assert e.active == 2
        assert e.max_concurrent == 2
        assert e.queued == 0  # Already decremented
        assert e.queue_size == 3
        assert e.queue_timeout_ms == 300
        assert e.retry_after_ms == 1000

        # Verify JSON-RPC format
        json_rpc = e.to_json_rpc()
        assert json_rpc["code"] == -32001
        assert json_rpc["data"]["reason"] == "queue_timeout"
        assert json_rpc["data"]["queue_timeout_ms"] == 300

    # Cleanup
    barrier_tool.release()
    for task in active_tasks:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_zero_timeout_rejects_immediately():
    """
    Test that queue_timeout must be > 0 (constructor validation).
    """
    with pytest.raises(ValueError, match="queue_timeout must be > 0"):
        BackpressureMiddleware(max_concurrent=5, queue_size=10, queue_timeout=0)

    with pytest.raises(ValueError, match="queue_timeout must be > 0"):
        BackpressureMiddleware(max_concurrent=5, queue_size=10, queue_timeout=-1.0)


@pytest.mark.asyncio
async def test_queue_processes_non_timed_out_requests():
    """
    Test that queue continues processing requests that haven't timed out.
    """
    mw = BackpressureMiddleware(max_concurrent=1, queue_size=5, queue_timeout=2.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active
    active_task = asyncio.create_task(make_request())
    await barrier_tool.wait_entered_at_least(1, timeout=2.0)

    # Queue 3 requests (should not timeout with 2s limit)
    queued_tasks = [asyncio.create_task(make_request()) for _ in range(3)]
    await asyncio.sleep(0.1)

    assert mw.queued == 3

    # Release barrier relatively quickly (before timeout)
    await asyncio.sleep(0.2)
    barrier_tool.release()

    # All should succeed
    results = await asyncio.gather(active_task, *queued_tasks, return_exceptions=True)

    success_count = sum(1 for r in results if not isinstance(r, Exception))
    assert success_count == 4, f"Expected 4 successes, got {success_count}"

    # Verify clean state
    metrics = mw.get_metrics()
    assert metrics.active == 0
    assert metrics.queued == 0
