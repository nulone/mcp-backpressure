"""
Tests for metrics tracking.

Verifies INV-06: After burst → active=0, queued=0
"""

import asyncio

import pytest

from mcp_backpressure import BackpressureMiddleware, BackpressureMetrics, OverloadError
from tests.conftest import BarrierTool


@pytest.fixture
def middleware():
    """Create middleware for metrics testing."""
    return BackpressureMiddleware(max_concurrent=5, queue_size=10, queue_timeout=5.0)


@pytest.mark.asyncio
async def test_metrics_after_burst_returns_to_zero(
    middleware: BackpressureMiddleware,
):
    """
    Test INV-06: After burst → active=0, queued=0.

    Launch many concurrent requests, let them complete, verify clean state.
    """
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Launch burst of N+Q requests
    N = middleware.max_concurrent
    Q = middleware.queue_size
    tasks = [asyncio.create_task(make_request()) for _ in range(N + Q)]

    # Wait for N to be active
    await barrier_tool.wait_entered_at_least(N, timeout=2.0)
    await asyncio.sleep(0.1)

    # Verify during execution
    metrics = middleware.get_metrics()
    assert metrics.active == N
    assert metrics.queued == Q

    # Release and complete
    barrier_tool.release()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Verify INV-06: all counters return to zero
    metrics = middleware.get_metrics()
    assert metrics.active == 0, f"INV-06 violated: active={metrics.active} after burst"
    assert metrics.queued == 0, f"INV-06 violated: queued={metrics.queued} after burst"


@pytest.mark.asyncio
async def test_metrics_track_active_correctly(middleware: BackpressureMiddleware):
    """
    Test that active counter accurately tracks concurrent executions.
    """
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Start with 0
    metrics = middleware.get_metrics()
    assert metrics.active == 0

    # Launch 3 tasks
    tasks = [asyncio.create_task(make_request()) for _ in range(3)]
    await barrier_tool.wait_entered_at_least(3, timeout=2.0)

    # Should show 3 active
    metrics = middleware.get_metrics()
    assert metrics.active == 3

    # Release and wait
    barrier_tool.release()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Should return to 0
    metrics = middleware.get_metrics()
    assert metrics.active == 0


@pytest.mark.asyncio
async def test_metrics_track_queued_correctly(middleware: BackpressureMiddleware):
    """
    Test that queued counter accurately tracks queue size.
    """
    N = middleware.max_concurrent
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Start with 0
    metrics = middleware.get_metrics()
    assert metrics.queued == 0

    # Fill active + queue some
    tasks = [asyncio.create_task(make_request()) for _ in range(N + 3)]
    await barrier_tool.wait_entered_at_least(N, timeout=2.0)
    await asyncio.sleep(0.1)

    # Should show 3 queued
    metrics = middleware.get_metrics()
    assert metrics.queued == 3

    # Release and complete
    barrier_tool.release()
    await asyncio.gather(*tasks, return_exceptions=True)

    # Should return to 0
    metrics = middleware.get_metrics()
    assert metrics.queued == 0


@pytest.mark.asyncio
async def test_metrics_track_rejected_counts(middleware: BackpressureMiddleware):
    """
    Test that rejection counters are incremented correctly.
    """
    N = middleware.max_concurrent
    Q = middleware.queue_size
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await middleware(fake_request, call_next)

    # Start with 0 rejections
    metrics = middleware.get_metrics()
    assert metrics.total_rejected == 0
    assert metrics.rejected_queue_full == 0

    # Fill active + queue
    tasks = [asyncio.create_task(make_request()) for _ in range(N + Q)]
    await barrier_tool.wait_entered_at_least(N, timeout=2.0)
    await asyncio.sleep(0.1)

    # Try 5 more (should be rejected as queue_full)
    rejected_tasks = []
    for _ in range(5):
        rejected_tasks.append(asyncio.create_task(make_request()))

    await asyncio.sleep(0.1)

    # Verify rejections
    for task in rejected_tasks:
        try:
            await task
        except OverloadError:
            pass

    metrics = middleware.get_metrics()
    assert metrics.total_rejected == 5
    assert metrics.rejected_queue_full == 5
    assert metrics.rejected_concurrency_limit == 0
    assert metrics.rejected_queue_timeout == 0

    # Cleanup
    barrier_tool.release()
    for task in tasks:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_metrics_track_timeout_rejections():
    """
    Test that queue_timeout rejections are tracked separately.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=3, queue_timeout=0.3)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active + queue
    tasks = [asyncio.create_task(make_request()) for _ in range(2 + 3)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)
    await asyncio.sleep(0.1)

    # Wait for queue timeouts
    await asyncio.sleep(0.4)

    # Verify timeout rejections
    metrics = mw.get_metrics()
    assert metrics.rejected_queue_timeout == 3
    assert metrics.total_rejected == 3

    # Cleanup
    barrier_tool.release()
    for task in tasks:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_metrics_track_concurrency_limit_rejections():
    """
    Test that concurrency_limit rejections (no queue) are tracked.
    """
    mw = BackpressureMiddleware(max_concurrent=3, queue_size=0, queue_timeout=1.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active
    tasks = [asyncio.create_task(make_request()) for _ in range(3)]
    await barrier_tool.wait_entered_at_least(3, timeout=2.0)

    # Try 4 more (should be rejected as concurrency_limit)
    rejected_tasks = []
    for _ in range(4):
        rejected_tasks.append(asyncio.create_task(make_request()))

    await asyncio.sleep(0.1)

    # Collect rejections
    for task in rejected_tasks:
        try:
            await task
        except OverloadError:
            pass

    metrics = mw.get_metrics()
    assert metrics.total_rejected == 4
    assert metrics.rejected_concurrency_limit == 4
    assert metrics.rejected_queue_full == 0
    assert metrics.rejected_queue_timeout == 0

    # Cleanup
    barrier_tool.release()
    for task in tasks:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_metrics_separate_rejection_reasons():
    """
    Test that different rejection reasons are tracked separately.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=2, queue_timeout=0.3)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Fill active + queue
    tasks = [asyncio.create_task(make_request()) for _ in range(2 + 2)]
    await barrier_tool.wait_entered_at_least(2, timeout=2.0)
    await asyncio.sleep(0.1)

    # Try 2 more (should be rejected as queue_full)
    queue_full_tasks = [asyncio.create_task(make_request()) for _ in range(2)]
    await asyncio.sleep(0.1)

    # Wait for queue timeouts (original 2 queued)
    await asyncio.sleep(0.4)

    # Collect queue_full rejections
    for task in queue_full_tasks:
        try:
            await task
        except OverloadError:
            pass

    # Verify separation
    metrics = mw.get_metrics()
    assert metrics.rejected_queue_full == 2
    assert metrics.rejected_queue_timeout == 2
    assert metrics.total_rejected == 4

    # Cleanup: release barrier and collect active tasks
    barrier_tool.release()
    for task in tasks:
        try:
            await task
        except OverloadError:
            pass


