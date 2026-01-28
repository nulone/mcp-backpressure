"""
Tests for request cancellation handling.

Verifies INV-03, INV-04: Cancellation correctly frees slots and decrements counters.
"""

import asyncio

import pytest

from mcp_backpressure import BackpressureMiddleware
from tests.conftest import BarrierTool


@pytest.fixture
def middleware():
    """Create middleware with queue for cancellation testing."""
    return BackpressureMiddleware(max_concurrent=2, queue_size=3, queue_timeout=5.0)


@pytest.mark.asyncio
async def test_cancel_while_queued_frees_slot(middleware: BackpressureMiddleware):
    """
    Test INV-03: Cancel while queued → slot freed.

    Verify that cancelling a queued request:
    1. Decrements queued counter
    2. Frees the queue slot for other requests
    3. No permit/slot leaks
    """
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Fill active slots (max_concurrent=2)
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)

    # Verify active slots full
    assert middleware.active == 2
    assert middleware.queued == 0

    # Queue one request (will wait in queue)
    queued_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.1)

    # Verify queued
    assert middleware.queued == 1
    assert middleware.active == 2

    # Cancel the queued request
    queued_task.cancel()

    # Wait for cancellation to propagate
    try:
        await queued_task
        pytest.fail("Expected CancelledError")
    except asyncio.CancelledError:
        pass

    # Give middleware time to clean up
    await asyncio.sleep(0.1)

    # Verify queued counter decremented (slot freed)
    assert middleware.queued == 0, (
        f"Expected queued=0 after cancel, got {middleware.queued}"
    )

    # Verify another request can take the freed queue slot
    new_queued_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.1)

    assert middleware.queued == 1, (
        "New request should queue successfully after cancel freed slot"
    )

    # Cleanup
    new_queued_task.cancel()
    try:
        await new_queued_task
    except asyncio.CancelledError:
        pass

    barrier_tool.release()
    for task in active_tasks:
        try:
            await task
        except Exception:
            pass

    # Verify no leaks
    await asyncio.sleep(0.1)
    assert middleware.active == 0, f"Active leak: {middleware.active}"
    assert middleware.queued == 0, f"Queue leak: {middleware.queued}"


@pytest.mark.asyncio
async def test_cancel_while_active_decrements_counter(
    middleware: BackpressureMiddleware,
):
    """
    Test INV-04: Cancel while active → counter decremented.

    Verify that cancelling an active (executing) request:
    1. Decrements active counter
    2. Releases semaphore permit
    3. Allows queued request to proceed
    """
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Fill active slots
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)

    assert middleware.active == 2

    # Queue one request (will wait)
    queued_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.1)

    assert middleware.queued == 1

    # Cancel one active task
    active_tasks[0].cancel()

    # Wait for cancellation
    try:
        await active_tasks[0]
        pytest.fail("Expected CancelledError")
    except asyncio.CancelledError:
        pass

    # Give middleware time to clean up and promote queued request
    await asyncio.sleep(0.1)

    # Active counter should have decremented then incremented (queued promoted)
    # So still at 2 (one cancelled, one promoted from queue)
    # But queued should now be 0
    assert middleware.queued == 0, (
        f"Queued request should be promoted after active cancel, got queued={middleware.queued}"
    )

    # The queued task should now be executing (waiting at barrier)
    # Release barrier to complete
    barrier_tool.release()

    # Wait for queued task (now active) to complete
    result = await queued_task
    assert result == {"ok": True}

    # Wait for remaining active task
    try:
        await active_tasks[1]
    except Exception:
        pass

    # Verify no leaks
    await asyncio.sleep(0.1)
    assert middleware.active == 0
    assert middleware.queued == 0


@pytest.mark.asyncio
async def test_no_permit_leak_on_cancel():
    """
    Test that cancellation never leaks permits or queue slots.

    Cancel requests at various stages and verify clean state.
    """
    mw = BackpressureMiddleware(max_concurrent=3, queue_size=5, queue_timeout=10.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active slots
    active_tasks = [asyncio.create_task(make_request()) for _ in range(3)]
    await barrier_tool.wait_entered_at_least(3, timeout=2.0)

    assert mw.active == 3

    # Queue several requests
    queued_tasks = [asyncio.create_task(make_request()) for _ in range(5)]
    await asyncio.sleep(0.1)

    assert mw.queued == 5

    # Cancel some queued requests
    for i in [0, 2, 4]:
        queued_tasks[i].cancel()

    # Wait for cancellations
    for i in [0, 2, 4]:
        try:
            await queued_tasks[i]
        except asyncio.CancelledError:
            pass

    await asyncio.sleep(0.1)

    # Queued should be decremented by 3
    assert mw.queued == 2, f"Expected queued=2 after 3 cancels, got {mw.queued}"

    # Cancel one active task
    active_tasks[1].cancel()
    try:
        await active_tasks[1]
    except asyncio.CancelledError:
        pass

    await asyncio.sleep(0.1)

    # One queued should be promoted to active
    assert mw.queued == 1, (
        f"Expected queued=1 after active cancel promoted one, got {mw.queued}"
    )

    # Release barrier
    barrier_tool.release()

    # Wait for all remaining tasks
    for task in active_tasks + queued_tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    # Verify clean state
    await asyncio.sleep(0.2)
    assert mw.active == 0, f"Active leak: {mw.active}"
    assert mw.queued == 0, f"Queue leak: {mw.queued}"


@pytest.mark.asyncio
async def test_cancel_before_acquiring_semaphore():
    """
    Test cancellation of request before it acquires execution semaphore.
    """
    mw = BackpressureMiddleware(max_concurrent=1, queue_size=2, queue_timeout=5.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active slot
    active_task = asyncio.create_task(make_request())
    await barrier_tool.wait_entered_at_least(1, timeout=2.0)

    # Queue request
    queued_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.05)

    assert mw.queued == 1

    # Cancel immediately (before semaphore acquired)
    queued_task.cancel()

    try:
        await queued_task
        pytest.fail("Expected CancelledError")
    except asyncio.CancelledError:
        pass

    await asyncio.sleep(0.1)

    # Verify queue freed
    assert mw.queued == 0

    # Verify new request can queue
    new_task = asyncio.create_task(make_request())
    await asyncio.sleep(0.05)

    assert mw.queued == 1

    # Cleanup
    barrier_tool.release()
    for task in [active_task, new_task]:
        try:
            await task
        except Exception:
            pass

    await asyncio.sleep(0.1)
    assert mw.active == 0
    assert mw.queued == 0


@pytest.mark.asyncio
async def test_multiple_cancellations_preserve_invariants():
    """
    Test that multiple simultaneous cancellations maintain invariants.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=8, queue_timeout=10.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active
    active_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)

    # Fill queue
    queued_tasks = [asyncio.create_task(make_request()) for _ in range(8)]
    await asyncio.sleep(0.1)

    assert mw.active == 2
    assert mw.queued == 8

    # Cancel half of queued tasks simultaneously
    cancel_indices = [0, 2, 4, 6]
    for i in cancel_indices:
        queued_tasks[i].cancel()

    # Wait for all cancellations
    for i in cancel_indices:
        try:
            await queued_tasks[i]
        except asyncio.CancelledError:
            pass

    await asyncio.sleep(0.1)

    # Verify counters
    assert mw.queued == 4, f"Expected queued=4 after 4 cancels, got {mw.queued}"
    assert mw.active == 2, f"Expected active=2, got {mw.active}"

    # Cleanup
    barrier_tool.release()
    for task in active_tasks + queued_tasks:
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    await asyncio.sleep(0.2)
    assert mw.active == 0
    assert mw.queued == 0
