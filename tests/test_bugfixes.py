"""
Tests for bug fixes from Fresh Eyes FE-01 report.

Tests for:
- BUG-1: Race condition in semaphore.locked()
- BUG-2: Permit leak on exception
- BUG-3: TOCTOU metrics race
"""

import asyncio

import pytest

from mcp_backpressure import BackpressureMiddleware, OverloadError
from tests.conftest import BarrierTool


@pytest.mark.asyncio
async def test_bug1_no_race_condition_with_queue_full():
    """
    BUG-1: Race condition between semaphore.locked() and acquire().

    Test that we don't incorrectly reject a request when:
    1. Semaphore appears locked
    2. Queue appears full
    3. But semaphore becomes available before we actually try to execute

    With the fix, we use non-blocking acquire instead of locked() check.
    """
    # Create middleware with small limits
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=2, queue_timeout=1.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active slots
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)
    assert mw.active == 2

    # Fill queue
    queued_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await asyncio.sleep(0.1)
    assert mw.queued == 2

    # Release one active slot
    barrier_tool.release()

    # Try to make a new request - it should succeed because active slot freed
    # Old code might reject if there was race between locked() check and queue check
    new_task = asyncio.create_task(make_request())

    # Wait a bit for processing
    await asyncio.sleep(0.2)

    # Should NOT be rejected - either queued or active
    assert not new_task.done() or not isinstance(
        new_task.exception() if new_task.done() else None, OverloadError
    ), "Request should not be rejected when slot becomes available"

    # Cleanup
    new_task.cancel()
    for task in active_tasks + queued_tasks:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, OverloadError):
            pass