@pytest.mark.asyncio
async def test_metrics_dataclass_fields():
    """
    Test that BackpressureMetrics dataclass has all required fields.
    """
    mw = BackpressureMiddleware(max_concurrent=5, queue_size=10, queue_timeout=5.0)
    metrics = mw.get_metrics()

    # Verify all fields exist
    assert hasattr(metrics, "active")
    assert hasattr(metrics, "queued")
    assert hasattr(metrics, "total_rejected")
    assert hasattr(metrics, "rejected_concurrency_limit")
    assert hasattr(metrics, "rejected_queue_full")
    assert hasattr(metrics, "rejected_queue_timeout")

    # Verify types
    assert isinstance(metrics.active, int)
    assert isinstance(metrics.queued, int)
    assert isinstance(metrics.total_rejected, int)
    assert isinstance(metrics.rejected_concurrency_limit, int)
    assert isinstance(metrics.rejected_queue_full, int)
    assert isinstance(metrics.rejected_queue_timeout, int)


@pytest.mark.asyncio
async def test_get_metrics_async_is_consistent():
    """
    Test that get_metrics_async() returns consistent snapshot.
    """
    mw = BackpressureMiddleware(max_concurrent=5, queue_size=10, queue_timeout=5.0)
    barrier_tool = BarrierTool()

    async def call_next(request):
        return await barrier_tool()

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Launch some tasks
    tasks = [asyncio.create_task(make_request()) for _ in range(7)]
    await barrier_tool.wait_entered_at_least(5, timeout=2.0)
    await asyncio.sleep(0.1)

    # Get metrics both ways
    metrics_sync = mw.get_metrics()
    metrics_async = await mw.get_metrics_async()

    # Should be consistent
    assert metrics_sync.active == metrics_async.active
    assert metrics_sync.queued == metrics_async.queued

    # Cleanup
    barrier_tool.release()
    for task in tasks:
        try:
            await task
        except Exception:
            pass


@pytest.mark.asyncio
async def test_metrics_persistent_across_bursts():
    """
    Test that rejection counters persist across multiple bursts.
    """
    mw = BackpressureMiddleware(max_concurrent=2, queue_size=1, queue_timeout=5.0)

    async def call_next(request):
        await asyncio.sleep(0.01)
        return {"ok": True}

    async def make_request():
        fake_request = {"type": "tool_call"}
        return await mw(fake_request, call_next)

    # Burst 1: fill and reject 2
    tasks1 = [asyncio.create_task(make_request()) for _ in range(5)]
    await asyncio.gather(*tasks1, return_exceptions=True)

    metrics = mw.get_metrics()
    rejected_after_burst1 = metrics.total_rejected
    assert rejected_after_burst1 == 2  # 5 - 2 active - 1 queued = 2 rejected

    # Burst 2: fill and reject 3 more
    tasks2 = [asyncio.create_task(make_request()) for _ in range(6)]
    await asyncio.gather(*tasks2, return_exceptions=True)

    metrics = mw.get_metrics()
    rejected_after_burst2 = metrics.total_rejected
    assert rejected_after_burst2 == rejected_after_burst1 + 3

    # Verify clean state
    assert metrics.active == 0
    assert metrics.queued == 0


@pytest.mark.asyncio
async def test_metrics_exported_in_public_api():
    """
    Test that BackpressureMetrics is exported in public API.
    """
    from mcp_backpressure import BackpressureMetrics

    # Should be importable
    assert BackpressureMetrics is not None

    # Should be a dataclass
    import dataclasses

    assert dataclasses.is_dataclass(BackpressureMetrics)