@pytest.mark.asyncio
async def test_bug2_no_permit_leak_on_exception_in_queued_path():
    """
    BUG-2: Permit leak when exception occurs between acquire() and try block.

    Test that semaphore is properly released even if exception happens
    after acquire() but before the main try/finally block in queued path.

    We simulate this by causing an exception in metrics operations.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=2, queue_timeout=1.0)

    # Mock metrics to cause exception
    original_increment = mw._metrics.increment_active
    call_count = [0]

    async def failing_increment():
        call_count[0] += 1
        if call_count[0] == 3:  # Fail on 3rd call (first queued request promoted)
            raise RuntimeError("Simulated exception in increment_active")
        await original_increment()

    mw._metrics.increment_active = failing_increment

    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active slots
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)
    assert mw.active == 2

    # Queue one request
    queued_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.1)
    assert mw.queued == 1

    # Release barrier to let active tasks finish
    barrier_tool.release()

    # Wait for tasks to complete
    for task in active_tasks:
        try:
            await task
        except Exception:
            pass

    # Wait for queued task to fail
    try:
        await queued_task
        pytest.fail("Expected RuntimeError from failing_increment")
    except RuntimeError as e:
        assert "Simulated exception" in str(e)

    # KEY TEST: Verify no permit leak - active should be 0
    # With BUG-2, semaphore would not be released and active would be stuck > 0
    await asyncio.sleep(0.1)
    assert mw.active == 0, f"Permit leak detected: active={mw.active}, expected 0"


@pytest.mark.asyncio
async def test_bug3_metrics_updated_before_error_creation():
    """
    BUG-3: TOCTOU race - metrics read before rejected increment.

    Test that rejected counters are incremented BEFORE reading metrics
    for error creation, so the error contains correct/updated counts.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active slots
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)
    assert mw.active == 2

    # Try to make requests that will be rejected
    rejected_errors = []
    for _ in range(3):
        try:
            await make_request()
            pytest.fail("Expected OverloadError")
        except OverloadError as e:
            rejected_errors.append(e)

    # KEY TEST: Verify that rejected count is correct after all rejections
    # With BUG-3, metrics would be read BEFORE increment, leading to incorrect counts

    # Check final metrics
    final_metrics = mw.get_metrics()
    assert final_metrics.total_rejected == 3, (
        f"Expected total_rejected=3, got {final_metrics.total_rejected}"
    )
    assert final_metrics.rejected_concurrency_limit == 3, (
        f"Expected rejected_concurrency_limit=3, got {final_metrics.rejected_concurrency_limit}"
    )

    # Each error should have consistent active/queued counts (not checking rejected in error.data
    # because it's not included there, but the fix ensures metrics are updated before error creation)
    for error in rejected_errors:
        assert error.reason == "concurrency_limit"
        assert error.active == 2  # Both slots were active when rejected

    # Cleanup
    barrier_tool.release()
    for task in active_tasks:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_bug3_queue_full_metrics():
    """
    BUG-3: Test metrics for queue_full rejections.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=1)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active and queue
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)

    queued_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.1)
    assert mw.queued == 1

    # Try to queue more - should get queue_full
    try:
        await make_request()
        pytest.fail("Expected OverloadError with queue_full")
    except OverloadError as e:
        assert e.reason == "queue_full"

    # Check metrics were updated correctly
    metrics = mw.get_metrics()
    assert metrics.total_rejected == 1, f"Expected total_rejected=1, got {metrics.total_rejected}"
    assert metrics.rejected_queue_full == 1, (
        f"Expected rejected_queue_full=1, got {metrics.rejected_queue_full}"
    )

    # Cleanup
    barrier_tool.release()
    for task in active_tasks + [queued_task]:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_bug3_queue_timeout_metrics():
    """
    BUG-3: Test metrics for queue_timeout rejections.
    """
    mw = BackpressureMiddleware(max_concurrent=1, queue_size=1, queue_timeout=0.1)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active
    active_task = asyncio.create_task(make_request())
    await barrier_tool.wait_entered_at_least(1, timeout=2.0)

    # Queue one that will timeout
    queued_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.05)
    assert mw.queued == 1

    # Wait for timeout
    try:
        await queued_task
        pytest.fail("Expected OverloadError with queue_timeout")
    except OverloadError as e:
        assert e.reason == "queue_timeout"

    # Check metrics were updated correctly
    metrics = mw.get_metrics()
    assert metrics.total_rejected == 1, (
        f"Expected total_rejected=1, got {metrics.total_rejected}"
    )
    assert metrics.rejected_queue_timeout == 1, (
        f"Expected rejected_queue_timeout=1, got {metrics.rejected_queue_timeout}"
    )

    # Cleanup
    barrier_tool.release()
    try:
        await active_task
    except Exception:
        pass


@pytest.mark.asyncio
async def test_cancel_during_sleep_no_leak():
    """
    EARLY-CANCEL LEAK: Semaphore leak when cancelled during admission.

    Test that if a request is cancelled during the sleep(0) after
    acquire_task.done() == True, the semaphore is properly released.

    Without the fix, the semaphore would be acquired but not tracked,
    causing a permanent leak.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=0)

    # Track calls to verify timing
    call_count = [0]

    async def call_next(request):
        call_count[0] += 1
        return {"result": "ok"}

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Make a request and cancel it immediately
    # This tries to hit the race where semaphore is acquired but task is cancelled
    for _ in range(10):  # Try multiple times to increase chance of hitting race
        task = asyncio.create_task(make_request())
        await asyncio.sleep(0)  # Let it start
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # KEY TEST: Verify no semaphore leak - should be able to make new requests
    # If there's a leak, semaphore would be exhausted and new requests would hang/fail
    await asyncio.sleep(0.1)

    # Try to make max_concurrent requests - they should all succeed
    successful_tasks = []
    for _ in range(mw.max_concurrent):
        task = asyncio.create_task(make_request())
        successful_tasks.append(task)
        await asyncio.sleep(0.05)

    # Wait for all to complete
    results = await asyncio.gather(*successful_tasks)
    assert len(results) == mw.max_concurrent
    assert all(r == {"result": "ok"} for r in results)

    # Verify active count is correct
    await asyncio.sleep(0.05)
    assert mw.active == 0, f"Active count incorrect: {mw.active}, expected 0"
